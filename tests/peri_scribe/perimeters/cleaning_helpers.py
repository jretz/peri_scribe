"""Provide data builders and stand-ins for cleaning tests."""

import shapely.geometry


def noisy_top_edge_polygon() -> shapely.geometry.Polygon:
    """Return a square whose top edge carries many small wiggles.

    The wiggles are far smaller than the cleaning deviation but far larger than the
    collinear epsilon, so they exercise the slit-killing simplification rather than the
    collinear removal alone.

    Returns:
        The noisy square.
    """
    points = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)]
    for index in range(99, 0, -1):
        x = index / 100.0
        y = 1.0 + (0.00001 if index % 2 == 0 else -0.00001)
        points.append((x, y))
    points.extend(((0.0, 1.0), (0.0, 0.0)))
    return shapely.geometry.Polygon(points)
