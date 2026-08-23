"""Reconciling perimeter and point observations into versioned history.

Turns each source row into a labeled observation, collapses and merges observations
that describe the same moment, and drops perimeters whose geometry collapsed below the
size the source reports. The attribute-value helpers used to read a row's fields live
here because both versioning and row construction share them.
"""

from __future__ import annotations

import dataclasses
import datetime
import pathlib
import typing

import peri_scribe.california_border_classification
import peri_scribe.changes
import peri_scribe.geo_package
import peri_scribe.history_attributes
import peri_scribe.models
import peri_scribe.snapshots
import peri_scribe.units


if typing.TYPE_CHECKING:
    import shapely


CONTEMPORANEOUS_TOLERANCE = datetime.timedelta(hours=4)


FIRIS_PERIMETER = (
    peri_scribe.california_border_classification.FireSourceKind.FIRIS_PERIMETER
)


WFIGS_PERIMETER = (
    peri_scribe.california_border_classification.FireSourceKind.WFIGS_PERIMETER
)


WFIGS_LOCATION = (
    peri_scribe.california_border_classification.FireSourceKind.WFIGS_LOCATION
)


WFIGS_PREFERRED_CLASSIFICATIONS = frozenset(
    {
        peri_scribe.models.BorderClassification.CROSSES_CALIFORNIA_BORDER,
        peri_scribe.models.BorderClassification.OUTSIDE_CALIFORNIA_NEAR_BORDER,
        peri_scribe.models.BorderClassification.OUTSIDE_CALIFORNIA,
    },
)


@dataclasses.dataclass(frozen=True, kw_only=True)
class SourceObservation:
    """One fire row observed in a source snapshot, labeled for versioning."""

    source_kind: peri_scribe.california_border_classification.FireSourceKind
    geometry: shapely.Geometry | None
    observation_time: datetime.datetime | None
    snapshot_time: datetime.datetime | None
    serial_number: int
    object_id: int | None
    source_file: str
    attributes: dict[str, object]


COMPUTED_AREA_COLUMNS = (
    "poly_Acres_AutoCalc",
    "poly_GISAcres",
    "area_acres",
)


INCIDENT_SIZE_COLUMNS = (
    "attr_IncidentSize",
    "attr_FinalAcres",
)


@dataclasses.dataclass(frozen=True, kw_only=True)
class PerimeterSizeFilterConfig:
    """Thresholds for dropping a perimeter whose geometry collapsed.

    A perimeter is dropped when its geometry area is smaller than one of these
    fractions of the size the source reports for the same row. The computed-area
    fraction is generous because the polygon's computed area should match its
    geometry; the incident-size fraction is strict because the incident size
    legitimately runs ahead of the mapped extent early in a fire.
    """

    minimum_computed_area_fraction: float = 0.2
    minimum_incident_area_fraction: float = 0.01


DEFAULT_SIZE_FILTER_CONFIG = PerimeterSizeFilterConfig()


def last_edit_time_from(path: pathlib.Path) -> datetime.datetime | None:
    """Return the snapshot's last-edit time encoded in *path*, or None.

    Args:
        path: A GeoPackage snapshot path.

    Returns:
        The last-edit time as a UTC datetime, or None when it cannot be read.
    """
    try:
        last_edit_timestamp = peri_scribe.snapshots.SourceFile.from_path(
            path
        ).last_edit_timestamp
    except ValueError:
        return None
    return datetime.datetime.fromtimestamp(
        last_edit_timestamp / peri_scribe.units.MILLISECONDS_PER_SECOND,
        tz=datetime.UTC,
    )


def source_observation_from_row(
    row: peri_scribe.geo_package.FireRowRecord,
    path: pathlib.Path,
    sources_directory: pathlib.Path,
) -> SourceObservation:
    """Return the source observation for *row* read from *path*.

    Args:
        row: A fire row read from a GeoPackage.
        path: The GeoPackage the row came from.
        sources_directory: The directory the source path is relative to.

    Returns:
        The observation with its source kind, times, provenance, and attributes.
    """
    return SourceObservation(
        source_kind=(
            peri_scribe.california_border_classification.source_kind_for_feed_name(
                row.source_name,
            )
        ),
        geometry=row.record.geometry,
        observation_time=row.record.observed_at,
        snapshot_time=last_edit_time_from(path),
        serial_number=(peri_scribe.snapshots.SourceFile.from_path(path).serial_number),
        object_id=row.object_id,
        source_file=str(path.relative_to(sources_directory)),
        attributes=row.attributes,
    )


def effective_time(
    observation: SourceObservation,
) -> datetime.datetime | None:
    """Return the observation's mapping time, falling back to its own edit time.

    The mapping time is the feed's observation column when present. A perimeter whose
    observation column is empty falls back to the row's current-date column
    (``poly_DateCurrent``) and then to the row's modified-time column, so a perimeter
    without a polygon date still carries the date its source reports it is current
    for. The snapshot's last-edit timestamp is the last resort: it describes when the
    layer last changed, not when the row was mapped, and dating a dateless perimeter
    by it can make a stale re-published row look like the newest mapping.

    Args:
        observation: The observation to time.

    Returns:
        The mapping time, the current date, the row's modified time, or the snapshot
        time, in that order.
    """
    if observation.observation_time is not None:
        return observation.observation_time
    current_date = peri_scribe.history_attributes.datetime_attribute(
        observation.attributes,
        "poly_DateCurrent",
    )
    if current_date is not None:
        return current_date
    modified_time = peri_scribe.history_attributes.datetime_attribute(
        observation.attributes,
        "EditDate",
        "attr_ModifiedOnDateTime_dt",
    )
    if modified_time is not None:
        return modified_time
    return observation.snapshot_time


def perimeter_sort_key(
    observation: SourceObservation,
) -> tuple[datetime.datetime, int, int]:
    """Return the ordering key for a perimeter observation.

    Args:
        observation: The observation to order.

    Returns:
        The effective time, serial number, and object id used for ordering.
    """
    time = effective_time(observation)
    resolved = time if time is not None else peri_scribe.models.EARLIEST_DATETIME
    return (resolved, observation.serial_number, observation.object_id or -1)


def geometries_are_equal(
    left: shapely.Geometry | None,
    right: shapely.Geometry | None,
) -> bool:
    """Return whether two geometries describe the same shape.

    Args:
        left: One geometry, or None.
        right: The other geometry, or None.

    Returns:
        True when the geometries are equal, or when both are None or empty.
    """
    return peri_scribe.geo_package.geometries_describe_same_shape(left, right)


def collapse_identical_consecutive_perimeters(
    observations: list[SourceObservation],
) -> list[SourceObservation]:
    """Collapse consecutive observations that share a geometry.

    A run of observations with equal geometry becomes one version carrying the newest
    observation's attributes and provenance.

    Args:
        observations: The perimeter observations for one source and fire.

    Returns:
        One observation per geometry change, in observation order.
    """
    ordered = sorted(observations, key=perimeter_sort_key)
    versions: list[SourceObservation] = []
    for observation in ordered:
        if versions and geometries_are_equal(
            versions[-1].geometry,
            observation.geometry,
        ):
            versions[-1] = observation
        else:
            versions.append(observation)
    return versions


def observations_are_contemporaneous(
    left: SourceObservation,
    right: SourceObservation,
) -> bool:
    """Return whether two observations were mapped close enough in time.

    Args:
        left: One observation.
        right: The other observation.

    Returns:
        True when the observations' effective times are within the tolerance.
    """
    left_time = effective_time(left)
    right_time = effective_time(right)
    if left_time is None and right_time is None:
        return True
    if left_time is None or right_time is None:
        return False
    return abs(left_time - right_time) <= CONTEMPORANEOUS_TOLERANCE


def preferred_perimeter_source(
    classification: peri_scribe.models.FireClassification | None,
) -> peri_scribe.california_border_classification.FireSourceKind:
    """Return the perimeter source most likely to be correct for a fire.

    WFIGS is preferred when a fire crosses or sits outside California, where it maps
    the full extent. FIRIS is preferred for fires inside California, including those
    near the border.

    Args:
        classification: The fire's border classification, or None.

    Returns:
        The preferred perimeter source kind.
    """
    if (
        classification is not None
        and classification.classification in WFIGS_PREFERRED_CLASSIFICATIONS
    ):
        return WFIGS_PERIMETER
    return FIRIS_PERIMETER


def preferred_pair(
    left: SourceObservation,
    right: SourceObservation,
    preferred: peri_scribe.california_border_classification.FireSourceKind,
) -> tuple[SourceObservation, SourceObservation]:
    """Return the preferred observation first among a pair.

    Args:
        left: One observation.
        right: The other observation.
        preferred: The preferred source kind.

    Returns:
        The preferred and non-preferred observations, in that order.
    """
    if left.source_kind is preferred:
        return left, right
    return right, left


def merge_observations(
    winner: SourceObservation,
    loser: SourceObservation,
) -> SourceObservation:
    """Return one observation merging *winner* over *loser*.

    The winner keeps its provenance and geometry; the attributes are the union of both,
    with the winner's values taking precedence on conflicts.

    Args:
        winner: The preferred observation.
        loser: The non-preferred observation.

    Returns:
        The merged observation.
    """
    return SourceObservation(
        source_kind=winner.source_kind,
        geometry=winner.geometry,
        observation_time=winner.observation_time,
        snapshot_time=winner.snapshot_time,
        serial_number=winner.serial_number,
        object_id=winner.object_id,
        source_file=winner.source_file,
        attributes={**loser.attributes, **winner.attributes},
    )


def identical_observation_index(
    versions: list[SourceObservation],
    observation: SourceObservation,
) -> int | None:
    """Return the index of a version matching *observation*, or None.

    Args:
        versions: The versions collected so far.
        observation: The observation to match.

    Returns:
        The index of a contemporaneous version with equal geometry, or None.
    """
    for index, existing in enumerate(versions):
        if geometries_are_equal(
            existing.geometry,
            observation.geometry,
        ) and observations_are_contemporaneous(existing, observation):
            return index
    return None


def merge_identical_observations(
    observations: list[SourceObservation],
    preferred: peri_scribe.california_border_classification.FireSourceKind,
) -> list[SourceObservation]:
    """Merge contemporaneous observations that share a geometry.

    Args:
        observations: The perimeter observations, sorted by time.
        preferred: The preferred source kind.

    Returns:
        The observations with equal-geometry pairs merged, in time order.
    """
    versions: list[SourceObservation] = []
    for observation in observations:
        merge_index = identical_observation_index(versions, observation)
        if merge_index is None:
            versions.append(observation)
        else:
            existing = versions[merge_index]
            winner, loser = preferred_pair(existing, observation, preferred)
            versions[merge_index] = merge_observations(winner, loser)
    return versions


def keep_preferred_in_window(
    window: list[SourceObservation],
    preferred: peri_scribe.california_border_classification.FireSourceKind,
) -> list[SourceObservation]:
    """Return the observations to keep from one time window.

    When a window holds perimeters from both sources, only the preferred source's
    observations are kept.

    Args:
        window: The observations in one time window.
        preferred: The preferred source kind.

    Returns:
        The observations to keep.
    """
    kinds = {observation.source_kind for observation in window}
    if FIRIS_PERIMETER in kinds and WFIGS_PERIMETER in kinds:
        return [
            observation
            for observation in window
            if observation.source_kind is preferred
        ]
    return window


def drop_losing_source_versions(
    versions: list[SourceObservation],
    preferred: peri_scribe.california_border_classification.FireSourceKind,
) -> list[SourceObservation]:
    """Drop the non-preferred source within each time window.

    Args:
        versions: The merged perimeter observations.
        preferred: The preferred source kind.

    Returns:
        The observations with conflicting non-preferred versions removed.
    """
    if not versions:
        return []
    ordered = sorted(versions, key=perimeter_sort_key)
    result: list[SourceObservation] = []
    window = [ordered[0]]
    window_start = effective_time(ordered[0])
    for observation in ordered[1:]:
        time = effective_time(observation)
        if (
            window_start is not None
            and time is not None
            and (time - window_start) <= CONTEMPORANEOUS_TOLERANCE
        ):
            window.append(observation)
        else:
            result.extend(keep_preferred_in_window(window, preferred))
            window = [observation]
            window_start = time
    result.extend(keep_preferred_in_window(window, preferred))
    return result


def reconcile_perimeter_versions(
    firis_observations: list[SourceObservation],
    wfigs_observations: list[SourceObservation],
    classification: peri_scribe.models.FireClassification | None,
) -> list[SourceObservation]:
    """Reconcile the two perimeter sources into one version list.

    Equal geometries observed within the tolerance merge into one version. Where the
    two sources disagree within the tolerance, the preferred source wins.

    Args:
        firis_observations: The FIRIS perimeter versions for one fire.
        wfigs_observations: The WFIGS perimeter versions for one fire.
        classification: The fire's border classification, or None.

    Returns:
        The reconciled perimeter versions, in observation order.
    """
    preferred = preferred_perimeter_source(classification)
    observations = sorted(
        firis_observations + wfigs_observations,
        key=perimeter_sort_key,
    )
    versions = merge_identical_observations(observations, preferred)
    return drop_losing_source_versions(versions, preferred)


def geometry_area_in_acres(
    geometry: shapely.Geometry | None,
) -> float | None:
    """Return *geometry*'s area in acres, or None when it has none.

    The area is computed geodesically so it is accurate anywhere on Earth.

    Args:
        geometry: The perimeter geometry, in degree coordinates, or None.

    Returns:
        The absolute area in acres, or None when *geometry* is missing or empty.
    """
    if geometry is None or geometry.is_empty:
        return None
    return peri_scribe.units.area_in_acres(geometry)


def computed_area_in_acres(
    attributes: dict[str, object],
) -> float | None:
    """Return the polygon's computed area for one row, in acres.

    The computed-area columns hold the source's own area for the polygon, so a healthy
    row's geometry should nearly equal this value.

    Args:
        attributes: The row's attributes.

    Returns:
        The first positive computed area in acres, or None when the row reports none.
    """
    for column in COMPUTED_AREA_COLUMNS:
        value = peri_scribe.history_attributes.float_attribute(attributes, column)
        if value is not None and value > 0:
            return value
    return None


def incident_size_in_acres(
    attributes: dict[str, object],
) -> float | None:
    """Return the incident's reported size for one row, in acres.

    The incident size is a human report that can outrun the mapped perimeter, so it is
    only used as a collapse reference with a much stricter threshold.

    Args:
        attributes: The row's attributes.

    Returns:
        The first positive incident size in acres, or None when the row reports none.
    """
    for column in INCIDENT_SIZE_COLUMNS:
        value = peri_scribe.history_attributes.float_attribute(attributes, column)
        if value is not None and value > 0:
            return value
    return None


def perimeter_is_implausibly_small(
    observation: SourceObservation,
    config: PerimeterSizeFilterConfig = DEFAULT_SIZE_FILTER_CONFIG,
) -> bool:
    """Return whether *observation*'s geometry collapsed below its reported size.

    The geometry is judged against the polygon's computed area and, more strictly,
    against the incident's reported size. Either reference can reveal a collapse: the
    computed area when the polygon alone shrank, and the incident size when the polygon
    and its computed area shrank together.

    Args:
        observation: The perimeter observation to judge.
        config: The size-filter thresholds.

    Returns:
        True when the geometry has area but is smaller than one of the configured
        fractions of the row's reported sizes.
    """
    geometry_acres = geometry_area_in_acres(observation.geometry)
    if geometry_acres is None:
        return False
    computed_acres = computed_area_in_acres(observation.attributes)
    incident_acres = incident_size_in_acres(observation.attributes)
    return (
        computed_acres is not None
        and geometry_acres < config.minimum_computed_area_fraction * computed_acres
    ) or (
        incident_acres is not None
        and geometry_acres < config.minimum_incident_area_fraction * incident_acres
    )


def drop_implausibly_small_perimeters(
    observations: list[SourceObservation],
    config: PerimeterSizeFilterConfig = DEFAULT_SIZE_FILTER_CONFIG,
) -> list[SourceObservation]:
    """Return *observations* without perimeters whose geometry collapsed.

    Args:
        observations: The reconciled perimeter versions for one fire.
        config: The size-filter thresholds.

    Returns:
        The observations whose geometry matches their reported size, in order.
    """
    return [
        observation
        for observation in observations
        if not perimeter_is_implausibly_small(observation, config)
    ]


def attributes_are_equal(
    left: dict[str, object],
    right: dict[str, object],
) -> bool:
    """Return whether two attribute dictionaries hold the same values.

    Args:
        left: One attribute dictionary.
        right: The other attribute dictionary.

    Returns:
        True when the dictionaries have the same keys and comparable values.
    """
    if set(left) != set(right):
        return False
    return all(
        peri_scribe.changes.normalized_attribute_value(left[key])
        == peri_scribe.changes.normalized_attribute_value(right[key])
        for key in left
    )


def point_versions(
    observations: list[SourceObservation],
) -> list[SourceObservation]:
    """Return one point version per distinct attribute state.

    The location is never part of version identity, so a location move alone folds the
    newest geometry into the current version instead of creating a new one.

    Args:
        observations: The incident location observations for one fire.

    Returns:
        One version per attribute change, in snapshot order.
    """
    ordered = sorted(observations, key=lambda observation: observation.serial_number)
    versions: list[SourceObservation] = []
    for observation in ordered:
        if versions and attributes_are_equal(
            versions[-1].attributes,
            observation.attributes,
        ):
            versions[-1] = dataclasses.replace(
                versions[-1],
                geometry=observation.geometry,
                snapshot_time=observation.snapshot_time,
                serial_number=observation.serial_number,
                object_id=observation.object_id,
                source_file=observation.source_file,
            )
        else:
            versions.append(observation)
    return versions
