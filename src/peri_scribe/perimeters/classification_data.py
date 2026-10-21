"""Shared evidence and geometry preparation for border classification.

[Geometry policy](../../../docs/algorithms/perimeter-geometry-policy.md)
"""

from __future__ import annotations

import dataclasses
import datetime
import enum
import functools
import threading
import typing

import pyproj
import shapely

import spatial_data.geometry
import spatial_data.reference
from measurement_units import units


if typing.TYPE_CHECKING:
    import pint


class FireSourceKind(enum.Enum):
    """The kind of source a fire observation came from."""

    FIRIS_PERIMETER = "firis_perimeter"
    WFIGS_PERIMETER = "wfigs_perimeter"
    WFIGS_LOCATION = "wfigs_location"


SOURCE_SPATIAL_REFERENCE_IDS = {
    FireSourceKind.FIRIS_PERIMETER: spatial_data.reference.NAD83_SPATIAL_REFERENCE_ID,
    FireSourceKind.WFIGS_PERIMETER: spatial_data.reference.WGS84_SPATIAL_REFERENCE_ID,
    FireSourceKind.WFIGS_LOCATION: spatial_data.reference.NAD83_SPATIAL_REFERENCE_ID,
}


@dataclasses.dataclass(frozen=True, kw_only=True)
class BorderClassificationConfig:
    """Thresholds for classifying a fire relative to the state boundary.

    All thresholds are configurable so they can be tuned against known fires.
    """

    outside_area_fraction_threshold: float = 0.01
    outside_area_threshold: pint.Quantity[float] = 500.0 * units.acres
    inside_area_fraction_threshold: float = 0.5
    near_border_buffer: pint.Quantity[float] = 10.0 * units.km
    extent_ratio_threshold: float = 1.05
    symmetric_difference_fraction_threshold: float = 0.05
    contemporaneous_tolerance: datetime.timedelta = datetime.timedelta(hours=24)


@dataclasses.dataclass(frozen=True, kw_only=True)
class Boundaries:
    """The California box and the interstate border it traces, in CA Albers."""

    box: shapely.Geometry
    border: shapely.Geometry
    prepared_boxes: threading.local = dataclasses.field(
        default_factory=threading.local,
        init=False,
        repr=False,
        compare=False,
    )

    @property
    def prepared_box(self) -> shapely.Geometry:
        """Own native prepared-predicate caches separately in each worker thread.

        Returns:
            A prepared clone with identical coordinates, precision, and reference.
        """
        prepared = typing.cast(
            "shapely.Geometry | None",
            getattr(self.prepared_boxes, "geometry", None),
        )
        if prepared is None:
            prepared = shapely.set_srid(self.box, shapely.get_srid(self.box))
            shapely.prepare(prepared)
            self.prepared_boxes.geometry = prepared
        return prepared


@dataclasses.dataclass(frozen=True, kw_only=True)
class PreparedObservationGeometry:
    """Carry exact one-sided collection evidence without repeating box predicates."""

    geometry: shapely.Geometry | None
    parts: tuple[shapely.Geometry, ...] = ()
    inside_box: bool | None = None


@dataclasses.dataclass(frozen=True, kw_only=True)
class FireObservation:
    """One fire perimeter or location, labeled with its source and attributes."""

    source: FireSourceKind
    geometry: shapely.Geometry | None
    observed_at: datetime.datetime | None
    serial_number: int
    identifiers: frozenset[str] = dataclasses.field(default_factory=frozenset)
    mission: str | None = None
    point_of_origin_state: str | None = None
    point_of_origin_fips: str | None = None


@dataclasses.dataclass(frozen=True, kw_only=True)
class GeometryEvidence:
    """Boundary evidence sufficient for the complete classification result.

    One-sided collections supply these exact fractions, flags, and distance without
    constructing an absolute-area union.
    """

    distance_to_boundary: pint.Quantity[float]
    outside_area_fraction: float
    inside_area_fraction: float
    crosses: bool
    near: bool
    inside: bool


@dataclasses.dataclass(frozen=True, kw_only=True)
class GeometrySignal(GeometryEvidence):
    """Boundary evidence with the exact absolute area outside the state box."""

    outside_area: pint.Quantity[float]


@dataclasses.dataclass(frozen=True, kw_only=True)
class ExtentSignal:
    """What the FIRIS and WFIGS perimeter comparison says."""

    wfigs_to_firis_area_ratio: float | None
    disagrees: bool


@functools.cache
def transformer_for_spatial_reference_id(
    source_spatial_reference_id: int,
) -> pyproj.Transformer:
    """Return the transformer from *source_spatial_reference_id* to California Albers.

    The transformer is cached because every fire's perimeters are re-projected, and
    building the PROJ pipeline per geometry dominates the re-projection cost.

    Args:
        source_spatial_reference_id: The EPSG id the geometry is currently in.

    Returns:
        The transformer to California Albers.
    """
    return pyproj.Transformer.from_crs(
        source_spatial_reference_id,
        spatial_data.reference.CALIFORNIA_ALBERS_SPATIAL_REFERENCE_ID,
        always_xy=True,
    )


def reproject_to_california_albers(
    geometry: shapely.Geometry,
    source_spatial_reference_id: int,
) -> shapely.Geometry:
    """Return *geometry* re-projected into California Albers.

    Args:
        geometry: The geometry to re-project.
        source_spatial_reference_id: The EPSG id the geometry is currently in.

    Returns:
        The geometry in California Albers.
    """
    transformer = transformer_for_spatial_reference_id(source_spatial_reference_id)
    return spatial_data.geometry.transform_coordinates(geometry, transformer)


class ProjectionCache:
    """Retain exact object/reference-system projections for one classification."""

    def __init__(self) -> None:
        """Release projected geometry when its owning classification finishes."""
        self.entries: dict[
            tuple[int, int],
            tuple[shapely.Geometry, shapely.Geometry],
        ] = {}

    def project(
        self,
        geometry: shapely.Geometry,
        source_spatial_reference_id: int,
    ) -> shapely.Geometry:
        """Reuse a projection only for the same retained object and source CRS.

        Args:
            geometry: Immutable coordinates interpreted in the supplied reference.
            source_spatial_reference_id: EPSG ID establishing that interpretation.

        Returns:
            The exact result of the classification's deterministic projection.
        """
        key = id(geometry), source_spatial_reference_id
        entry = self.entries.get(key)
        if entry is not None:
            return entry[1]
        projected = reproject_to_california_albers(
            geometry,
            source_spatial_reference_id,
        )
        self.entries[key] = geometry, projected
        return projected
