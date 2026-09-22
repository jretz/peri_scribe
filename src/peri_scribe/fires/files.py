"""Writing the fire history GeoPackage files."""

from __future__ import annotations

import contextlib
import dataclasses
import pathlib

import structlog

import peri_scribe.fires.classification
import peri_scribe.fires.history
import peri_scribe.fires.incident_history
import peri_scribe.fires.index
import peri_scribe.fires.reuse
import peri_scribe.fires.sources
import peri_scribe.geo.measurements
import peri_scribe.incidents
import peri_scribe.logging
import peri_scribe.phases
import peri_scribe.sources.snapshots
import spatial_data.layers


PERIMETER_LAYER_NAME = "perimeter_history"
logger = structlog.get_logger()


POINT_LAYER_NAME = "point_history"


HISTORY_OUTPUT_FILENAME = "history_of_full_geography.gpkg"


DERIVED_DIRECTORY_NAME = "derived"


PERIMETER_COLUMNS = [
    peri_scribe.fires.reuse.KEY_COLUMN,
    *peri_scribe.fires.history.IDENTITY_COLUMNS,
    "source",
    "source_subsource",
    "source_objectid",
    "source_globalid",
    "source_file",
    "source_serial",
    "superseded_sources",
    "observation_time",
    "created_time",
    "modified_time",
    "discovery_time",
    "area_acres",
    peri_scribe.geo.measurements.AREA_COLUMN,
    peri_scribe.geo.measurements.EXTERIOR_COLUMN,
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
    peri_scribe.fires.reuse.KEY_COLUMN,
    *peri_scribe.fires.history.IDENTITY_COLUMNS,
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


def history_geopackage_path(year_directory: pathlib.Path) -> pathlib.Path:
    """Return the path of the derived history GeoPackage for *year_directory*.

    Args:
        year_directory: The year directory that holds the ``sources`` directory.

    Returns:
        The output GeoPackage path.

    Examples:
        >>> history_geopackage_path(pathlib.Path("data/2025"))
        PosixPath('data/2025/derived/history_of_full_geography.gpkg')
    """
    return year_directory / DERIVED_DIRECTORY_NAME / HISTORY_OUTPUT_FILENAME


def write_history_of_full_geography(
    year_directory: pathlib.Path,
    *,
    unconditional: bool = False,
) -> pathlib.Path:
    """Build and write the full geography and incident history GeoPackage.

    The spatial layers are ``perimeter_history`` and ``point_history``; the separate
    ``incident_history`` layer preserves reports on their own observation dates.
    Validated geography rows for unchanged fires are retained; affected fires are
    reconciled in full so corrections can revise their history.

    Args:
        year_directory: The year directory that holds the ``sources`` directory.
        unconditional: Recompute every fire and refresh its source index.

    Returns:
        The path of the written GeoPackage.
    """
    sources_directory = peri_scribe.sources.snapshots.sources_directory_path(
        year_directory,
    )
    with peri_scribe.logging.log_phase(peri_scribe.phases.Phase.LOAD_AND_GROUP_SOURCES):
        read = peri_scribe.fires.sources.read_fire_sources(sources_directory)
        record_groups = peri_scribe.fires.sources.group_fire_sources(read)
    output_path = history_geopackage_path(year_directory)
    with (
        contextlib.nullcontext()
        if unconditional
        else peri_scribe.logging.log_phase(
            peri_scribe.phases.Phase.LOAD_REUSABLE_HISTORY,
        )
    ):
        cached = peri_scribe.fires.reuse.read_rows(
            output_path,
            (PERIMETER_LAYER_NAME, POINT_LAYER_NAME, peri_scribe.incidents.LAYER_NAME),
            unconditional=unconditional,
        )
    keys = peri_scribe.fires.reuse.fire_keys(
        read,
        record_groups,
        sources_directory,
        peri_scribe.fires.reuse.derivation_context(year_directory),
    )
    cached_perimeters = cached.get(PERIMETER_LAYER_NAME, {})
    cached_points = cached.get(POINT_LAYER_NAME, {})
    reused = {
        identifier: (cached_perimeters.get(key, []), cached_points.get(key, []))
        for identifier, key in keys.items()
        if key in cached_perimeters or key in cached_points
    }
    missing = [
        (fire, group)
        for fire, group in zip(record_groups.fires, record_groups.groups, strict=True)
        if id(fire) not in reused
    ]
    classifications = peri_scribe.fires.classification.classify_fire_sources(
        dataclasses.replace(
            record_groups,
            fires=tuple(fire for fire, _group in missing),
            groups=tuple(group for _fire, group in missing),
        ),
        year_directory,
    )
    if unconditional:
        peri_scribe.fires.index.write_fire_index(
            year_directory,
            record_groups,
            classifications,
        )
    with peri_scribe.logging.log_phase(peri_scribe.phases.Phase.RECONSTRUCT_GEOGRAPHY):
        perimeter_rows, point_rows = peri_scribe.fires.history.history_layer_rows(
            record_groups,
            classifications,
            list(read.rows),
            list(read.paths),
            sources_directory,
            reused=reused,
            derivation_keys=keys,
        )
    perimeter_dataframe = peri_scribe.fires.history.build_dataframe(
        perimeter_rows,
        PERIMETER_COLUMNS,
    )
    point_dataframe = peri_scribe.fires.history.build_dataframe(
        point_rows,
        POINT_COLUMNS,
    )
    logger.info("Full history reuse", reused=len(reused), recomputed=len(missing))
    peri_scribe.fires.reuse.write_layers(
        output_path,
        [
            spatial_data.layers.LayerData(
                name=PERIMETER_LAYER_NAME,
                dataframe=perimeter_dataframe,
            ),
            spatial_data.layers.LayerData(
                name=POINT_LAYER_NAME,
                dataframe=point_dataframe,
            ),
            spatial_data.layers.LayerData(
                name=peri_scribe.incidents.LAYER_NAME,
                dataframe=peri_scribe.fires.history.build_dataframe(
                    peri_scribe.fires.incident_history.incident_layer_rows(
                        read,
                        record_groups,
                        sources_directory,
                        reused={
                            identifier: cached[peri_scribe.incidents.LAYER_NAME][key]
                            for identifier, key in keys.items()
                            if key in cached.get(peri_scribe.incidents.LAYER_NAME, {})
                        },
                        derivation_keys=keys,
                    ),
                    peri_scribe.fires.incident_history.COLUMNS,
                ),
            ),
        ],
    )
    return output_path
