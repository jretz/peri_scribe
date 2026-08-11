"""GeoDataFrame construction and query helpers for peri_scribe.

Converts ArcGIS FeatureSet query results into GeoDataFrames in the layer's native
spatial reference, and provides retry-aware querying for ArcGIS feature layers.
"""

from __future__ import annotations

import time
import typing

import geopandas
import pyproj
import structlog

import peri_scribe.exceptions
import peri_scribe.models
import peri_scribe.retry
import peri_scribe.spatial_reference


if typing.TYPE_CHECKING:
    import arcgis.features
    import pandas as pd
    import shapely


logger = structlog.get_logger()


def extract_geometries(
    dataframe: pd.DataFrame,
) -> tuple[pd.DataFrame, list[shapely.Geometry | None], str | None]:
    """Separate a feature dataframe's SHAPE column from its attributes.

    Returns:
        The dataframe with the SHAPE column removed, the shapely geometries of its
        features (None where a feature has no geometry), and a warning to report when
        the dataframe has no geometry column.
    """
    if "SHAPE" not in dataframe.columns:
        return (
            dataframe,
            [None] * len(dataframe),
            (
                "  warning: all features lack geometry; "
                "writing the layer with NULL geometry"
            ),
        )
    return (
        dataframe.drop(columns=["SHAPE"]),
        list(dataframe["SHAPE"].geom.as_shapely),
        None,
    )


def geo_data_frame_from(
    dataframe: pd.DataFrame,
    shapely_geometries: list[shapely.Geometry | None],
    spatial_reference_id: int,
) -> geopandas.GeoDataFrame:
    """Build the output GeoDataFrame with its geometry column renamed.

    Returns:
        The GeoDataFrame with its geometry column renamed.
    """
    geo_data_frame = geopandas.GeoDataFrame(
        dataframe,
        geometry=shapely_geometries,
        crs=pyproj.CRS.from_epsg(spatial_reference_id),
    )
    return geo_data_frame.rename_geometry(
        peri_scribe.models.GEOMETRY_COLUMN_NAME,
        inplace=False,
    )


def dataframe_for_layer(
    feed: peri_scribe.models.ArcGISFeed,
    layer: arcgis.features.FeatureLayer,
    feature_set: arcgis.features.FeatureSet,
) -> geopandas.GeoDataFrame:
    """Convert a query result to a GeoDataFrame in the layer's native CRS.

    Returns:
        The GeoDataFrame for the feed's features.

    Raises:
        NoFeaturesError: If the feed returns no features.
    """
    features = feature_set.features
    if not features:
        message = (
            f"Feed {feed.name} returned no features; "
            f"{peri_scribe.models.OUTPUT_FILENAME} was not modified"
        )
        raise peri_scribe.exceptions.NoFeaturesError(message)
    dataframe = feature_set.sdf
    dataframe, shapely_geometries, geometry_warning = extract_geometries(dataframe)
    if geometry_warning is not None:
        logger.warning(geometry_warning)
    bounds = peri_scribe.spatial_reference.bounds_of(shapely_geometries)
    spatial_reference_id = peri_scribe.spatial_reference.choose_spatial_reference_id(
        layer,
        feature_set,
        bounds,
    )
    return geo_data_frame_from(dataframe, shapely_geometries, spatial_reference_id)


def query_with_retry(
    feed_name: str,
    layer: arcgis.features.FeatureLayer,
    *,
    max_retries: int = peri_scribe.retry.DEFAULT_MAX_RETRIES,
) -> arcgis.features.FeatureSet:
    """Query *layer*, retrying on transient and rate-limit errors.

    Rate-limit errors (HTTP 429 from the ArcGIS REST API) use the server-
    suggested ``Retry after`` delay. Other transient network errors use
    exponential backoff starting at ``BACKOFF_BASE_SECONDS`` and capped at
    ``BACKOFF_MAXIMUM_SECONDS``.

    Args:
        feed_name: Human-readable feed identifier for log messages.
        layer: The FeatureLayer to query.
        max_retries: Maximum number of retries before giving up.

    Returns:
        The FeatureSet returned by a successful query.
    """
    attempts_made = 0
    while True:
        attempts_made += 1
        try:
            return layer.query()
        except Exception as error:
            retry_seconds = peri_scribe.retry.rate_limit_retry_seconds(error)
            if retry_seconds is not None:
                retry_reason = "Rate-limited; retrying after server-suggested delay"
            elif peri_scribe.retry.is_transient_error(error):
                retry_seconds = peri_scribe.retry.compute_backoff(attempts_made)
                retry_reason = "Transient network error; retrying after backoff"
            else:
                raise

            if attempts_made > max_retries:
                logger.exception(
                    "Retries exhausted",
                    feed=feed_name,
                    attempts=attempts_made,
                    reason=retry_reason,
                )
                raise
            logger.warning(
                retry_reason,
                feed=feed_name,
                attempt=attempts_made,
                retry_seconds=retry_seconds,
            )
            time.sleep(retry_seconds)
