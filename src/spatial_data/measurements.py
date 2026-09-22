"""Geodesic measurements share one unit registry across their callers."""

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

    The area is computed geodesically so it is accurate anywhere on Earth. Consistent
    ring orientation makes disjoint parts add and holes subtract.

    Args:
        geometry: The geometry to measure, in WGS 84 degrees.

    Returns:
        The absolute area as a quantity in square meters.

    Examples:
        >>> area(shapely.Point(0, 0)).m_as("acres")
        0.0
    """
    measured_area, _perimeter = pyproj.Geod(ellps="WGS84").geometry_area_perimeter(
        shapely.orient_polygons(geometry),
    )
    return abs(measured_area) * units.Unit("meters ** 2")


def exterior_perimeter(
    geometry: shapely.Geometry | None,
) -> pint.Quantity[float] | None:
    """Return *geometry*'s exterior perimeter length, or None.

    The length is the sum of each polygon part's outer ring, measured geodesically so it
    is accurate anywhere on Earth. Interior rings are excluded. Missing, empty, and
    non-polygonal geometries have no exterior perimeter.

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
