"""Build inputs for geometry tests."""

from __future__ import annotations

import shapely.geometry


def polygon(*args: tuple[float, float]) -> shapely.geometry.Polygon:
    """Return a polygon from *args*.

    Args:
        args: The polygon's exterior points.

    Returns:
        The polygon.
    """
    return shapely.geometry.Polygon(args)


def square(side: float) -> shapely.geometry.Polygon:
    """Return a square of *side* degrees centered at the origin.

    Args:
        side: The length of each side.

    Returns:
        The square.
    """
    half = side / 2
    return shapely.geometry.box(-half, -half, half, half)


def point(x: float, y: float) -> shapely.geometry.Point:
    """Return a point at *x*, *y*.

    Args:
        x: The longitude.
        y: The latitude.

    Returns:
        The point.
    """
    return shapely.geometry.Point(x, y)
