"""Clean fire perimeter polygons so Google Earth can render them.

Rapid mapping in WFIGS/IRWIN can leave details below the source resolution: zero-area
parts and holes, and narrow slits where a boundary doubles back on itself. Google
Earth's polygon renderer cannot handle these artifacts reliably. Remove them while
preparing derived perimeters, keeping the source files intact.

[Geometry policy](../../../docs/algorithms/perimeter-geometry-policy.md)
"""

from __future__ import annotations

import dataclasses
import typing

import pyproj
import shapely

import spatial_data.geometry
from measurement_units import units


if typing.TYPE_CHECKING:
    import pint


@dataclasses.dataclass(frozen=True, kw_only=True)
class PerimeterCleaningConfig:
    """Thresholds for cleaning a fire perimeter polygon.

    The area floor removes tiny parts and holes before simplification. The nominal
    deviation controls how much detail simplification removes; its conversion to degrees
    depends on latitude. These are rendering choices, not measures of source accuracy.
    """

    minimum_part_area: pint.Quantity[float] = 1e-6 * units.Unit("degrees ** 2")
    collinear_epsilon: pint.Quantity[float] = 1e-7 * units.degrees
    maximum_deviation: pint.Quantity[float] = 22.0 * units.meters


DEFAULT_CLEANING_CONFIG = PerimeterCleaningConfig()


def meridional_degree_length(latitude: float) -> pint.Quantity[float]:
    """Return the north-south length of one degree of latitude at *latitude*.

    Args:
        latitude: The latitude to measure at, in degrees.

    Returns:
        The meridional length of one degree, in meters per degree.
    """
    _forward_azimuth, _backward_azimuth, distance = pyproj.Geod(ellps="WGS84").inv(
        0.0,
        latitude,
        0.0,
        latitude + 1.0,
    )
    return distance * units.meters / units.degrees


def simplify_tolerance(
    geometry: shapely.Geometry,
    config: PerimeterCleaningConfig,
) -> pint.Quantity[float]:
    """Return the ring simplification tolerance for *geometry*.

    Convert the nominal deviation to degrees at the geometry's latitude. The collinear
    epsilon sets a lower bound when that conversion produces a smaller tolerance.

    Args:
        geometry: The geometry being cleaned, in degree coordinates.
        config: The cleaning thresholds.

    Returns:
        The simplification tolerance, in degrees.
    """
    maximum_deviation = config.maximum_deviation / meridional_degree_length(
        geometry.representative_point().y,
    )
    return max(config.collinear_epsilon, maximum_deviation)


def without_degenerate_holes(
    part: shapely.Polygon,
    config: PerimeterCleaningConfig,
) -> shapely.Polygon:
    """Return *part* with holes above the configured area floor.

    Drop holes at or below the floor, including zero-area rings. This removes tiny
    rendering details; it does not establish whether a hole is an unburned island.

    Args:
        part: The polygon part to filter.
        config: The cleaning thresholds.

    Returns:
        The part with holes whose angular area exceeds the configured floor.
    """
    return shapely.Polygon(
        part.exterior,
        [
            ring
            for ring in part.interiors
            if shapely.Polygon(ring).area * units.Unit("degrees ** 2")
            > config.minimum_part_area
        ],
    )


def clean_perimeter(
    geometry: shapely.Geometry | None,
    config: PerimeterCleaningConfig = DEFAULT_CLEANING_CONFIG,
) -> shapely.Geometry | None:
    """Return *geometry* cleaned for rendering.

    Remove parts and holes at or below the area floor, then simplify the surviving
    geometry with the latitude-adjusted angular tolerance. Simplify the assembled
    geometry together so its parts do not drift into one another, and repair an invalid
    result.

    When no part exceeds the floor, keep the original geometry: the threshold should not
    erase an entire fire. All changes happen in memory, leaving the source file intact.

    Args:
        geometry: The perimeter geometry, in degree coordinates.
        config: The cleaning thresholds.

    Returns:
        The cleaned geometry, which may be a geometry collection after validity repair.
        The original geometry stays unchanged when it has no polygon part above the
        area floor, including empty and non-polygonal inputs. None stays None.
    """
    if geometry is None or geometry.is_empty:
        return geometry
    parts = spatial_data.geometry.polygonal_parts(geometry)
    if not parts:
        return geometry
    kept = [
        without_degenerate_holes(part, config)
        for part in parts
        if part.area * units.Unit("degrees ** 2") > config.minimum_part_area
    ]
    if not kept:
        return geometry
    assembled = kept[0] if len(kept) == 1 else shapely.MultiPolygon(kept)
    simplified = shapely.simplify(
        assembled,
        simplify_tolerance(geometry, config).m_as("degrees"),
    )
    if simplified.is_valid:
        return simplified
    return shapely.make_valid(simplified)
