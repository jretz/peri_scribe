"""Overlay polygonal growth on one fixed longitude/latitude precision grid.

The binary grid keeps coordinates exactly representable and leaves about three digits
of floating-point headroom in the WGS84 coordinate domain. Sub-grid area features can
collapse; lower-dimensional remnants contribute no covered ground.

[Growth geometry and area](../../../docs/algorithms/growth-geometry-and-area.md)
"""

from __future__ import annotations

import shapely

from measurement_units import units


GRID_SIZE = 2**-30 * units.degrees


def polygonal(geometry: shapely.Geometry | None) -> shapely.Geometry | None:
    """Keep polygonal covered ground, merging collection members on the common grid.

    Args:
        geometry: A valid geometry, including nested collections, or None.

    Returns:
        Polygonal ground, or None when no positive-dimensional area remains.
    """
    if geometry is None or geometry.is_empty:
        return None
    if isinstance(geometry, shapely.Polygon | shapely.MultiPolygon):
        return geometry
    if not isinstance(geometry, shapely.GeometryCollection):
        return None
    parts = [area for part in geometry.geoms if (area := polygonal(part)) is not None]
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]
    return polygonal(shapely.union_all(parts, grid_size=GRID_SIZE.m_as("degrees")))


def normalize(geometry: shapely.Geometry | None) -> shapely.Geometry | None:
    """Represent valid polygonal ground on the shared binary degree grid.

    Args:
        geometry: A valid WGS84 geometry with finite coordinates, or None.

    Returns:
        Valid polygonal area with the common precision attached, or None when empty.
        Precision reduction can remove collapsed sub-grid islands, holes, or spikes.
    """
    area = polygonal(geometry)
    if area is None:
        return None
    grid = GRID_SIZE.m_as("degrees")
    if shapely.get_precision(area) == grid:
        return area
    return polygonal(shapely.set_precision(area, grid))


def union(
    left: shapely.Geometry | None,
    right: shapely.Geometry | None,
) -> shapely.Geometry | None:
    """Combine polygonal ground using fixed-precision snap rounding.

    Args:
        left: Existing covered ground, or None.
        right: Additional covered ground, or None.

    Returns:
        Their polygonal union on the common precision grid, or None when empty.
    """
    left = normalize(left)
    right = normalize(right)
    if left is None:
        return right
    if right is None:
        return left
    return polygonal(shapely.union(left, right, grid_size=GRID_SIZE.m_as("degrees")))


def intersection(
    left: shapely.Geometry | None,
    right: shapely.Geometry | None,
) -> shapely.Geometry | None:
    """Retain shared polygonal ground using fixed-precision snap rounding.

    Args:
        left: An earlier footprint, or None.
        right: The later corrected footprint, or None.

    Returns:
        Shared polygonal ground on the common grid, or None when absent.
    """
    left = normalize(left)
    right = normalize(right)
    if left is None or right is None:
        return None
    return polygonal(
        shapely.intersection(left, right, grid_size=GRID_SIZE.m_as("degrees")),
    )


def difference(
    left: shapely.Geometry | None,
    right: shapely.Geometry | None,
) -> shapely.Geometry | None:
    """Remove earlier polygonal ground using fixed-precision snap rounding.

    Args:
        left: The current corrected footprint, or None.
        right: Its corrected predecessor, or None.

    Returns:
        The left footprint outside the right on the common grid, or None when empty.
    """
    left = normalize(left)
    right = normalize(right)
    if left is None:
        return None
    if right is None:
        return left
    return polygonal(
        shapely.difference(left, right, grid_size=GRID_SIZE.m_as("degrees")),
    )
