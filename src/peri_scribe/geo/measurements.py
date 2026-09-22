"""Shared measurements stored alongside the geometry they describe."""

from __future__ import annotations

import typing

import peri_scribe.geo.parsing
import spatial_data.measurements
from measurement_units import units


if typing.TYPE_CHECKING:
    import pint
    import shapely


AREA_COLUMN = "geometry_area_square_meters"
EXTERIOR_COLUMN = "exterior_perimeter_meters"


def area(geometry: shapely.Geometry, stored: object = None) -> pint.Quantity[float]:
    """Use the persisted measurement when available, otherwise measure the shape.

    Args:
        geometry: The geometry described by the stored area.
        stored: The stored area in square meters, or a missing or nonnumeric value when
            the geometry must be measured.

    Returns:
        The geometry's geodesic area.
    """
    value = peri_scribe.geo.parsing.numeric_value(stored)
    if value is not None:
        return value * units.Unit("meters ** 2")
    return spatial_data.measurements.area(geometry)


def exterior_perimeter(
    geometry: shapely.Geometry | None,
    stored: object = None,
) -> pint.Quantity[float] | None:
    """Let history consumers share the same exterior-length measurement.

    Args:
        geometry: The geometry described by the stored length, or None.
        stored: The stored exterior length in meters, or a missing or nonnumeric value
            when the geometry must be measured.

    Returns:
        The exterior length, or None for a geometry without an exterior.
    """
    value = peri_scribe.geo.parsing.numeric_value(stored)
    if value is not None:
        return value * units.meters
    return spatial_data.measurements.exterior_perimeter(geometry)
