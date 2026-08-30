"""Administrative boundary GeoPackages: fetching, computation, and upkeep."""

from __future__ import annotations

import datetime
import pathlib
import typing

import arcgis.features
import arcgis.gis
import geopandas
import shapely
import structlog

import peri_scribe.exceptions
import peri_scribe.models
import peri_scribe.output
import peri_scribe.sources.borders
import peri_scribe.sources.snapshots


logger = structlog.get_logger()


CALIFORNIA_LAYER_URL = (
    "https://services3.arcgis.com/0OPQIK59PJJqLK0A/ArcGIS/rest/services/"
    "California/FeatureServer/3"
)


NEIGHBOR_LAYER_URL = (
    "https://services.arcgis.com/P3ePLMYs2RVChkJx/arcgis/rest/services/"
    "USA_States_Generalized_Boundaries/FeatureServer/0"
)


BOUNDARY_OUTPUT_FILENAME = "CA_border_with_AZ_NV_and_OR.gpkg"


OUTPUT_LAYER_NAME = "CA_border_with_AZ_NV_and_OR"


def output_geopackage_path(year_directory: pathlib.Path) -> pathlib.Path:
    """Return the path of the administrative boundary GeoPackage.

    The boundary is a single derived file stored directly under the sources directory,
    named so it is not mistaken for a fire-source snapshot.

    Args:
        year_directory: The year directory that holds the ``sources`` directory.

    Returns:
        The path to the California border GeoPackage.
    """
    return (
        peri_scribe.sources.snapshots.sources_directory_path(year_directory)
        / BOUNDARY_OUTPUT_FILENAME
    )


def is_usable(path: pathlib.Path) -> bool:
    """Return whether *path* holds a usable California border GeoPackage.

    The file must exist, open as a GeoPackage, and contain the expected layer with the
    expected number of features, columns, non-empty geometry, and spatial reference, so
    a missing, stale, or truncated file is rebuilt instead of reused.

    Args:
        path: The GeoPackage path to inspect.

    Returns:
        True when the GeoPackage appears to be in good shape.
    """
    if not path.is_file():
        return False
    try:
        layer_names = list(geopandas.list_layers(path)["name"])
        if OUTPUT_LAYER_NAME not in layer_names:
            return False
        dataframe = geopandas.read_file(path, layer=OUTPUT_LAYER_NAME)
        columns = set(dataframe.columns) - {dataframe.geometry.name}
        usable = (
            len(dataframe) == peri_scribe.sources.borders.EXPECTED_FEATURE_COUNT
            and peri_scribe.sources.borders.EXPECTED_COLUMNS.issubset(columns)
            and not dataframe.geometry.isna().any()
            and not dataframe.geometry.is_empty.any()
            and dataframe.crs is not None
            and dataframe.crs.to_epsg() == peri_scribe.models.WGS84_SPATIAL_REFERENCE_ID
        )
    except (OSError, RuntimeError, ValueError) as error:
        logger.warning(
            "Administrative boundaries file is not usable",
            path=path,
            error=str(error),
        )
        return False
    return usable


def ensure_administrative_boundaries(
    year_directory: pathlib.Path | None = None,
) -> pathlib.Path:
    """Ensure the California border GeoPackage exists and is usable.

    When the GeoPackage is present and appears to be in good shape it is reused as is.
    Otherwise the border is rebuilt: California's polygon is fetched from the California
    service, the neighboring states' polygons are fetched from the same-source
    generalized states layer, the shared border portions are computed, and the result is
    written to ``sources/administrative_boundaries/`` under *year_directory*.

    Args:
        year_directory: The year directory that holds the ``sources`` directory.
            Defaults to the current year's data directory under the current working
            directory.

    Returns:
        The path to the California border GeoPackage.

    Raises:
        AdministrativeBoundariesError: If the boundary cannot be fetched or computed.
    """
    if year_directory is None:
        year_directory = peri_scribe.sources.snapshots.year_directory_path(
            pathlib.Path.cwd(),
            datetime.date.today().year,
        )
    output_path = output_geopackage_path(year_directory)
    if is_usable(output_path):
        logger.debug("Administrative boundaries already present", path=output_path)
        return output_path
    logger.debug("Building administrative boundaries", path=output_path)
    try:
        gis = arcgis.gis.GIS()
        california = peri_scribe.sources.borders.california_geometry(
            arcgis.features.FeatureLayer(CALIFORNIA_LAYER_URL, gis),
        )
        neighbors = peri_scribe.sources.borders.neighbor_geometries(
            arcgis.features.FeatureLayer(NEIGHBOR_LAYER_URL, gis),
        )
    except Exception as error:
        message = f"Failed to build administrative boundaries: {error}"
        raise peri_scribe.exceptions.AdministrativeBoundariesError(message) from error
    border = peri_scribe.sources.borders.border_dataframe(california, neighbors)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    peri_scribe.output.write_geopackage(
        output_path,
        [
            peri_scribe.models.LayerData(
                name=OUTPUT_LAYER_NAME,
                dataframe=border,
            ),
        ],
    )
    logger.debug(
        "Wrote administrative boundaries",
        path=output_path,
        features=len(border),
    )
    return output_path


def load_border_geometry(
    year_directory: pathlib.Path,
) -> shapely.Geometry:
    """Return the California border lines from the stored GeoPackage.

    The three neighbor borders are returned as a single MultiLineString (or a
    LineString when they collapse into one part), in WGS84.

    Args:
        year_directory: The year directory that holds the ``sources`` directory.

    Returns:
        The California border lines in WGS84.
    """
    path = output_geopackage_path(year_directory)
    dataframe = geopandas.read_file(path, layer=OUTPUT_LAYER_NAME)
    parts = [
        part
        for geometry in dataframe.geometry
        for part in peri_scribe.sources.borders.line_parts(
            typing.cast("shapely.Geometry", geometry),
        )
    ]
    if len(parts) == 1:
        return parts[0]
    return shapely.MultiLineString(parts)
