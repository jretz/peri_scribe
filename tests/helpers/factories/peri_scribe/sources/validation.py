"""Build inputs for validation tests."""

from __future__ import annotations

import geopandas
import pyproj
import shapely.geometry

import peri_scribe.sources.feed_types


def validation_feed(index: int) -> peri_scribe.sources.feed_types.ArcGISFeed:
    """Return a feed with a name unique to *index*.

    Args:
        index: The number that distinguishes the feed's name.

    Returns:
        The feed.
    """
    return peri_scribe.sources.feed_types.ArcGISFeed(
        url=(f"https://example.test/ArcGIS/rest/services/Fires{index}/FeatureServer/0"),
        fire_name_column="name",
        status_column="status",
    )


def frame_without_object_id() -> geopandas.GeoDataFrame:
    """Return a GeoDataFrame with one point feature and no OBJECTID column.

    Returns:
        The GeoDataFrame.
    """
    return geopandas.GeoDataFrame(
        {"name": ["a"]},
        geometry=[shapely.geometry.Point(0.0, 0.0)],
        crs=pyproj.CRS.from_epsg(4326),
    )
