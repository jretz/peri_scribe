"""Building the full point and perimeter history for a year's fires.

The derived history is written to a GeoPackage with one layer for perimeters and one
for points. Perimeter history is reconciled across the two perimeter sources, where a
fire that appears in both keeps the source most likely to be correct at each moment
under the border-classification rules. Point history comes from the single incident
location source, so every distinct attribute state is kept while the location itself
never creates a version.
"""

from __future__ import annotations

import dataclasses
import datetime
import json
import pathlib
import typing

import geopandas
import numpy as np
import pyproj

import peri_scribe.california_border_classification
import peri_scribe.changes
import peri_scribe.classification
import peri_scribe.fire_sources
import peri_scribe.geo_data
import peri_scribe.models
import peri_scribe.output
import peri_scribe.snapshots


if typing.TYPE_CHECKING:
    import shapely


CONTEMPORANEOUS_TOLERANCE = datetime.timedelta(hours=4)

OUTPUT_SPATIAL_REFERENCE_ID = 4326

PERIMETER_LAYER_NAME = "perimeter_history"

POINT_LAYER_NAME = "point_history"

OUTPUT_FILENAME = "history_of_full_geography.gpkg"

DERIVED_DIRECTORY_NAME = "derived"

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

IDENTITY_COLUMNS = [
    "fire_name",
    "fire_identifier",
    "fire_aliases",
    "complex_name",
    "complex_identifier",
    "border_classification",
]

PERIMETER_COLUMNS = [
    *IDENTITY_COLUMNS,
    "source",
    "source_subsource",
    "source_objectid",
    "source_globalid",
    "source_file",
    "source_serial",
    "observation_time",
    "created_time",
    "modified_time",
    "discovery_time",
    "area_acres",
    "percent_contained",
    "containment_datetime",
    "estimated_cost_to_date",
    "estimated_final_cost",
    "type",
    "feature_category",
    "map_method",
    "mission",
    "description",
    "source_attributes",
    "geometry",
]

POINT_COLUMNS = [
    *IDENTITY_COLUMNS,
    "source",
    "source_objectid",
    "source_globalid",
    "source_file",
    "source_serial",
    "observation_time",
    "created_time",
    "modified_time",
    "discovery_time",
    "incident_size",
    "discovery_acres",
    "final_acres",
    "estimated_cost_to_date",
    "estimated_final_cost",
    "percent_contained",
    "containment_datetime",
    "control_datetime",
    "source_attributes",
    "geometry",
]


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


def watermark_time_from(path: pathlib.Path) -> datetime.datetime | None:
    """Return the snapshot watermark time encoded in *path*, or None.

    Args:
        path: A GeoPackage snapshot path.

    Returns:
        The watermark time as a UTC datetime, or None when it cannot be read.
    """
    try:
        _serial_number, watermark = peri_scribe.snapshots.parse_geopackage_filename(
            path,
        )
    except ValueError:
        return None
    prefix = "lastEdit="
    if not watermark.startswith(prefix):
        return None
    try:
        epoch_milliseconds = int(watermark[len(prefix) :])
    except ValueError:
        return None
    return datetime.datetime.fromtimestamp(
        epoch_milliseconds / 1000.0,
        tz=datetime.UTC,
    )


def source_observation_from_row(
    row: peri_scribe.geo_data.FireRowRecord,
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
        snapshot_time=watermark_time_from(path),
        serial_number=(
            peri_scribe.california_border_classification.snapshot_serial_number(path)
        ),
        object_id=row.object_id,
        source_file=str(path.relative_to(sources_directory)),
        attributes=row.attributes,
    )


def effective_time(
    observation: SourceObservation,
) -> datetime.datetime | None:
    """Return the observation's mapping time, falling back to its snapshot time.

    Args:
        observation: The observation to time.

    Returns:
        The mapping time when present, otherwise the snapshot time.
    """
    if observation.observation_time is not None:
        return observation.observation_time
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
    resolved = (
        time
        if time is not None
        else datetime.datetime.min.replace(tzinfo=datetime.UTC)
    )
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
    if left is None or right is None:
        return left is None and right is None
    if left.is_empty or right.is_empty:
        return left.is_empty and right.is_empty
    return left.wkb == right.wkb


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


def attribute_value(
    attributes: dict[str, object],
    *column_names: str,
) -> object | None:
    """Return the first present value among *column_names*, or None.

    Args:
        attributes: The row's attributes.
        column_names: The column names to look up, in priority order.

    Returns:
        The first non-missing value, or None.
    """
    for column_name in column_names:
        if column_name in attributes:
            value = attributes[column_name]
            if not peri_scribe.geo_data.is_missing(value):
                return value
    return None


def text_attribute(
    attributes: dict[str, object],
    *column_names: str,
) -> str | None:
    """Return the first present text value among *column_names*, or None.

    Args:
        attributes: The row's attributes.
        column_names: The column names to look up, in priority order.

    Returns:
        The first non-blank text value, or None.
    """
    value = attribute_value(attributes, *column_names)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def float_attribute(
    attributes: dict[str, object],
    *column_names: str,
) -> float | None:
    """Return the first present numeric value among *column_names*, or None.

    Args:
        attributes: The row's attributes.
        column_names: The column names to look up, in priority order.

    Returns:
        The first numeric value as a float, or None.
    """
    value = attribute_value(attributes, *column_names)
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def datetime_attribute(
    attributes: dict[str, object],
    *column_names: str,
) -> datetime.datetime | None:
    """Return the first present datetime value among *column_names*, or None.

    Args:
        attributes: The row's attributes.
        column_names: The column names to look up, in priority order.

    Returns:
        The first datetime value, or None.
    """
    return peri_scribe.changes.modified_datetime_from(
        attribute_value(attributes, *column_names),
    )


def classification_text(
    classification: peri_scribe.models.FireClassification | None,
) -> str | None:
    """Return the classification's string value, or None.

    Args:
        classification: The fire's classification, or None.

    Returns:
        The classification value, or None.
    """
    if classification is None:
        return None
    return classification.classification.value


def json_safe_value(value: object) -> object:
    """Return *value* in a JSON-serializable form.

    Args:
        value: Any attribute value.

    Returns:
        The value converted to JSON-native types where possible.
    """
    if peri_scribe.geo_data.is_missing(value):
        return None
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, dict):
        return {
            str(key): json_safe_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [json_safe_value(item) for item in value]
    if isinstance(value, np.generic):
        return json_safe_value(value.item())
    return value


def attributes_json(attributes: dict[str, object]) -> str:
    """Return the row's attributes serialized as JSON.

    Args:
        attributes: The row's attributes.

    Returns:
        The attributes as a compact JSON string.
    """
    return json.dumps(
        {str(key): json_safe_value(value) for key, value in attributes.items()},
        sort_keys=True,
        default=str,
    )


def identity_fields(
    fire: peri_scribe.models.Fire,
    classification: peri_scribe.models.FireClassification | None,
) -> dict[str, object]:
    """Return the shared identity fields for *fire*.

    Args:
        fire: The fire to describe.
        classification: The fire's classification, or None.

    Returns:
        The fire's identity fields.
    """
    complex_ = fire.complex
    return {
        "fire_name": fire.name,
        "fire_identifier": fire.identifier,
        "fire_aliases": ", ".join(sorted(fire.aliases)),
        "complex_name": complex_.name if complex_ is not None else None,
        "complex_identifier": complex_.identifier if complex_ is not None else None,
        "border_classification": classification_text(classification),
    }


def perimeter_row(
    fire: peri_scribe.models.Fire,
    classification: peri_scribe.models.FireClassification | None,
    observation: SourceObservation,
) -> dict[str, object]:
    """Return one perimeter history row for *observation*.

    Args:
        fire: The fire the version belongs to.
        classification: The fire's classification, or None.
        observation: The reconciled perimeter version.

    Returns:
        The row's fields, including its geometry.
    """
    attributes = observation.attributes
    row = identity_fields(fire, classification)
    row.update(
        {
            "source": observation.source_kind.value,
            "source_subsource": text_attribute(attributes, "source", "poly_Source"),
            "source_objectid": observation.object_id,
            "source_globalid": text_attribute(attributes, "GlobalID"),
            "source_file": observation.source_file,
            "source_serial": observation.serial_number,
            "observation_time": observation.observation_time,
            "created_time": datetime_attribute(
                attributes,
                "CreationDate",
                "poly_CreateDate",
            ),
            "modified_time": datetime_attribute(
                attributes,
                "EditDate",
                "attr_ModifiedOnDateTime_dt",
            ),
            "discovery_time": datetime_attribute(
                attributes,
                "FireDiscoveryDate",
                "attr_FireDiscoveryDateTime",
            ),
            "area_acres": float_attribute(attributes, "area_acres", "poly_GISAcres"),
            "percent_contained": float_attribute(attributes, "attr_PercentContained"),
            "containment_datetime": datetime_attribute(
                attributes,
                "attr_ContainmentDateTime",
            ),
            "estimated_cost_to_date": float_attribute(
                attributes,
                "attr_EstimatedCostToDate",
            ),
            "estimated_final_cost": float_attribute(
                attributes,
                "attr_EstimatedFinalCost",
            ),
            "type": text_attribute(attributes, "type"),
            "feature_category": text_attribute(attributes, "poly_FeatureCategory"),
            "map_method": text_attribute(attributes, "poly_MapMethod"),
            "mission": text_attribute(attributes, "mission"),
            "description": text_attribute(attributes, "description"),
            "source_attributes": attributes_json(attributes),
            "geometry": observation.geometry,
        },
    )
    return row


def point_row(
    fire: peri_scribe.models.Fire,
    classification: peri_scribe.models.FireClassification | None,
    observation: SourceObservation,
) -> dict[str, object]:
    """Return one point history row for *observation*.

    Args:
        fire: The fire the version belongs to.
        classification: The fire's classification, or None.
        observation: The point version.

    Returns:
        The row's fields, including its geometry.
    """
    attributes = observation.attributes
    row = identity_fields(fire, classification)
    row.update(
        {
            "source": observation.source_kind.value,
            "source_objectid": observation.object_id,
            "source_globalid": text_attribute(attributes, "GlobalID"),
            "source_file": observation.source_file,
            "source_serial": observation.serial_number,
            "observation_time": observation.snapshot_time,
            "created_time": datetime_attribute(attributes, "CreatedOnDateTime_dt"),
            "modified_time": datetime_attribute(attributes, "ModifiedOnDateTime_dt"),
            "discovery_time": datetime_attribute(attributes, "FireDiscoveryDateTime"),
            "incident_size": float_attribute(attributes, "IncidentSize"),
            "discovery_acres": float_attribute(attributes, "DiscoveryAcres"),
            "final_acres": float_attribute(attributes, "FinalAcres"),
            "estimated_cost_to_date": float_attribute(
                attributes,
                "EstimatedCostToDate",
            ),
            "estimated_final_cost": float_attribute(
                attributes,
                "EstimatedFinalCost",
            ),
            "percent_contained": float_attribute(attributes, "PercentContained"),
            "containment_datetime": datetime_attribute(
                attributes,
                "ContainmentDateTime",
            ),
            "control_datetime": datetime_attribute(attributes, "ControlDateTime"),
            "source_attributes": attributes_json(attributes),
            "geometry": observation.geometry,
        },
    )
    return row


def build_dataframe(
    rows: list[dict[str, object]],
    columns: list[str],
) -> geopandas.GeoDataFrame:
    """Build a GeoDataFrame from history rows.

    Args:
        rows: The history rows, each including a geometry.
        columns: The column names in output order.

    Returns:
        The rows as a GeoDataFrame in the output spatial reference.
    """
    geometries = [row["geometry"] for row in rows]
    attribute_columns = [column for column in columns if column != "geometry"]
    attribute_rows = [
        {column: row.get(column) for column in attribute_columns}
        for row in rows
    ]
    return geopandas.GeoDataFrame(
        attribute_rows,
        geometry=geometries,
        crs=pyproj.CRS.from_epsg(OUTPUT_SPATIAL_REFERENCE_ID),
    )


def read_full_rows(
    sources_directory: pathlib.Path,
) -> tuple[
    list[peri_scribe.geo_data.FireRowRecord],
    list[pathlib.Path],
]:
    """Read every fire row under *sources_directory* with its source path.

    Rows are read in the same file and row order used by the fire grouping, so the
    returned rows align with `fire_sources.fire_record_groups` records by index.

    Args:
        sources_directory: The directory tree holding the source GeoPackages.

    Returns:
        The full rows and their source paths, aligned by index.
    """
    rows: list[peri_scribe.geo_data.FireRowRecord] = []
    paths: list[pathlib.Path] = []
    for path in peri_scribe.snapshots.geo_package_files(sources_directory):
        file_rows = list(peri_scribe.geo_data.fire_row_records(path))
        rows.extend(file_rows)
        paths.extend([path] * len(file_rows))
    return rows, paths


def history_rows_for_fire(
    fire: peri_scribe.models.Fire,
    group: tuple[int, ...],
    full_rows: list[peri_scribe.geo_data.FireRowRecord],
    full_paths: list[pathlib.Path],
    *,
    sources_directory: pathlib.Path,
    classification: peri_scribe.models.FireClassification | None,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Return the perimeter and point history rows for one fire.

    Args:
        fire: The fire to build history for.
        group: The indices of the fire's rows within *full_rows*.
        full_rows: Every fire row, aligned with *full_paths*.
        full_paths: The source path of each full row.
        sources_directory: The directory the source paths are relative to.
        classification: The fire's classification, or None.

    Returns:
        The perimeter rows and point rows for the fire.
    """
    observations = [
        source_observation_from_row(
            full_rows[index],
            full_paths[index],
            sources_directory,
        )
        for index in group
    ]
    firis_observations = [
        observation
        for observation in observations
        if observation.source_kind is FIRIS_PERIMETER
    ]
    wfigs_observations = [
        observation
        for observation in observations
        if observation.source_kind is WFIGS_PERIMETER
    ]
    point_observations = [
        observation
        for observation in observations
        if observation.source_kind is WFIGS_LOCATION
    ]
    perimeter_versions = reconcile_perimeter_versions(
        collapse_identical_consecutive_perimeters(firis_observations),
        collapse_identical_consecutive_perimeters(wfigs_observations),
        classification,
    )
    perimeter_rows = [
        perimeter_row(fire, classification, version)
        for version in perimeter_versions
    ]
    point_rows = [
        point_row(fire, classification, version)
        for version in point_versions(point_observations)
    ]
    return perimeter_rows, point_rows


def history_layer_rows(
    record_groups: peri_scribe.fire_sources.FireRecordGroups,
    classifications: dict[
        int,
        peri_scribe.models.FireClassification,
    ],
    full_rows: list[peri_scribe.geo_data.FireRowRecord],
    full_paths: list[pathlib.Path],
    sources_directory: pathlib.Path,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Return the perimeter and point history rows for every non-complex fire.

    Args:
        record_groups: The grouped fire records.
        classifications: Each fire's classification, keyed by fire identity.
        full_rows: Every fire row, aligned with *full_paths*.
        full_paths: The source path of each full row.
        sources_directory: The directory the source paths are relative to.

    Returns:
        All perimeter rows and all point rows.
    """
    perimeter_rows: list[dict[str, object]] = []
    point_rows: list[dict[str, object]] = []
    for fire, group in zip(
        record_groups.fires,
        record_groups.groups,
        strict=True,
    ):
        if peri_scribe.fire_sources.fire_is_complex_parent(record_groups, group):
            continue
        fire_perimeter_rows, fire_point_rows = history_rows_for_fire(
            fire,
            group,
            full_rows,
            full_paths,
            sources_directory=sources_directory,
            classification=classifications.get(id(fire)),
        )
        perimeter_rows.extend(fire_perimeter_rows)
        point_rows.extend(fire_point_rows)
    return perimeter_rows, point_rows


def history_geopackage_path(year_directory: pathlib.Path) -> pathlib.Path:
    """Return the path of the derived history GeoPackage for *year_directory*.

    Args:
        year_directory: The year directory that holds the ``sources`` directory.

    Returns:
        The output GeoPackage path.
    """
    return year_directory / DERIVED_DIRECTORY_NAME / OUTPUT_FILENAME


def write_history_of_full_geography(
    year_directory: pathlib.Path,
) -> pathlib.Path:
    """Build and write the full point and perimeter history GeoPackage.

    The output holds two layers: `perimeter_history` and `point_history`, both in the
    output spatial reference.

    Args:
        year_directory: The year directory that holds the ``sources`` directory.

    Returns:
        The path of the written GeoPackage.
    """
    sources_directory = peri_scribe.snapshots.sources_directory_path(year_directory)
    record_groups = peri_scribe.fire_sources.fire_record_groups(sources_directory)
    classifications = peri_scribe.classification.classify_fire_sources(
        record_groups,
        year_directory.parent.parent,
    )
    full_rows, full_paths = read_full_rows(sources_directory)
    perimeter_rows, point_rows = history_layer_rows(
        record_groups,
        classifications,
        full_rows,
        full_paths,
        sources_directory,
    )
    perimeter_dataframe = build_dataframe(perimeter_rows, PERIMETER_COLUMNS)
    point_dataframe = build_dataframe(point_rows, POINT_COLUMNS)
    output_path = history_geopackage_path(year_directory)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    peri_scribe.output.write_geopackage(
        output_path,
        [
            peri_scribe.models.LayerData(
                name=PERIMETER_LAYER_NAME,
                dataframe=perimeter_dataframe,
            ),
            peri_scribe.models.LayerData(
                name=POINT_LAYER_NAME,
                dataframe=point_dataframe,
            ),
        ],
    )
    return output_path
