"""Tests for peri_scribe.fires.scores."""

from __future__ import annotations

import geopandas
import shapely.geometry


def point(x: float, y: float) -> shapely.geometry.Point:
    """Return a WGS84 point at the given coordinates.

    Args:
        x: The longitude.
        y: The latitude.

    Returns:
        The point.
    """
    return shapely.geometry.Point(x, y)


def square(side: float) -> shapely.geometry.Polygon:
    """Return a square of the given side, centered at the origin.

    Args:
        side: The length of each side.

    Returns:
        The square.
    """
    half = side / 2
    return shapely.geometry.box(-half, -half, half, half)


def empty_frame(crs: str = "EPSG:4326") -> geopandas.GeoDataFrame:
    """Return an empty GeoDataFrame in the given spatial reference.

    Args:
        crs: The spatial reference.

    Returns:
        The empty GeoDataFrame.
    """
    return geopandas.GeoDataFrame(geometry=[], crs=crs)


def perimeter_frame(
    records: list[dict[str, object]],
    geometries: list[shapely.geometry.base.BaseGeometry],
) -> geopandas.GeoDataFrame:
    """Build a perimeter-history GeoDataFrame from attribute overrides.

    Args:
        records: One attribute override per row.
        geometries: The rows' geometries.

    Returns:
        The rows as a GeoDataFrame with the perimeter columns scoring reads.
    """
    columns = [
        "fire_name",
        "fire_identifier",
        "area_acres",
        "area_acres_differential",
        "observation_time",
    ]
    rows = [{column: record.get(column) for column in columns} for record in records]
    return geopandas.GeoDataFrame(rows, geometry=geometries, crs="EPSG:4326")


def point_frame(
    records: list[dict[str, object]],
    geometries: list[shapely.geometry.base.BaseGeometry],
) -> geopandas.GeoDataFrame:
    """Build a point-history GeoDataFrame from attribute overrides.

    Args:
        records: One attribute override per row.
        geometries: The rows' geometries.

    Returns:
        The rows as a GeoDataFrame with the point columns scoring reads.
    """
    columns = ["fire_name", "fire_identifier", "source_attributes"]
    rows = [{column: record.get(column) for column in columns} for record in records]
    return geopandas.GeoDataFrame(rows, geometry=geometries, crs="EPSG:4326")
