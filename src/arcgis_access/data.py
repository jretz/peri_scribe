"""Constructing GeoDataFrames from ArcGIS FeatureSet query results.

Converts ArcGIS FeatureSet query results into GeoDataFrames in the layer's native
spatial reference and provides retry-aware querying for ArcGIS feature layers.
"""

from __future__ import annotations

import typing

import geopandas
import structlog

import arcgis_access.exceptions
import arcgis_access.retry
import arcgis_access.spatial_reference
import spatial_data.reference


if typing.TYPE_CHECKING:
    import arcgis.features
    import pandas as pd
    import shapely


logger = structlog.get_logger()


SHAPE_COLUMN_NAME = "SHAPE"
GEOMETRY_COLUMN_NAME = "geom"


def extract_geometries(
    dataframe: pd.DataFrame,
) -> tuple[pd.DataFrame, list[shapely.Geometry | None], str | None]:
    """Separate a feature dataframe's SHAPE column from its attributes.

    Args:
        dataframe: The feature dataframe whose SHAPE column holds the geometries.

    Returns:
        The dataframe with the SHAPE column removed, the shapely geometries of its
        features (None where a feature has no geometry), and a warning to report when
        the dataframe has no geometry column.
    """
    if SHAPE_COLUMN_NAME not in dataframe.columns:
        return (
            dataframe,
            [None] * len(dataframe),
            (
                "  warning: all features lack geometry; "
                "writing the layer with NULL geometry"
            ),
        )
    return (
        dataframe.drop(columns=[SHAPE_COLUMN_NAME]),
        list(dataframe[SHAPE_COLUMN_NAME].geom.as_shapely),
        None,
    )


def geo_data_frame_from(
    dataframe: pd.DataFrame,
    shapely_geometries: list[shapely.Geometry | None],
    spatial_reference_id: int,
    *,
    geometry_column: str = GEOMETRY_COLUMN_NAME,
) -> geopandas.GeoDataFrame:
    """Build the output GeoDataFrame with the requested geometry-column name.

    Args:
        dataframe: The feature attributes.
        shapely_geometries: The geometry for each feature, aligned with the rows.
        spatial_reference_id: The EPSG id of the output spatial reference.
        geometry_column: The output geometry-column name.

    Returns:
        The GeoDataFrame with the requested geometry-column name.
    """
    geo_data_frame = geopandas.GeoDataFrame(
        dataframe,
        geometry=shapely_geometries,
        crs=spatial_data.reference.spatial_reference_for_id(
            spatial_reference_id,
        ),
    )
    if geo_data_frame.geometry.name == geometry_column:
        return geo_data_frame
    return typing.cast(
        "geopandas.GeoDataFrame",
        geo_data_frame.rename_geometry(geometry_column),
    )


def wgs84_query_parameters(where: str) -> dict[str, typing.Any]:
    """Return the standard query parameters for a layer stored in WGS 84.

    The query asks for WGS 84 so every stored layer shares one spatial reference.
    Ordering by the object id sends the ArcGIS client's paging down a single-threaded
    path: its concurrent paging races on the shared SSL context and, although the
    connection is verified, reports it unverified, spamming a misleading
    InsecureRequestWarning per page.

    Args:
        where: The SQL where clause selecting the features.

    Returns:
        The keyword arguments to pass to :func:`query_with_retry`.
    """
    return {
        "where": where,
        "out_sr": spatial_data.reference.WGS84_SPATIAL_REFERENCE_ID,
        "order_by_fields": "OBJECTID",
    }


def geo_data_frame_from_feature_set(
    feature_set: arcgis.features.FeatureSet,
    *,
    geometry_column: str = GEOMETRY_COLUMN_NAME,
) -> geopandas.GeoDataFrame:
    """Return a WGS 84 query result's features as a GeoDataFrame.

    A result whose features carry no geometry is returned with null geometry after
    logging why. Empty results retain a geometry column and CRS so they can be stored
    as spatial layers without relying on the client's empty attribute conversion.

    Args:
        feature_set: The WGS 84 query result to convert.
        geometry_column: The output geometry-column name.

    Returns:
        The features as a GeoDataFrame in WGS 84.
    """
    if not feature_set.features:
        return geopandas.GeoDataFrame(
            {geometry_column: []},
            geometry=geometry_column,
            crs=spatial_data.reference.spatial_reference_for_id(
                spatial_data.reference.WGS84_SPATIAL_REFERENCE_ID,
            ),
        )
    dataframe, shapely_geometries, geometry_warning = extract_geometries(
        feature_set.sdf,
    )
    if geometry_warning is not None:
        logger.warning(geometry_warning)
    return geo_data_frame_from(
        dataframe,
        shapely_geometries,
        spatial_data.reference.WGS84_SPATIAL_REFERENCE_ID,
        geometry_column=geometry_column,
    )


def dataframe_for_layer(
    feed_name: str,
    layer: arcgis.features.FeatureLayer,
    feature_set: arcgis.features.FeatureSet,
    *,
    geometry_column: str = GEOMETRY_COLUMN_NAME,
) -> geopandas.GeoDataFrame:
    """Convert a query result to a GeoDataFrame in the layer's native CRS.

    Args:
        feed_name: Human-readable layer identifier for errors.
        layer: The layer that was queried.
        feature_set: The query result to convert.
        geometry_column: The output geometry-column name.

    Returns:
        The GeoDataFrame for the feed's features.

    Raises:
        NoFeaturesError: If the feed returns no features.
    """
    features = feature_set.features
    if not features:
        message = f"Feed {feed_name} returned no features; no output was written"
        raise arcgis_access.exceptions.NoFeaturesError(message)
    dataframe = feature_set.sdf
    dataframe, shapely_geometries, geometry_warning = extract_geometries(dataframe)
    if geometry_warning is not None:
        logger.warning(geometry_warning)
    bounds = arcgis_access.spatial_reference.bounds_of(shapely_geometries)
    spatial_reference_id = arcgis_access.spatial_reference.choose_spatial_reference_id(
        layer,
        feature_set,
        bounds,
    )
    return geo_data_frame_from(
        dataframe,
        shapely_geometries,
        spatial_reference_id,
        geometry_column=geometry_column,
    )


def query_with_retry(
    feed_name: str,
    layer: arcgis.features.FeatureLayer,
    *,
    maximum_retries: int = arcgis_access.retry.DEFAULT_MAXIMUM_RETRIES,
    parameters: dict[str, typing.Any] | None = None,
) -> arcgis.features.FeatureSet:
    """Query *layer* for features, retrying on transient and rate-limit errors.

    Args:
        feed_name: Human-readable feed identifier for log messages.
        layer: The FeatureLayer to query.
        maximum_retries: Maximum number of retries before giving up.
        parameters: Keyword arguments forwarded to ``layer.query``.

    Returns:
        The FeatureSet returned by a successful query.
    """
    query_parameters = {} if parameters is None else parameters
    return arcgis_access.retry.run_with_retry(
        feed_name,
        lambda: layer.query(**query_parameters),
        maximum_retries=maximum_retries,
    )


def query_object_ids_with_retry(
    feed_name: str,
    layer: arcgis.features.FeatureLayer,
    *,
    where: str,
    maximum_retries: int = arcgis_access.retry.DEFAULT_MAXIMUM_RETRIES,
) -> list[int]:
    """Return the OBJECTIDs of the features in *layer* matching *where*.

    The query requests only identifiers, so the response is a few bytes for most layers.
    An empty list means no features matched.

    Args:
        feed_name: Human-readable feed identifier for log messages.
        layer: The FeatureLayer to query.
        where: The SQL where clause selecting the features.
        maximum_retries: Maximum number of retries before giving up.

    Returns:
        The OBJECTIDs of the matching features.

    Raises:
        NoFeaturesError: If the service does not return an object id list.
    """
    result = arcgis_access.retry.run_with_retry(
        feed_name,
        lambda: layer.query(where=where, return_ids_only=True),
        maximum_retries=maximum_retries,
    )
    if not isinstance(result, dict) or "objectIds" not in result:
        message = f"Feed {feed_name} returned no object ids"
        raise arcgis_access.exceptions.NoFeaturesError(message)
    return [int(object_id) for object_id in result["objectIds"]]
