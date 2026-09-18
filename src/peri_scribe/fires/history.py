"""Building the full point and perimeter history for a year's fires.

The derived history is written to a GeoPackage with one layer for perimeters and one for
points. Perimeter history is reconciled across the two perimeter sources, where a fire
that appears in both keeps the source most likely to be correct at each moment under the
border-classification rules. Point history comes from the single incident location
source, so every distinct attribute state is kept while the location itself never
creates a version.
"""

from __future__ import annotations

import concurrent.futures
import functools
import itertools
import json
import os
import pathlib

import geopandas

import peri_scribe.fires.reuse
import peri_scribe.fires.sources
import peri_scribe.geo.measurements
import peri_scribe.geo.package
import peri_scribe.geo.parsing
import peri_scribe.geo.spatial_reference
import peri_scribe.models
import peri_scribe.perimeters.cleaning
import peri_scribe.perimeters.history_attributes
import peri_scribe.perimeters.size_filtering
import peri_scribe.perimeters.versions
import peri_scribe.units


IDENTITY_COLUMNS = [
    "fire_name",
    "fire_identifier",
    "fire_aliases",
    "complex_name",
    "complex_identifier",
    "border_classification",
]

# The per-fire work mixes geometry calls that release the GIL with Python-side attribute
# and dictionary work that does not, so more than a handful of workers only adds GIL
# contention, so cap the pool size.
HISTORY_ROW_WORKER_COUNT = min(4, os.cpu_count() or 1)


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


def attributes_json(attributes: dict[str, object]) -> str:
    """Return the row's attributes serialized as JSON.

    Args:
        attributes: The row's attributes.

    Returns:
        The attributes as a compact JSON string.

    Examples:
        >>> attributes_json({"fire_name": "Example", "acres": 12})
        '{"acres": 12, "fire_name": "Example"}'
    """
    return json.dumps(
        {
            str(key): peri_scribe.geo.parsing.json_native_value(value)
            for key, value in attributes.items()
        },
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
    geometry = peri_scribe.perimeters.cleaning.clean_perimeter(observation.geometry)
    row = identity_fields(fire, classification)
    row.update({
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
        "superseded_sources": json.dumps(observation.superseded_sources),
        "observation_time": (
            peri_scribe.perimeters.versions.effective_time(observation)
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
        "geometry": geometry,
    })
    if geometry is not None:
        row[peri_scribe.geo.measurements.AREA_COLUMN] = peri_scribe.units.area(
            geometry,
        ).m_as("meters ** 2")
        exterior = peri_scribe.units.exterior_perimeter(geometry)
        row[peri_scribe.geo.measurements.EXTERIOR_COLUMN] = (
            None if exterior is None else exterior.m_as("meters")
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
    row.update({
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
        # The incident record's modified time (the feed's observation column) is the
        # as-of date for the point's reported state; the snapshot time is the fallback
        # when the record carries no modified time.
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
    })
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
        crs=peri_scribe.geo.spatial_reference.WGS84_SPATIAL_REFERENCE,
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
    classifications: dict[int, peri_scribe.models.FireClassification],
    full_rows: list[peri_scribe.geo.package.FireRowRecord],
    full_paths: list[pathlib.Path],
    sources_directory: pathlib.Path,
    *,
    reused: dict[int, tuple[list[dict[str, object]], list[dict[str, object]]]]
    | None = None,
    derivation_keys: dict[int, str] | None = None,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Return the perimeter and point history rows for every non-complex fire.

    Each fire's rows are derived from only that fire's records, and the cleaning and
    geodesic area work releases the GIL, so the fires are built in parallel and their
    rows are collected in fire order alongside validated rows from unchanged fires.

    Args:
        record_groups: The grouped fire records.
        classifications: Each fire's classification, keyed by fire identity.
        full_rows: Every fire row, aligned with *full_paths*.
        full_paths: The source path of each full row.
        sources_directory: The directory the source paths are relative to.
        reused: Validated full histories keyed by in-memory fire identity.
        derivation_keys: Input fingerprints to retain with each fire's output rows.

    Returns:
        All perimeter rows and all point rows.
    """
    non_complex_fires = [
        (fire, group)
        for fire, group in zip(record_groups.fires, record_groups.groups, strict=True)
        if not peri_scribe.fires.sources.fire_is_complex_parent(record_groups, group)
    ]
    if not non_complex_fires:
        return [], []
    reused = {} if reused is None else reused
    perimeter_rows: list[dict[str, object]] = []
    point_rows: list[dict[str, object]] = []
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=HISTORY_ROW_WORKER_COUNT,
    ) as executor:
        results = executor.map(
            functools.partial(
                grouped_history_rows,
                full_rows=full_rows,
                full_paths=full_paths,
                sources_directory=sources_directory,
                classifications=classifications,
                reused=reused,
            ),
            non_complex_fires,
            buffersize=2 * HISTORY_ROW_WORKER_COUNT,
        )
        for (fire, _group), (fire_perimeter_rows, fire_point_rows) in zip(
            non_complex_fires,
            results,
            strict=True,
        ):
            if derivation_keys is not None:
                for row in itertools.chain(fire_perimeter_rows, fire_point_rows):
                    row[peri_scribe.fires.reuse.KEY_COLUMN] = derivation_keys[id(fire)]
            perimeter_rows.extend(fire_perimeter_rows)
            point_rows.extend(fire_point_rows)
    return perimeter_rows, point_rows


def grouped_history_rows(
    grouped_fire: tuple[peri_scribe.models.Fire, tuple[int, ...]],
    *,
    full_rows: list[peri_scribe.geo.package.FireRowRecord],
    full_paths: list[pathlib.Path],
    sources_directory: pathlib.Path,
    classifications: dict[int, peri_scribe.models.FireClassification],
    reused: dict[int, tuple[list[dict[str, object]], list[dict[str, object]]]],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Reuse complete histories without retaining every outstanding future.

    Args:
        grouped_fire: One fire and its source-record positions.
        full_rows: All source observations.
        full_paths: Source paths aligned with the observations.
        sources_directory: Root for relative source paths.
        classifications: Each fire's classification by identity.
        reused: Validated histories by fire identity.

    Returns:
        The fire's perimeter and point rows.
    """
    fire, group = grouped_fire
    if id(fire) in reused:
        return reused[id(fire)]
    return history_rows_for_fire(
        fire,
        group,
        full_rows,
        full_paths,
        sources_directory=sources_directory,
        classification=classifications.get(id(fire)),
    )
