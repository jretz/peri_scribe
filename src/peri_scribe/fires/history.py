"""Building the full point and perimeter history for a year's fires.

The derived history is written to a GeoPackage with one layer for perimeters and one
for points. Perimeter history is reconciled across the two perimeter sources, where a
fire that appears in both keeps the source most likely to be correct at each moment
under the border-classification rules. Point history comes from the single incident
location source, so every distinct attribute state is kept while the location itself
never creates a version.
"""

from __future__ import annotations

import datetime
import json
import pathlib

import geopandas
import numpy as np
import pyproj

import peri_scribe.fires.sources
import peri_scribe.geo.package
import peri_scribe.geo.parsing
import peri_scribe.models
import peri_scribe.perimeters.cleaning
import peri_scribe.perimeters.history_attributes
import peri_scribe.perimeters.size_filtering
import peri_scribe.perimeters.versions


IDENTITY_COLUMNS = [
    "fire_name",
    "fire_identifier",
    "fire_aliases",
    "complex_name",
    "complex_identifier",
    "border_classification",
]


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
    if peri_scribe.geo.parsing.is_missing(value):
        return None
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): json_safe_value(item) for key, item in value.items()}
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
    observation: peri_scribe.perimeters.versions.SourceObservation,
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
            "source_subsource": (
                peri_scribe.perimeters.history_attributes.text_attribute(
                    attributes,
                    "source",
                    "poly_Source",
                )
            ),
            "source_objectid": observation.object_id,
            "source_globalid": (
                peri_scribe.perimeters.history_attributes.text_attribute(
                    attributes,
                    "GlobalID",
                )
            ),
            "source_file": observation.source_file,
            "source_serial": observation.serial_number,
            "observation_time": (
                peri_scribe.perimeters.versions.effective_time(
                    observation,
                )
            ),
            "created_time": (
                peri_scribe.perimeters.history_attributes.datetime_attribute(
                    attributes,
                    "CreationDate",
                    "poly_CreateDate",
                )
            ),
            "modified_time": (
                peri_scribe.perimeters.history_attributes.datetime_attribute(
                    attributes,
                    "EditDate",
                    "attr_ModifiedOnDateTime_dt",
                )
            ),
            "discovery_time": (
                peri_scribe.perimeters.history_attributes.datetime_attribute(
                    attributes,
                    "FireDiscoveryDate",
                    "attr_FireDiscoveryDateTime",
                )
            ),
            "area_acres": (
                peri_scribe.perimeters.history_attributes.float_attribute(
                    attributes,
                    "area_acres",
                    "poly_GISAcres",
                )
            ),
            "percent_contained": (
                peri_scribe.perimeters.history_attributes.float_attribute(
                    attributes,
                    "attr_PercentContained",
                )
            ),
            "containment_datetime": (
                peri_scribe.perimeters.history_attributes.datetime_attribute(
                    attributes,
                    "attr_ContainmentDateTime",
                )
            ),
            "estimated_cost_to_date": (
                peri_scribe.perimeters.history_attributes.float_attribute(
                    attributes,
                    "attr_EstimatedCostToDate",
                )
            ),
            "estimated_final_cost": (
                peri_scribe.perimeters.history_attributes.float_attribute(
                    attributes,
                    "attr_EstimatedFinalCost",
                )
            ),
            "type": peri_scribe.perimeters.history_attributes.text_attribute(
                attributes,
                "type",
            ),
            "feature_category": (
                peri_scribe.perimeters.history_attributes.text_attribute(
                    attributes,
                    "poly_FeatureCategory",
                )
            ),
            "map_method": (
                peri_scribe.perimeters.history_attributes.text_attribute(
                    attributes,
                    "poly_MapMethod",
                )
            ),
            "mission": (
                peri_scribe.perimeters.history_attributes.text_attribute(
                    attributes,
                    "mission",
                )
            ),
            "description": (
                peri_scribe.perimeters.history_attributes.text_attribute(
                    attributes,
                    "description",
                )
            ),
            "source_attributes": attributes_json(attributes),
            "geometry": (
                peri_scribe.perimeters.cleaning.clean_perimeter(
                    observation.geometry,
                )
            ),
        },
    )
    return row


def point_row(
    fire: peri_scribe.models.Fire,
    classification: peri_scribe.models.FireClassification | None,
    observation: peri_scribe.perimeters.versions.SourceObservation,
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
            "source_globalid": (
                peri_scribe.perimeters.history_attributes.text_attribute(
                    attributes,
                    "GlobalID",
                )
            ),
            "source_file": observation.source_file,
            "source_serial": observation.serial_number,
            # The incident record's modified time (the feed's observation column)
            # is the as-of date for the point's reported state; the snapshot time
            # is the fallback when the record carries no modified time.
            "observation_time": (
                observation.observation_time
                if observation.observation_time is not None
                else observation.snapshot_time
            ),
            "created_time": (
                peri_scribe.perimeters.history_attributes.datetime_attribute(
                    attributes,
                    "CreatedOnDateTime_dt",
                )
            ),
            "modified_time": (
                peri_scribe.perimeters.history_attributes.datetime_attribute(
                    attributes,
                    "ModifiedOnDateTime_dt",
                )
            ),
            "discovery_time": (
                peri_scribe.perimeters.history_attributes.datetime_attribute(
                    attributes,
                    "FireDiscoveryDateTime",
                )
            ),
            "incident_size": (
                peri_scribe.perimeters.history_attributes.float_attribute(
                    attributes,
                    "IncidentSize",
                )
            ),
            "discovery_acres": (
                peri_scribe.perimeters.history_attributes.float_attribute(
                    attributes,
                    "DiscoveryAcres",
                )
            ),
            "final_acres": (
                peri_scribe.perimeters.history_attributes.float_attribute(
                    attributes,
                    "FinalAcres",
                )
            ),
            "estimated_cost_to_date": (
                peri_scribe.perimeters.history_attributes.float_attribute(
                    attributes,
                    "EstimatedCostToDate",
                )
            ),
            "estimated_final_cost": (
                peri_scribe.perimeters.history_attributes.float_attribute(
                    attributes,
                    "EstimatedFinalCost",
                )
            ),
            "percent_contained": (
                peri_scribe.perimeters.history_attributes.float_attribute(
                    attributes,
                    "PercentContained",
                )
            ),
            "containment_datetime": (
                peri_scribe.perimeters.history_attributes.datetime_attribute(
                    attributes,
                    "ContainmentDateTime",
                )
            ),
            "control_datetime": (
                peri_scribe.perimeters.history_attributes.datetime_attribute(
                    attributes,
                    "ControlDateTime",
                )
            ),
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
        {column: row.get(column) for column in attribute_columns} for row in rows
    ]
    return geopandas.GeoDataFrame(
        attribute_rows,
        geometry=geometries,
        crs=pyproj.CRS.from_epsg(peri_scribe.models.WGS84_SPATIAL_REFERENCE_ID),
    )


def history_rows_for_fire(
    fire: peri_scribe.models.Fire,
    group: tuple[int, ...],
    full_rows: list[peri_scribe.geo.package.FireRowRecord],
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
        peri_scribe.perimeters.versions.source_observation_from_row(
            full_rows[index],
            full_paths[index],
            sources_directory,
        )
        for index in group
    ]
    firis_observations = [
        observation
        for observation in observations
        if observation.source_kind is peri_scribe.perimeters.versions.FIRIS_PERIMETER
    ]
    wfigs_observations = [
        observation
        for observation in observations
        if observation.source_kind is peri_scribe.perimeters.versions.WFIGS_PERIMETER
    ]
    point_observations = [
        observation
        for observation in observations
        if observation.source_kind is peri_scribe.perimeters.versions.WFIGS_LOCATION
    ]
    reconciled_perimeters = (
        peri_scribe.perimeters.versions.reconcile_perimeter_versions(
            peri_scribe.perimeters.versions.collapse_identical_consecutive_perimeters(
                firis_observations,
            ),
            peri_scribe.perimeters.versions.collapse_identical_consecutive_perimeters(
                wfigs_observations,
            ),
            classification,
        )
    )
    reconciled_perimeters = (
        peri_scribe.perimeters.size_filtering.drop_implausibly_small_perimeters(
            reconciled_perimeters,
        )
    )
    perimeter_rows = [
        perimeter_row(fire, classification, version)
        for version in reconciled_perimeters
    ]
    point_rows = [
        point_row(fire, classification, version)
        for version in peri_scribe.perimeters.versions.point_versions(
            point_observations,
        )
    ]
    return perimeter_rows, point_rows


def history_layer_rows(
    record_groups: peri_scribe.fires.sources.FireRecordGroups,
    classifications: dict[
        int,
        peri_scribe.models.FireClassification,
    ],
    full_rows: list[peri_scribe.geo.package.FireRowRecord],
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
        if peri_scribe.fires.sources.fire_is_complex_parent(record_groups, group):
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
