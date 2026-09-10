"""Constructing GeoDataFrames from ArcGIS FeatureSet query results.

Converts ArcGIS FeatureSet query results into GeoDataFrames in the layer's native
spatial reference and provides retry-aware querying for ArcGIS feature layers.
"""

from __future__ import annotations

import typing

import geopandas
import structlog

import peri_scribe.exceptions
import peri_scribe.geo.spatial_reference
import peri_scribe.models
import peri_scribe.retry
import peri_scribe.sources.feed_types


if typing.TYPE_CHECKING:
    import arcgis.features
    import pandas as pd
    import shapely


logger = structlog.get_logger()


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
    if peri_scribe.models.SHAPE_COLUMN_NAME not in dataframe.columns:
        return (
            dataframe,
            [None] * len(dataframe),
            (
                "  warning: all features lack geometry; "
                "writing the layer with NULL geometry"
            ),
        )
    return (
        dataframe.drop(columns=[peri_scribe.models.SHAPE_COLUMN_NAME]),
        list(
            dataframe[peri_scribe.models.SHAPE_COLUMN_NAME].geom.as_shapely,
        ),
        None,
    )


def geo_data_frame_from(
    dataframe: pd.DataFrame,
    shapely_geometries: list[shapely.Geometry | None],
    spatial_reference_id: int,
) -> geopandas.GeoDataFrame:
    """Build the output GeoDataFrame with its geometry column renamed.

    Args:
        dataframe: The feature attributes.
        shapely_geometries: The geometry for each feature, aligned with the rows.
        spatial_reference_id: The EPSG id of the output spatial reference.

    Returns:
        The GeoDataFrame with its geometry column renamed.
    """
    geo_data_frame = geopandas.GeoDataFrame(
        dataframe,
        geometry=shapely_geometries,
        crs=peri_scribe.geo.spatial_reference.spatial_reference_for_id(
            spatial_reference_id,
        ),
    )
    return typing.cast(
        "geopandas.GeoDataFrame",
        geo_data_frame.rename_geometry(peri_scribe.models.GEOMETRY_COLUMN_NAME),
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
        "out_sr": peri_scribe.models.WGS84_SPATIAL_REFERENCE_ID,
        "order_by_fields": "OBJECTID",
    }


def geo_data_frame_from_feature_set(
    feature_set: arcgis.features.FeatureSet,
) -> geopandas.GeoDataFrame:
    """Return a WGS 84 query result's features as a GeoDataFrame.

    A result whose features carry no geometry is returned with null geometry after
    logging why.

    Args:
        feature_set: The WGS 84 query result to convert.

    Returns:
        The features as a GeoDataFrame in WGS 84.
    """
    dataframe, shapely_geometries, geometry_warning = extract_geometries(
        feature_set.sdf,
    )
    if geometry_warning is not None:
        logger.warning(geometry_warning)
    return geo_data_frame_from(
        dataframe,
        shapely_geometries,
        peri_scribe.models.WGS84_SPATIAL_REFERENCE_ID,
    )


def dataframe_for_layer(
    feed: peri_scribe.sources.feed_types.Feed,
    layer: arcgis.features.FeatureLayer,
    feature_set: arcgis.features.FeatureSet,
) -> geopandas.GeoDataFrame:
    """Convert a query result to a GeoDataFrame in the layer's native CRS.

    Args:
        feed: The feed the query result came from.
        layer: The layer that was queried.
        feature_set: The query result to convert.

    Returns:
        The GeoDataFrame for the feed's features.

    Raises:
        NoFeaturesError: If the feed returns no features.
    """
    features = feature_set.features
    if not features:
        message = f"Feed {feed.name} returned no features; no output was written"
        raise peri_scribe.exceptions.NoFeaturesError(message)
    dataframe = feature_set.sdf
    dataframe, shapely_geometries, geometry_warning = extract_geometries(dataframe)
    if geometry_warning is not None:
        logger.warning(geometry_warning)
    bounds = peri_scribe.geo.spatial_reference.bounds_of(shapely_geometries)
    spatial_reference_id = (
        peri_scribe.geo.spatial_reference.choose_spatial_reference_id(
            layer,
            feature_set,
            bounds,
        )
    )
    return geo_data_frame_from(dataframe, shapely_geometries, spatial_reference_id)


def query_with_retry(
    feed_name: str,
    layer: arcgis.features.FeatureLayer,
    *,
    max_retries: int = peri_scribe.retry.DEFAULT_MAX_RETRIES,
    parameters: dict[str, typing.Any] | None = None,
) -> arcgis.features.FeatureSet:
    """Query *layer* for features, retrying on transient and rate-limit errors.

    Args:
        feed_name: Human-readable feed identifier for log messages.
        layer: The FeatureLayer to query.
        max_retries: Maximum number of retries before giving up.
        parameters: Keyword arguments forwarded to ``layer.query``.

    Returns:
        The FeatureSet returned by a successful query.
    """
    query_parameters = {} if parameters is None else parameters
    return peri_scribe.retry.run_with_retry(
        feed_name,
        lambda: layer.query(**query_parameters),
        max_retries=max_retries,
    )


def query_object_ids_with_retry(
    feed_name: str,
    layer: arcgis.features.FeatureLayer,
    *,
    where: str,
    max_retries: int = peri_scribe.retry.DEFAULT_MAX_RETRIES,
) -> list[int]:
    """Return the OBJECTIDs of the features in *layer* matching *where*.

    The query requests only identifiers, so the response is a few bytes for most layers.
    An empty list means no features matched.

    Args:
        feed_name: Human-readable feed identifier for log messages.
        layer: The FeatureLayer to query.
        where: The SQL where clause selecting the features.
        max_retries: Maximum number of retries before giving up.

    Returns:
        The OBJECTIDs of the matching features.

    Raises:
        NoFeaturesError: If the service does not return an object id list.
    """
    result = peri_scribe.retry.run_with_retry(
        feed_name,
        lambda: layer.query(where=where, return_ids_only=True),
        max_retries=max_retries,
    )
    if not isinstance(result, dict) or "objectIds" not in result:
        message = f"Feed {feed_name} returned no object ids"
        raise peri_scribe.exceptions.NoFeaturesError(message)
    return [int(object_id) for object_id in result["objectIds"]]
