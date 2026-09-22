"""Application phase logging around ArcGIS layer queries and conversion."""

from __future__ import annotations

import typing

import arcgis_access.data
import arcgis_access.retry
import peri_scribe.logging
import peri_scribe.phases
import peri_scribe.sources.feed_types


if typing.TYPE_CHECKING:
    import arcgis.features
    import geopandas


def dataframe_for_layer(
    feed: peri_scribe.sources.feed_types.Feed,
    layer: arcgis.features.FeatureLayer,
    feature_set: arcgis.features.FeatureSet,
) -> geopandas.GeoDataFrame:
    """Convert a configured feed's result within its application phase.

    Args:
        feed: The configured feed providing the layer.
        layer: The queried ArcGIS layer.
        feature_set: The query result to convert.

    Returns:
        The features in the layer's native coordinate reference system.
    """
    with peri_scribe.logging.log_phase(
        peri_scribe.phases.Phase.CONVERT_FEATURES,
        feed=feed.name,
    ):
        return arcgis_access.data.dataframe_for_layer(feed.name, layer, feature_set)


def query_with_retry(
    feed_name: str,
    layer: arcgis.features.FeatureLayer,
    *,
    maximum_retries: int = arcgis_access.retry.DEFAULT_MAXIMUM_RETRIES,
    parameters: dict[str, typing.Any] | None = None,
) -> arcgis.features.FeatureSet:
    """Query a layer within the application's feature-query phase.

    Args:
        feed_name: Human-readable layer identifier for logs.
        layer: The ArcGIS layer to query.
        maximum_retries: Maximum retries before the failure propagates.
        parameters: Keyword arguments passed to the ArcGIS query.

    Returns:
        The successful feature query result.
    """
    with peri_scribe.logging.log_phase(
        peri_scribe.phases.Phase.QUERY_FEATURES,
        feed=feed_name,
    ):
        return arcgis_access.data.query_with_retry(
            feed_name,
            layer,
            maximum_retries=maximum_retries,
            parameters=parameters,
        )
