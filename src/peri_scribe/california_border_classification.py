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
import us.states

import peri_scribe.administrative_boundaries
import peri_scribe.models
import peri_scribe.units


CALIFORNIA_STATE_ABBREVIATION = us.states.CA.abbr.casefold()
CALIFORNIA_STATE_CODE = f"us-{us.states.CA.abbr.casefold()}"
CALIFORNIA_FIPS_PREFIX = typing.cast("str", us.states.CA.fips)

STATE_CODE_LENGTH = 2


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
    return int(path.stem.split(",", 1)[0])


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


def load_boundaries(base_dir: pathlib.Path) -> Boundaries:
    """Load the California box and the interstate border, in California Albers.

    Args:
        base_dir: The base directory that holds the ``data`` directory.

    Returns:
        The California box and the interstate border in California Albers.
    """
    border = peri_scribe.administrative_boundaries.load_border_geometry(base_dir)
    box = peri_scribe.administrative_boundaries.california_box_polygon(border)
    return Boundaries(
        box=reproject_to_california_albers(box, 4326),
        border=reproject_to_california_albers(border, 4326),
    )


def union_geometry(
    observations: typing.Iterable[FireObservation],
) -> shapely.Geometry | None:
    """Return the union of the observations' geometries in California Albers.

    Args:
        observations: The fire's observations.

    Returns:
        The union geometry in California Albers, or None when there is none.
    """
    geometries: list[shapely.Geometry] = []
    for observation in observations:
        geometry = observation.geometry
        if geometry is None or geometry.is_empty:
            continue
        geometries.append(
            reproject_to_california_albers(
                geometry,
                SOURCE_SPATIAL_REFERENCE_IDS[observation.source],
            ),
        )
    if not geometries:
        return None
    return shapely.union_all(geometries)


def geometry_signal(
    union: shapely.Geometry | None,
    boundaries: Boundaries,
    config: BorderClassificationConfig,
) -> GeometrySignal:
    """Compute the geometry signal for *union* against the California box.

    The portion of the union lying inside the box is inside California (or in the
    ocean or Mexico sliver the box absorbs); the rest lies on the far side of the
    interstate border. A fire crosses the border when it lies on both sides of it. A
    fire is inside when most of it lies within the box.

    Args:
        union: The fire's union geometry in California Albers, or None.
        boundaries: The California box and the interstate border in CA Albers.
        config: The classification thresholds.

    Returns:
        The distance, area measurements, and whether the geometry crosses or is near
        the border, and whether it is inside California.
    """
    if union is None or union.is_empty:
        return GeometrySignal(
            distance_to_boundary_in_meters=float("inf"),
            outside_area_fraction=0.0,
            outside_area_in_acres=0.0,
            inside_area_fraction=0.0,
            crosses=False,
            near=False,
            inside=False,
        )
    inside_area_in_square_meters = union.intersection(
        boundaries.box,
    ).area
    total_area_in_square_meters = union.area
    outside_area_in_square_meters = max(
        0.0,
        total_area_in_square_meters - inside_area_in_square_meters,
    )
    inside_area_fraction = (
        inside_area_in_square_meters / total_area_in_square_meters
        if total_area_in_square_meters > 0
        else 0.0
    )
    outside_area_fraction = (
        outside_area_in_square_meters / total_area_in_square_meters
        if total_area_in_square_meters > 0
        else 0.0
    )
    outside_area_in_acres = (
        outside_area_in_square_meters / peri_scribe.units.SQUARE_METERS_PER_ACRE
    )
    crosses = inside_area_fraction > 0 and (
        outside_area_fraction > config.outside_area_fraction_threshold
        or outside_area_in_acres > config.outside_area_threshold_in_acres
    )
    distance_to_boundary_in_meters = union.distance(boundaries.border)
    near = (
        not crosses
        and distance_to_boundary_in_meters <= config.near_border_buffer_in_meters
    )
    inside = inside_area_fraction >= config.inside_area_fraction_threshold
    return GeometrySignal(
        distance_to_boundary_in_meters=distance_to_boundary_in_meters,
        outside_area_fraction=outside_area_fraction,
        outside_area_in_acres=outside_area_in_acres,
        inside_area_fraction=inside_area_fraction,
        crosses=crosses,
        near=near,
        inside=inside,
    )


def freshest_observation(
    observations: list[FireObservation],
) -> FireObservation:
    """Return the freshest observation in *observations*.

    Recency is decided by observation time first and snapshot serial number second,
    so a perimeter with a later mapping time wins, and equally timed snapshots are
    broken by the newest file.

    Args:
        observations: A non-empty list of observations.

    Returns:
        The freshest observation.

    Raises:
        ValueError: If *observations* is empty.
    """
    if not observations:
        message = "cannot pick the freshest observation from an empty list"
        raise ValueError(message)

    def recency_key(observation: FireObservation) -> tuple[datetime.datetime, int]:
        observed_at = observation.observed_at or peri_scribe.models.EARLIEST_DATETIME
        return observed_at, observation.serial_number

    return max(observations, key=recency_key)


def are_contemporaneous(
    left: FireObservation,
    right: FireObservation,
    config: BorderClassificationConfig,
) -> bool:
    """Return whether two perimeters were mapped at close enough times to compare.

    Perimeters with no observation time can only be compared to each other, since there
    is no way to tell when either was mapped.

    Args:
        left: One perimeter observation.
        right: The other perimeter observation.
        config: The classification thresholds.

    Returns:
        True when the two perimeters are close enough in time to compare.
    """
    if left.observed_at is None and right.observed_at is None:
        return True
    if left.observed_at is None or right.observed_at is None:
        return False
    difference = abs(left.observed_at - right.observed_at)
    return difference <= config.contemporaneous_tolerance


def extent_signal(
    observations: list[FireObservation],
    config: BorderClassificationConfig,
) -> ExtentSignal:
    """Compute the FIRIS-versus-WFIGS extent signal.

    The freshest FIRIS perimeter and the freshest WFIGS perimeter are compared when they
    are contemporaneous. A WFIGS perimeter that is substantially larger than the FIRIS
    perimeter of the same fire suggests the fire extends beyond what FIRIS mapped.

    Args:
        observations: The fire's observations.
        config: The classification thresholds.

    Returns:
        The area ratio and whether the extents disagree.
    """
    firis = [
        observation
        for observation in observations
        if observation.source is FireSourceKind.FIRIS_PERIMETER
        and observation.geometry is not None
        and not observation.geometry.is_empty
    ]
    wfigs = [
        observation
        for observation in observations
        if observation.source is FireSourceKind.WFIGS_PERIMETER
        and observation.geometry is not None
        and not observation.geometry.is_empty
    ]
    if not firis or not wfigs:
        return ExtentSignal(wfigs_to_firis_area_ratio=None, disagrees=False)
    firis_freshest = freshest_observation(firis)
    wfigs_freshest = freshest_observation(wfigs)
    if not are_contemporaneous(firis_freshest, wfigs_freshest, config):
        return ExtentSignal(wfigs_to_firis_area_ratio=None, disagrees=False)
    firis_geometry = reproject_to_california_albers(
        typing.cast("shapely.Geometry", firis_freshest.geometry),
        SOURCE_SPATIAL_REFERENCE_IDS[firis_freshest.source],
    )
    wfigs_geometry = reproject_to_california_albers(
        typing.cast("shapely.Geometry", wfigs_freshest.geometry),
        SOURCE_SPATIAL_REFERENCE_IDS[wfigs_freshest.source],
    )
    firis_area = firis_geometry.area
    wfigs_area = wfigs_geometry.area
    ratio = wfigs_area / firis_area if firis_area > 0 else None
    if ratio is None or firis_area <= 0:
        return ExtentSignal(wfigs_to_firis_area_ratio=ratio, disagrees=False)
    symmetric_difference_area = wfigs_geometry.symmetric_difference(
        firis_geometry,
    ).area
    disagrees = wfigs_area > firis_area * config.extent_ratio_threshold or (
        wfigs_area > firis_area
        and symmetric_difference_area
        > firis_area * config.symmetric_difference_fraction_threshold
    )
    return ExtentSignal(wfigs_to_firis_area_ratio=ratio, disagrees=disagrees)


def unit_state_code_is_out_of_state(token: str) -> bool:
    """Return whether *token* embeds a non-California US state code.

    Args:
        token: A fire unit or mission token.

    Returns:
        True when the token starts with a recognized state code other than California's.
    """
    folded = token.casefold()
    if len(folded) < STATE_CODE_LENGTH:
        return False
    state_code = folded[:STATE_CODE_LENGTH]
    return (
        us.states.lookup(state_code) is not None
        and state_code != CALIFORNIA_STATE_ABBREVIATION
    )


def state_tokens_from_mission(mission: str) -> list[str]:
    """Return the state-code tokens a mission code can carry.

    A mission that is itself a unique fire identifier (``YYYY-UNIT-######``) carries the
    state in its unit token. Otherwise the state is the mission's leading token when
    that token is a two-letter code, as in ``NV-CCD-BUG``.

    Args:
        mission: The fire's mapping mission code.

    Returns:
        The mission's state-code candidate tokens.
    """
    if peri_scribe.models.is_unique_fire_identifier(mission):
        return [mission.split("-")[1]]
    first = mission.split("-", 1)[0]
    return [first] if len(first) == STATE_CODE_LENGTH else []


def out_of_state_unit_from(
    identifiers: frozenset[str],
    mission: str | None,
) -> bool:
    """Return whether a fire identifier or mission names an out-of-state unit.

    Args:
        identifiers: The fire's identifiers.
        mission: The fire's mapping mission code, or None.

    Returns:
        True when any identifier unit or mission token embeds a non-California state.
    """
    tokens = [
        identifier.split("-")[1]
        for identifier in identifiers
        if peri_scribe.models.is_unique_fire_identifier(identifier)
    ]
    if mission is not None:
        tokens.extend(state_tokens_from_mission(mission))
    return any(unit_state_code_is_out_of_state(token) for token in tokens)


def identifier_signal(observations: list[FireObservation]) -> bool:
    """Return whether any observation carries an out-of-state identifier signal.

    Args:
        observations: The fire's observations.

    Returns:
        True when an identifier, mission, or point of origin names a non-California
        home.
    """
    for observation in observations:
        if out_of_state_unit_from(
            observation.identifiers,
            observation.mission,
        ):
            return True
        if (
            observation.point_of_origin_state is not None
            and observation.point_of_origin_state.casefold() != CALIFORNIA_STATE_CODE
        ):
            return True
        if (
            observation.point_of_origin_fips is not None
            and not observation.point_of_origin_fips.startswith(CALIFORNIA_FIPS_PREFIX)
        ):
            return True
    return False


def classify(
    *,
    geometry: GeometrySignal,
    extent: ExtentSignal,
    identifier: bool,
) -> peri_scribe.models.FireClassification:
    """Combine the three signals into a border classification.

    CROSSES_CALIFORNIA_BORDER requires the geometry to span the California border.
    A fire that does not cross is INSIDE_CALIFORNIA or OUTSIDE_CALIFORNIA, with the
    near-border variants when it is within the near-border buffer or the FIRIS and
    WFIGS extents disagree. The identifier signal only ever appears in the evidence;
    it never changes the classification on its own.

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
            source=source_kind_for_feed_name(path.parent.name),
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
        geometry=geometry_signal(union_geometry(observations), boundaries, config),
        extent=extent_signal(observations, config),
        identifier=identifier_signal(observations),
    )
