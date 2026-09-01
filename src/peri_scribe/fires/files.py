"""Writing the fire history GeoPackage files."""

from __future__ import annotations

import pathlib

import peri_scribe.fires.classification
import peri_scribe.fires.history
import peri_scribe.fires.sources
import peri_scribe.models
import peri_scribe.output
import peri_scribe.sources.snapshots


PERIMETER_LAYER_NAME = "perimeter_history"


POINT_LAYER_NAME = "point_history"


HISTORY_OUTPUT_FILENAME = "history_of_full_geography.gpkg"


DERIVED_DIRECTORY_NAME = "derived"


PERIMETER_COLUMNS = [
    *peri_scribe.fires.history.IDENTITY_COLUMNS,
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
) -> pathlib.Path:
    """Build and write the full point and perimeter history GeoPackage.

    The output holds two layers: ``perimeter_history`` and ``point_history``, both in
    the output spatial reference.

    Args:
        year_directory: The year directory that holds the ``sources`` directory.

    Returns:
        The path of the written GeoPackage.
    """
    sources_directory = peri_scribe.sources.snapshots.sources_directory_path(
        year_directory,
    )
    read = peri_scribe.fires.sources.read_fire_sources(sources_directory)
    record_groups = peri_scribe.fires.sources.group_fire_sources(read)
    classifications = peri_scribe.fires.classification.classify_fire_sources(
        record_groups,
        year_directory,
    )
    perimeter_rows, point_rows = peri_scribe.fires.history.history_layer_rows(
        record_groups,
        classifications,
        list(read.rows),
        list(read.paths),
        sources_directory,
    )
    perimeter_dataframe = peri_scribe.fires.history.build_dataframe(
        perimeter_rows,
        PERIMETER_COLUMNS,
    )
    point_dataframe = peri_scribe.fires.history.build_dataframe(
        point_rows,
        POINT_COLUMNS,
    )
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
