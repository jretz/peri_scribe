"""Writing the fire history GeoPackage files."""

from __future__ import annotations

import collections.abc
import contextlib
import dataclasses
import pathlib

import structlog

import peri_scribe.fires.classification
import peri_scribe.fires.generation
import peri_scribe.fires.history
import peri_scribe.fires.incident_history
import peri_scribe.fires.index
import peri_scribe.fires.reuse
import peri_scribe.fires.sources
import peri_scribe.geo.measurements
import peri_scribe.incidents
import peri_scribe.logging
import peri_scribe.phases
import peri_scribe.preparation
import peri_scribe.sources.snapshots
import spatial_data.layers


PERIMETER_LAYER_NAME = "perimeter_history"
logger = structlog.get_logger()


POINT_LAYER_NAME = "point_history"


HISTORY_OUTPUT_FILENAME = "history_of_full_geography.gpkg"


DERIVED_DIRECTORY_NAME = "derived"
FULL_LAYER_NAMES = (
    PERIMETER_LAYER_NAME,
    POINT_LAYER_NAME,
    peri_scribe.incidents.LAYER_NAME,
)


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


@peri_scribe.preparation.cached_year
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
    unconditional = peri_scribe.preparation.unconditional_rebuild(
        requested=unconditional,
    )
    output_path = history_geopackage_path(year_directory)
    generation = peri_scribe.fires.generation.source_key(year_directory)
    if not unconditional and peri_scribe.fires.reuse.generation_matches(
        output_path,
        generation,
        FULL_LAYER_NAMES,
    ):
        logger.info("Full geography unchanged", path=str(output_path))
        return output_path
    with peri_scribe.logging.log_phase(peri_scribe.phases.Phase.LOAD_AND_GROUP_SOURCES):
        prepared = peri_scribe.fires.sources.prepare_fire_sources(
            peri_scribe.sources.snapshots.sources_directory_path(year_directory),
        )
    return write_prepared_full_geography(
        year_directory,
        prepared,
        generation=generation,
        unconditional=unconditional,
    )


def write_prepared_full_geography(
    year_directory: pathlib.Path,
    prepared: peri_scribe.fires.sources.PreparedSources,
    *,
    generation: str,
    unconditional: bool = False,
) -> pathlib.Path:
    """Reconstruct affected fires while retaining authenticated histories for others.

    Args:
        year_directory: The year whose full geography should be published.
        prepared: Complete source evidence and grouped fire identities.
        generation: Exact source snapshot and dependency identity.
        unconditional: Whether every fire must be rebuilt regardless of cached rows.

    Returns:
        The complete published full-history GeoPackage path.
    """
    sources_directory = peri_scribe.sources.snapshots.sources_directory_path(
        year_directory,
    )
    record_groups = prepared.groups
    output_path = history_geopackage_path(year_directory)
    keys = peri_scribe.fires.reuse.shared_fire_keys(
        prepared.read,
        record_groups,
        sources_directory,
        peri_scribe.fires.reuse.derivation_context(year_directory),
    )
    with (
        contextlib.nullcontext()
        if unconditional
        else peri_scribe.logging.log_phase(
            peri_scribe.phases.Phase.LOAD_REUSABLE_HISTORY,
        )
    ):
        cached = peri_scribe.fires.reuse.read_rows(
            output_path,
            FULL_LAYER_NAMES,
            unconditional=unconditional,
            keys=frozenset(keys.values()),
        )
    cached_perimeters = cached.get(PERIMETER_LAYER_NAME, {})
    cached_points = cached.get(POINT_LAYER_NAME, {})
    reused = {
        identifier: (cached_perimeters.get(key, []), cached_points.get(key, []))
        for identifier, key in keys.items()
        if key in cached_perimeters or key in cached_points
    }
    previously_classified = classified_reused_fires(output_path, reused.keys())
    missing = [
        (fire, group)
        for fire, group in zip(record_groups.fires, record_groups.groups, strict=True)
        if id(fire) not in previously_classified
    ]
    classifications = prepared.classifications
    if classifications is None:
        classifications = peri_scribe.fires.classification.classify_fire_sources(
            dataclasses.replace(
                record_groups,
                fires=tuple(fire for fire, _group in missing),
                groups=tuple(group for _fire, group in missing),
            ),
            year_directory,
        )
    reused = {
        identifier: rows
        for identifier, rows in reused.items()
        if identifier in previously_classified or identifier not in classifications
    }
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
            list(prepared.read.rows),
            list(prepared.read.paths),
            sources_directory,
            reused=reused,
            derivation_keys=keys,
        )
    logger.info(
        "Full history reuse",
        reused=len(reused),
        recomputed=len(keys) - len(reused),
    )
    peri_scribe.fires.reuse.write_layers(
        output_path,
        [
            spatial_data.layers.LayerData(
                name=PERIMETER_LAYER_NAME,
                dataframe=peri_scribe.fires.history.build_dataframe(
                    perimeter_rows,
                    PERIMETER_COLUMNS,
                ),
            ),
            spatial_data.layers.LayerData(
                name=POINT_LAYER_NAME,
                dataframe=peri_scribe.fires.history.build_dataframe(
                    point_rows,
                    POINT_COLUMNS,
                ),
            ),
            spatial_data.layers.LayerData(
                name=peri_scribe.incidents.LAYER_NAME,
                dataframe=peri_scribe.fires.history.build_dataframe(
                    peri_scribe.fires.incident_history.incident_layer_rows(
                        prepared.read,
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
        generation=generation
        if peri_scribe.fires.generation.classifications_complete(
            record_groups,
            previously_classified | classifications.keys(),
        )
        else None,
    )
    return output_path


def classified_reused_fires(
    path: pathlib.Path,
    reused: collections.abc.Collection[int],
) -> frozenset[int]:
    """Carry forward classification proof only from authenticated complete histories.

    A complete generation tag proves that all its non-complex fires were classified.
    Matching per-fire derivation keys keep that proof valid for the reused histories.

    Args:
        path: The previous full-history output whose rows are being reused.
        reused: Current fire identities matched to authenticated prior derivation keys.

    Returns:
        Reused identities known to have completed classification.
    """
    if not reused:
        return frozenset()
    signature = peri_scribe.fires.reuse.validated_signature(path, FULL_LAYER_NAMES)
    return (
        frozenset(reused)
        if signature is not None and signature.generation is not None
        else frozenset()
    )
