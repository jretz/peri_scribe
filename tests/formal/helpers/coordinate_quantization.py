"""Binary64 neighbors expose rounding and envelope edges around the stored grid."""

import itertools
import math

import numpy as np

import spatial_data.point_store
import tests.formal.helpers.spatial_index


def axis_values(limit: int) -> list[float]:
    """Tile edges, half ticks, zero, and geographic endpoints need both neighbors.

    Args:
        limit: The geographic axis limit in integer degrees.

    Returns:
        Finite valid binary64 values covering boundary and seeded interior cases.
    """
    scale = spatial_data.point_store.COORDINATE_SCALE
    values = {-0.0, 0.0}
    for boundary, displacement in itertools.product(
        range(-limit * scale, limit * scale + 1, 50_000),
        (-1.5, -1.0, -0.5, 0.0, 0.5, 1.0, 1.5),
    ):
        value = (boundary + displacement) / scale
        values.update((
            math.nextafter(value, -math.inf),
            value,
            math.nextafter(value, math.inf),
        ))
    generator = np.random.default_rng(20261002 + limit)
    values.update(float(value) for value in generator.uniform(-limit, limit, 1000))
    return sorted(value for value in values if -limit <= value <= limit)


def command(value: float) -> str:
    """The exact scaled binary64 rational separates rounding from multiplication error.

    Args:
        value: One finite geographic coordinate.

    Returns:
        A request for the proved rational ties-to-even algorithm.
    """
    numerator, denominator = (
        value * spatial_data.point_store.COORDINATE_SCALE
    ).as_integer_ratio()
    return f"quantize {numerator} {denominator}"


def query_cases() -> tuple[
    list[tuple[int, int]],
    list[tuple[float, float, float, float]],
]:
    """Very narrow envelopes must preserve the grid points their float bounds contain.

    Returns:
        A stored point bag and both-sided envelopes near tile and world boundaries.
    """
    scale = spatial_data.point_store.COORDINATE_SCALE
    points = tests.formal.helpers.spatial_index.coordinate_boundaries()[::23]
    points.extend([
        (-18_000_000, -9_000_000),
        (18_000_000, 9_000_000),
        (-12_200_001, 3_750_001),
        (-1, -1),
        (0, 0),
        (1, 1),
    ])
    points += points[::7]
    boxes = []
    for longitude, latitude in points:
        horizontal = longitude / scale
        vertical = latitude / scale
        for delta in (-0.5 / scale, 0.0, 0.5 / scale):
            left = math.nextafter(horizontal + delta, -math.inf)
            bottom = math.nextafter(vertical + delta, -math.inf)
            right = math.nextafter(horizontal + delta, math.inf)
            top = math.nextafter(vertical + delta, math.inf)
            boxes.extend([
                (left, bottom, right, top),
                (left, bottom, horizontal + 1 / scale, vertical + 1 / scale),
                (horizontal - 1 / scale, vertical - 1 / scale, right, top),
            ])
    return points, boxes
