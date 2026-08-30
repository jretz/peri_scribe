"""Classify fires relative to the California state boundary.

A fire is classified as INSIDE_CALIFORNIA, INSIDE_CALIFORNIA_NEAR_BORDER,
CROSSES_CALIFORNIA_BORDER, OUTSIDE_CALIFORNIA_NEAR_BORDER, or OUTSIDE_CALIFORNIA by
combining three signals. The primary signal compares the fire's geometry with a
"California box" that traces the border California shares with its neighboring US
states (Arizona, Nevada, and Oregon) and closes well out into the Pacific Ocean and
Mexico, so maritime and international borders are absorbed into the box. The secondary
signal compares contemporaneous FIRIS and WFIGS perimeters, where a WFIGS perimeter
that is substantially larger suggests the fire extends beyond what FIRIS mapped. The
tertiary signal flags out-of-state fire units and points of origin.
CROSSES_CALIFORNIA_BORDER requires the geometry to span the California border; the
weaker signals only ever support the near-border classifications.
"""

from __future__ import annotations

import dataclasses
import datetime
import enum
import functools
import pathlib
import typing

import numpy as np
import pyproj
import shapely

import peri_scribe.models
import peri_scribe.perimeters.signals
import peri_scribe.sources.administrative_boundaries
import peri_scribe.sources.borders
import peri_scribe.sources.snapshots


class FireSourceKind(enum.Enum):
    """The kind of source a fire observation came from."""

    FIRIS_PERIMETER = "firis_perimeter"
    WFIGS_PERIMETER = "wfigs_perimeter"
    WFIGS_LOCATION = "wfigs_location"


SOURCE_SPATIAL_REFERENCE_IDS = {
    FireSourceKind.FIRIS_PERIMETER: peri_scribe.models.NAD83_SPATIAL_REFERENCE_ID,
    FireSourceKind.WFIGS_PERIMETER: peri_scribe.models.WGS84_SPATIAL_REFERENCE_ID,
    FireSourceKind.WFIGS_LOCATION: peri_scribe.models.NAD83_SPATIAL_REFERENCE_ID,
}


@dataclasses.dataclass(frozen=True, kw_only=True)
class BorderClassificationConfig:
    """Thresholds for classifying a fire relative to the state boundary.

    All thresholds are configurable so they can be tuned against known fires.
    """

    outside_area_fraction_threshold: float = 0.01
    outside_area_threshold_in_acres: float = 500.0
    inside_area_fraction_threshold: float = 0.5
    near_border_buffer_in_meters: float = 10_000.0
    extent_ratio_threshold: float = 1.05
    symmetric_difference_fraction_threshold: float = 0.05
    contemporaneous_tolerance: datetime.timedelta = datetime.timedelta(hours=24)


@dataclasses.dataclass(frozen=True, kw_only=True)
class Boundaries:
    """The California box and the interstate border it traces, in CA Albers."""

    box: shapely.Geometry
    border: shapely.Geometry


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
class GeometrySignal:
    """What the fire's geometry says about the state boundary."""

    distance_to_boundary_in_meters: float
    outside_area_fraction: float
    outside_area_in_acres: float
    inside_area_fraction: float
    crosses: bool
    near: bool
    inside: bool


@dataclasses.dataclass(frozen=True, kw_only=True)
class ExtentSignal:
    """What the FIRIS and WFIGS perimeter comparison says."""

    wfigs_to_firis_area_ratio: float | None
    disagrees: bool


def source_kind_for_feed_name(feed_name: str) -> FireSourceKind:
    """Return the source kind for a source directory name.

    Args:
        feed_name: The feed's name, which doubles as its source directory name.

    Returns:
        The source kind the feed represents.

    Raises:
        ValueError: If the feed name does not name a known fire source.
    """
    if "CA_Perimeters_NIFC_FIRIS" in feed_name:
        return FireSourceKind.FIRIS_PERIMETER
    if "WFIGS_Interagency_Perimeters" in feed_name:
        return FireSourceKind.WFIGS_PERIMETER
    if "WFIGS_Incident_Locations" in feed_name:
        return FireSourceKind.WFIGS_LOCATION
    message = f"unknown fire source directory {feed_name!r}"
    raise ValueError(message)


def snapshot_serial_number(path: pathlib.Path) -> int:
    """Return the snapshot serial number encoded in a GeoPackage filename.

    Args:
        path: The GeoPackage path.

    Returns:
        The serial number from the filename.
    """
    return peri_scribe.sources.snapshots.SourceFile.from_path(path).serial_number


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
        peri_scribe.models.CALIFORNIA_ALBERS_SPATIAL_REFERENCE_ID,
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
    if shapely.has_z(geometry):
        return shapely.transform(
            geometry,
            lambda coordinates: np.column_stack(
                transformer.transform(
                    coordinates[:, 0],
                    coordinates[:, 1],
                    coordinates[:, 2],
                ),
            ),
            include_z=True,
        )
    return shapely.transform(
        geometry,
        lambda coordinates: np.column_stack(
            transformer.transform(
                coordinates[:, 0],
                coordinates[:, 1],
            ),
        ),
    )


def load_boundaries(year_directory: pathlib.Path) -> Boundaries:
    """Load the California box and the interstate border, in California Albers.

    Args:
        year_directory: The year directory that holds the ``sources`` directory.

    Returns:
        The California box and the interstate border in California Albers.
    """
    border = peri_scribe.sources.administrative_boundaries.load_border_geometry(
        year_directory,
    )
    box = peri_scribe.sources.borders.california_box_polygon(border)
    return Boundaries(
        box=reproject_to_california_albers(box, 4326),
        border=reproject_to_california_albers(border, 4326),
    )


def union_geometry(
    observations: typing.Iterable[FireObservation],
    boundaries: Boundaries,
) -> shapely.Geometry | None:
    """Return a geometry describing the observations in California Albers.

    Observations of the same fire frequently repeat the same mapped geometry, so
    byte-identical (source, geometry) pairs are collapsed before re-projection: the
    re-projection is deterministic, and the union of the distinct geometries is the same
    shape as the union of all of them. A single distinct geometry is returned as itself,
    since the union of one geometry is the geometry.

    When every distinct geometry lies entirely on one side of the California box, the
    parts are returned unmerged as a collection instead of being unioned. The
    classification's geometry signal recognizes such a one-sided collection and reads
    the exact signal values from the parts: a one-sided fire's area fractions are 0 or
    1, its border distance is the minimum over the parts, and it cannot cross the
    border. Only a fire whose geometry straddles the box needs the true union, since
    overlapping parts on both sides change the area fractions.

    Args:
        observations: The fire's observations.
        boundaries: The California box and interstate border in CA Albers.

    Returns:
        The union (or unmerged collection) of the distinct geometries in California
        Albers, or None when there are none.
    """
    seen: set[tuple[FireSourceKind, bytes]] = set()
    distinct: list[tuple[FireObservation, shapely.Geometry]] = []
    for observation in observations:
        geometry = observation.geometry
        if geometry is None or geometry.is_empty:
            continue
        key = (observation.source, geometry.wkb)
        if key in seen:
            continue
        seen.add(key)
        distinct.append((observation, geometry))
    geometries: list[shapely.Geometry] = []
    for observation, geometry in distinct:
        geometries.append(
            reproject_to_california_albers(
                geometry,
                SOURCE_SPATIAL_REFERENCE_IDS[observation.source],
            ),
        )
    if not geometries:
        return None
    if len(geometries) == 1:
        return geometries[0]
    box = boundaries.box
    if all(box.contains(geometry) for geometry in geometries) or all(
        not box.intersects(geometry) for geometry in geometries
    ):
        return shapely.GeometryCollection(geometries)
    return shapely.union_all(geometries)


def classify(
    *,
    geometry: GeometrySignal,
    extent: ExtentSignal,
    identifier: bool,
) -> peri_scribe.models.FireClassification:
    """Combine the three signals into a border classification.

    CROSSES_CALIFORNIA_BORDER requires the geometry to span the California border. A
    fire that does not cross is INSIDE_CALIFORNIA or OUTSIDE_CALIFORNIA, with the
    near-border variants when it is within the near-border buffer or the FIRIS and WFIGS
    extents disagree. The identifier signal only ever appears in the evidence; it never
    changes the classification on its own.

    Args:
        geometry: The geometry signal.
        extent: The extent disagreement signal.
        identifier: Whether the identifier signal fired.

    Returns:
        The classification with its evidence.
    """
    signals: list[peri_scribe.models.BorderSignal] = []
    if geometry.crosses:
        signals.append(peri_scribe.models.BorderSignal.GEOMETRY_OUTSIDE)
    if geometry.near:
        signals.append(peri_scribe.models.BorderSignal.GEOMETRY_NEAR)
    if extent.disagrees:
        signals.append(peri_scribe.models.BorderSignal.EXTENT_DISAGREEMENT)
    if identifier:
        signals.append(peri_scribe.models.BorderSignal.IDENTIFIER_UNIT)

    if geometry.crosses:
        classification = (
            peri_scribe.models.BorderClassification.CROSSES_CALIFORNIA_BORDER
        )
    elif geometry.near or extent.disagrees:
        if geometry.inside:
            classification = (
                peri_scribe.models.BorderClassification.INSIDE_CALIFORNIA_NEAR_BORDER
            )
        else:
            classification = (
                peri_scribe.models.BorderClassification.OUTSIDE_CALIFORNIA_NEAR_BORDER
            )
    elif geometry.inside:
        classification = peri_scribe.models.BorderClassification.INSIDE_CALIFORNIA
    else:
        classification = peri_scribe.models.BorderClassification.OUTSIDE_CALIFORNIA

    return peri_scribe.models.FireClassification(
        classification=classification,
        distance_to_boundary_in_meters=geometry.distance_to_boundary_in_meters,
        outside_area_fraction=geometry.outside_area_fraction,
        inside_area_fraction=geometry.inside_area_fraction,
        wfigs_to_firis_area_ratio=extent.wfigs_to_firis_area_ratio,
        signals=signals,
    )


def classify_fire(
    *,
    records: typing.Iterable[peri_scribe.models.FireRecord],
    record_paths: typing.Iterable[pathlib.Path],
    boundaries: Boundaries,
    config: BorderClassificationConfig | None = None,
) -> peri_scribe.models.FireClassification:
    """Classify one fire from its records and source files.

    Args:
        records: The fire's records, aligned with *record_paths*.
        record_paths: The GeoPackage file each record came from.
        boundaries: The California polygon and border in California Albers.
        config: The classification thresholds. Defaults to the standard thresholds.

    Returns:
        The fire's border classification and evidence.
    """
    if config is None:
        config = BorderClassificationConfig()
    observations = [
        FireObservation(
            source=source_kind_for_feed_name(
                peri_scribe.sources.snapshots.source_name_from_snapshot_path(path),
            ),
            geometry=record.geometry,
            observed_at=record.observed_at,
            serial_number=snapshot_serial_number(path),
            identifiers=record.identifiers,
            mission=record.mission,
            point_of_origin_state=record.point_of_origin_state,
            point_of_origin_fips=record.point_of_origin_fips,
        )
        for record, path in zip(records, record_paths, strict=True)
    ]
    return classify(
        geometry=peri_scribe.perimeters.signals.geometry_signal(
            union_geometry(observations, boundaries),
            boundaries,
            config,
        ),
        extent=peri_scribe.perimeters.signals.extent_signal(observations, config),
        identifier=peri_scribe.perimeters.signals.identifier_signal(observations),
    )
