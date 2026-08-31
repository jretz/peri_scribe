"""Physical unit conversions and area measurement for peri_scribe."""

from __future__ import annotations

import pyproj
import shapely


SQUARE_METERS_PER_ACRE = 4046.8564224

MILLISECONDS_PER_SECOND = 1000.0

METERS_PER_KILOMETER = 1000.0

MILES_PER_KILOMETER = 0.621371192237334


def area_in_square_meters(geometry: shapely.Geometry) -> float:
    """Return *geometry*'s area in square meters.

    The area is computed geodesically so it is accurate anywhere on Earth.

    Args:
        geometry: The geometry to measure, in WGS 84 degrees.

    Returns:
        The absolute area in square meters.
    """
    area_in_square_meters, _perimeter = pyproj.Geod(
        ellps="WGS84",
    ).geometry_area_perimeter(geometry)
    return abs(area_in_square_meters)


def area_in_acres(geometry: shapely.Geometry) -> float:
    """Return *geometry*'s area in acres.

    The area is computed geodesically so it is accurate anywhere on Earth.

    Args:
        geometry: The geometry to measure, in WGS 84 degrees.

    Returns:
        The absolute area in acres.
    """
    return area_in_square_meters(geometry) / SQUARE_METERS_PER_ACRE


def exterior_perimeter_in_miles(geometry: shapely.Geometry | None) -> float | None:
    """Return *geometry*'s exterior perimeter length in miles, or None.

    The length is the sum of each polygon part's outer ring, measured geodesically
    so it is accurate anywhere on Earth. Interior rings (unburned islands inside a
    fire perimeter) are excluded, and a geometry without any polygon exterior —
    empty, missing, or non-polygonal — has no exterior perimeter.

    Args:
        geometry: The perimeter geometry, in WGS 84 degrees.

    Returns:
        The exterior perimeter length in miles, or None when there is no polygon
        exterior to measure.
    """
    if geometry is None or geometry.is_empty:
        return None
    exteriors = [
        shapely.LineString(part.exterior)
        for part in shapely.get_parts(geometry)
        if part.geom_type == "Polygon" and not part.is_empty
    ]
    if not exteriors:
        return None
    geod = pyproj.Geod(ellps="WGS84")
    length_in_meters = sum(geod.geometry_length(exterior) for exterior in exteriors)
    return length_in_meters / METERS_PER_KILOMETER * MILES_PER_KILOMETER
