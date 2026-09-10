"""Geodesic area and perimeter measurement for peri_scribe."""

from __future__ import annotations

import pint
import pyproj
import shapely

import peri_scribe.geo.geometry


# The pint unit registry shared by every module that works with physical quantities.
units = pint.UnitRegistry()

# Costs are reported in US dollars; pint has no built-in currency unit, so one is
# defined with its common symbols and the ISO 4217 code.
units.define("dollar = [currency] = $ = USD")


def area(geometry: shapely.Geometry) -> pint.Quantity[float]:
    """Return the absolute geodesic area of *geometry*.

    The area is computed geodesically so it is accurate anywhere on Earth.

    Args:
        geometry: The geometry to measure, in WGS 84 degrees.

    Returns:
        The absolute area as a quantity in square meters.

    Examples:
        >>> area(shapely.Point(0, 0)).m_as("acres")
        0.0
    """
    measured_area, _perimeter = pyproj.Geod(
        ellps="WGS84",
    ).geometry_area_perimeter(geometry)
    return abs(measured_area) * units.meters**2


def exterior_perimeter(
    geometry: shapely.Geometry | None,
) -> pint.Quantity[float] | None:
    """Return *geometry*'s exterior perimeter length, or None.

    The length is the sum of each polygon part's outer ring, measured geodesically
    so it is accurate anywhere on Earth. Interior rings (unburned islands inside a
    fire perimeter) are excluded, and a geometry without any polygon exterior —
    empty, missing, or non-polygonal — has no exterior perimeter.

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
        for part in peri_scribe.geo.geometry.polygonal_parts(geometry)
    ]
    if not exteriors:
        return None
    geod = pyproj.Geod(ellps="WGS84")
    length = sum(geod.geometry_length(exterior) for exterior in exteriors)
    return length * units.meters
