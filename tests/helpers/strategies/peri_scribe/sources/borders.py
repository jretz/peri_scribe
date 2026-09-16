"""Generate borders examples with constrained domains."""

from __future__ import annotations

import itertools

import hypothesis.strategies
import shapely


@hypothesis.strategies.composite
def split_paths(
    draw: hypothesis.strategies.DrawFn,
) -> tuple[list[tuple[float, float]], list[shapely.LineString]]:
    """Keep the reference path independent of graph traversal and endpoint matching.

    Distinct increasing longitudes prevent self-intersections and snapping collisions.
    Internal latitudes vary freely, while splitting and direction obscure input order.

    Args:
        draw: The current example's strategy sampler.

    Returns:
        The west-to-east coordinates and reordered, independently reversed line parts.
    """
    longitudes = sorted(
        draw(
            hypothesis.strategies.lists(
                hypothesis.strategies.integers(-1700, 1700),
                min_size=2,
                max_size=15,
                unique=True,
            ),
        ),
    )
    coordinates = [
        (longitude / 10, float(draw(hypothesis.strategies.integers(-70, 70))))
        for longitude in longitudes
    ]
    boundaries = [
        0,
        *[
            index
            for index in range(1, len(coordinates) - 1)
            if draw(hypothesis.strategies.booleans())
        ],
        len(coordinates) - 1,
    ]
    parts = []
    for start, end in itertools.pairwise(boundaries):
        part = coordinates[start : end + 1]
        if draw(hypothesis.strategies.booleans()):
            part = part[::-1]
        parts.append(shapely.LineString(part))
    return coordinates, list(draw(hypothesis.strategies.permutations(parts)))
