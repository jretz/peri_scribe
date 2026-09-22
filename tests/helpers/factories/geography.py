"""Build inputs for geography tests."""

from __future__ import annotations

import typing

import geopandas
import pyproj
import shapely
import shapely.geometry

from measurement_units import units


WEB_MERCATOR_WKID = 3857


CALIFORNIA_ALBERS_WKID = 3310


NAD83_WKID = 4269


NAD83_2011_WKID = 6318


NAVD88_HEIGHT_WKID = 5703


UNKNOWN_WKID = 999999


WEB_MERCATOR_MAXIMUM_MAGNITUDE = 20048966.104014598 * units.meters


def sample_geo_dataframe() -> geopandas.GeoDataFrame:
    """Return the canonical two-point WGS84 GeoDataFrame.

    Returns:
        A GeoDataFrame with two point features in WGS84.
    """
    return geopandas.GeoDataFrame(
        {"name": ["a", "b"]},
        geometry=[shapely.geometry.Point(1.0, 2.0), shapely.geometry.Point(3.0, 4.0)],
        crs=pyproj.CRS.from_epsg(WGS84_WKID),
    )


WGS84_WKID = 4326


def empty_frame() -> geopandas.GeoDataFrame:
    """Return an empty WGS84 GeoDataFrame.

    Returns:
        The empty frame.
    """
    return geopandas.GeoDataFrame(geometry=[], crs="EPSG:4326")


def geo_frame(
    columns: typing.Mapping[str, typing.Any],
    geometry: typing.Sequence[shapely.Geometry],
) -> geopandas.GeoDataFrame:
    """Build a WGS84 GeoDataFrame from *columns* and *geometry*.

    Args:
        columns: Each column name and its row values.
        geometry: The geometry of each row.

    Returns:
        The frame.
    """
    return geopandas.GeoDataFrame(columns, geometry=geometry, crs="EPSG:4326")
