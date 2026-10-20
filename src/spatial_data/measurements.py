"""Geodesic measurements share one unit registry across their callers.

See [Measurement reasoning] for the contract and correctness argument.

[Measurement reasoning]: ../../docs/algorithms/spatial-queries-and-measurements.md
"""

from __future__ import annotations

import typing

import pyproj
import shapely

import spatial_data.geometry
from measurement_units import units


if typing.TYPE_CHECKING:
    import pint


def area(geometry: shapely.Geometry) -> pint.Quantity[float]:
    """Return the absolute geodesic area of *geometry*.

    Measuring on the WGS84 ellipsoid avoids treating longitude and latitude as flat
    coordinates. Consistent ring orientation makes disjoint parts add and holes
    subtract.

    Args:
        geometry: The geometry to measure, in WGS 84 degrees.

    Returns:
        The absolute area as a quantity in square meters.

    Examples:
        >>> area(shapely.Point(0, 0)).m_as("acres")
        0.0
    """
    measured_area = signed_area(
        shapely.orient_polygons(geometry),
        pyproj.Geod(ellps="WGS84"),
    )
    return abs(measured_area) * units.Unit("meters ** 2")


def signed_area(geometry: shapely.Geometry, geodesic: pyproj.Geod) -> float:
    """Retain the geodesic calculator's recursive order of signed area additions.

    Polygon rings pass coordinate arrays directly to the calculator. Other leaves use
    its geometry adapter to preserve its treatment of points and lines.

    Args:
        geometry: An oriented geometry with WGS84 coordinates in degrees.
        geodesic: The current measurement's WGS84 calculator.

    Returns:
        Signed area in the calculator's native square meters.
    """
    if isinstance(geometry, shapely.Polygon):
        measured_area = ring_area(geometry.exterior, geodesic)
        for interior in geometry.interiors:
            measured_area += ring_area(interior, geodesic)
        return measured_area
    if isinstance(
        geometry,
        shapely.GeometryCollection
        | shapely.MultiPolygon
        | shapely.MultiLineString
        | shapely.MultiPoint,
    ):
        measured_area = 0.0
        for part in geometry.geoms:
            measured_area += signed_area(part, geodesic)
        return measured_area
    return geodesic.geometry_area_perimeter(geometry)[0]


def ring_area(geometry: shapely.LinearRing, geodesic: pyproj.Geod) -> float:
    """Measure an oriented ring through coordinate arrays in their existing order.

    Args:
        geometry: One polygon ring with WGS84 coordinates in degrees.
        geodesic: The current measurement's WGS84 calculator.

    Returns:
        Signed area in the calculator's native square meters.
    """
    coordinates = shapely.get_coordinates(geometry)
    measured_area, _perimeter = geodesic.polygon_area_perimeter(
        coordinates[:, 0],
        coordinates[:, 1],
    )
    return measured_area


def exterior_perimeter(
    geometry: shapely.Geometry | None,
) -> pint.Quantity[float] | None:
    """Return *geometry*'s exterior perimeter length, or None.

    Each polygon's outer ring is measured on the WGS84 ellipsoid, then the lengths are
    added. Interior rings are excluded. Missing, empty, and non-polygonal geometries
    have no exterior perimeter.

    Args:
        geometry: The perimeter geometry, in WGS 84 degrees.

    Returns:
        The exterior perimeter length as a quantity in meters, or None when there is no
        polygon exterior to measure.

    Examples:
        >>> exterior_perimeter(None) is None
        True
    """
    if geometry is None or geometry.is_empty:
        return None
    exteriors = [
        shapely.LineString(part.exterior)
        for part in spatial_data.geometry.polygonal_parts(geometry)
    ]
    if not exteriors:
        return None
    geodesic = pyproj.Geod(ellps="WGS84")
    length = sum(geodesic.geometry_length(exterior) for exterior in exteriors)
    return length * units.meters
