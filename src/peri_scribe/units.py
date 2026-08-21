"""Physical unit conversions and area measurement for peri_scribe."""

from __future__ import annotations

import typing

import pyproj


if typing.TYPE_CHECKING:
    import shapely


SQUARE_METERS_PER_ACRE = 4046.8564224

MILLISECONDS_PER_SECOND = 1000.0

METERS_PER_KILOMETER = 1000.0


def area_in_acres(geometry: shapely.Geometry) -> float:
    """Return *geometry*'s area in acres.

    The area is computed geodesically so it is accurate anywhere on Earth.

    Args:
        geometry: The geometry to measure, in WGS 84 degrees.

    Returns:
        The absolute area in acres.
    """
    area_in_square_meters, _perimeter = pyproj.Geod(
        ellps="WGS84",
    ).geometry_area_perimeter(geometry)
    return abs(area_in_square_meters) / SQUARE_METERS_PER_ACRE
