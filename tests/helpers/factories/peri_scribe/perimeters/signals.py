"""Build inputs for signals tests."""

from __future__ import annotations

import datetime
import typing

import peri_scribe.perimeters.classification_data
from peri_scribe.units import units


if typing.TYPE_CHECKING:
    import shapely.geometry


FIRIS = peri_scribe.perimeters.classification_data.FireSourceKind.FIRIS_PERIMETER


WFIGS_PERIMETER = (
    peri_scribe.perimeters.classification_data.FireSourceKind.WFIGS_PERIMETER
)


WFIGS_LOCATION = (
    peri_scribe.perimeters.classification_data.FireSourceKind.WFIGS_LOCATION
)


def observation(
    source: peri_scribe.perimeters.classification_data.FireSourceKind,
    geometry: shapely.geometry.base.BaseGeometry | None,
    *,
    observed_at: datetime.datetime | None = None,
    serial_number: int = 0,
    identifiers: frozenset[str] = frozenset(),
    mission: str | None = None,
    point_of_origin_state: str | None = None,
    point_of_origin_fips: str | None = None,
) -> peri_scribe.perimeters.classification_data.FireObservation:
    """Build a fire observation for a test.

    Args:
        source: Source family supplying the fire observation.
        geometry: Geometry supplied for the selected spatial case.
        observed_at: Observation time attached to the mapping, or None if unknown.
        serial_number: Snapshot sequence number used in the bucket and filename.
        identifiers: Fire identifiers supplied for identity matching.
        mission: Mapping mission identifier, or None when unavailable.
        point_of_origin_state: Reported origin state, or None when unavailable.
        point_of_origin_fips: Reported origin FIPS code, or None when unavailable.

    Returns:
        The fire observation.
    """
    return peri_scribe.perimeters.classification_data.FireObservation(
        source=source,
        geometry=geometry,
        observed_at=observed_at,
        serial_number=serial_number,
        identifiers=identifiers,
        mission=mission,
        point_of_origin_state=point_of_origin_state,
        point_of_origin_fips=point_of_origin_fips,
    )


def geometry_signal(
    *,
    distance_to_boundary: float = 100.0,
    outside_area_fraction: float = 0.0,
    outside_area: float = 0.0,
    inside_area_fraction: float = 1.0,
    crosses: bool = False,
    near: bool = False,
    inside: bool = True,
) -> peri_scribe.perimeters.classification_data.GeometrySignal:
    """Build a geometry signal, defaulting to a fire fully inside California.

    Args:
        distance_to_boundary: Distance to the boundary in meters.
        outside_area_fraction: Fraction of the mapped area outside the boundary.
        outside_area: Mapped area outside the boundary in square meters.
        inside_area_fraction: Fraction of the mapped area inside the boundary.
        crosses: Whether the mapped footprint crosses the boundary.
        near: Whether the mapped footprint lies near the boundary.
        inside: Whether the mapped footprint lies inside the boundary.

    Returns:
        The geometry signal.
    """
    return peri_scribe.perimeters.classification_data.GeometrySignal(
        distance_to_boundary=distance_to_boundary * units.meters,
        outside_area_fraction=outside_area_fraction,
        outside_area=outside_area * units.Unit("meters ** 2"),
        inside_area_fraction=inside_area_fraction,
        crosses=crosses,
        near=near,
        inside=inside,
    )


def extent_signal(
    *,
    wfigs_to_firis_area_ratio: float | None = None,
    disagrees: bool = False,
) -> peri_scribe.perimeters.classification_data.ExtentSignal:
    """Build an extent signal, defaulting to no disagreement.

    Args:
        wfigs_to_firis_area_ratio: Ratio of WFIGS to FIRIS area, or None if unavailable.
        disagrees: Whether the two source extents disagree.

    Returns:
        The extent signal.
    """
    return peri_scribe.perimeters.classification_data.ExtentSignal(
        wfigs_to_firis_area_ratio=wfigs_to_firis_area_ratio,
        disagrees=disagrees,
    )


CONFIG = peri_scribe.perimeters.classification_data.BorderClassificationConfig()


PLANAR_CONFIG = peri_scribe.perimeters.classification_data.BorderClassificationConfig(
    near_border_buffer=10.0 * units.meters,
)
