"""Generate buildings examples with constrained domains."""

from __future__ import annotations

import hypothesis.strategies
import numpy as np
import shapely
import shapely.affinity

import tests.helpers.strategies.geometry


def encoded_coordinate(maximum: int) -> hypothesis.strategies.SearchStrategy[int]:
    """Exercise the inclusive geographic extremes as well as ordinary coordinates.

    Args:
        maximum: The largest representable longitude or latitude magnitude.

    Returns:
        An encoded coordinate with frequent samples at the limits of its domain.
    """
    return hypothesis.strategies.one_of(
        hypothesis.strategies.integers(-maximum, maximum),
        hypothesis.strategies.sampled_from([-maximum, maximum]),
    )


def encoded_points() -> hypothesis.strategies.SearchStrategy[list[tuple[int, int]]]:
    """Exercise signed coordinates, repeated records, and empty payloads.

    Returns:
        Lists of coordinate pairs in the database's quantized WGS84 domain.
    """
    return hypothesis.strategies.lists(
        hypothesis.strategies.tuples(
            encoded_coordinate(18_000_000),
            encoded_coordinate(9_000_000),
        ),
        max_size=40,
    )


@hypothesis.strategies.composite
def building_queries(
    draw: hypothesis.strategies.DrawFn,
) -> tuple[np.ndarray, list[shapely.Geometry | None]]:
    """Place buildings and queries on a shared grid to exercise containment boundaries.

    Small coordinate offsets straddle quantization thresholds; the grid crosses tile
    boundaries and allows duplicates, polygon holes, and bounding-box false positives.

    Args:
        draw: The current example's strategy sampler.

    Returns:
        Building centroids and nearby geometries to query against the stored points.
    """
    longitude = draw(hypothesis.strategies.integers(-340, 340)) / 2
    latitude = draw(hypothesis.strategies.integers(-140, 140)) / 2
    coordinate = hypothesis.strategies.tuples(
        hypothesis.strategies.integers(-2, 18),
        hypothesis.strategies.sampled_from(
            [-0.000006, -0.000004, 0, 0.000004, 0.000006],
        ),
    ).map(lambda pair: pair[0] / 4 + pair[1])
    points = np.asarray(
        draw(
            hypothesis.strategies.lists(
                hypothesis.strategies.tuples(coordinate, coordinate),
                max_size=40,
            ),
        ),
        dtype=float,
    ).reshape(-1, 2)
    points += [longitude, latitude]
    shapes = draw(
        hypothesis.strategies.lists(
            hypothesis.strategies.one_of(
                tests.helpers.strategies.geometry.local_shapes(),
                hypothesis.strategies.just(shapely.Polygon()),
                hypothesis.strategies.none(),
            ),
            max_size=6,
        ),
    )
    queries = [
        None
        if shape is None
        else shapely.affinity.translate(
            shapely.affinity.scale(shape, xfact=0.5, yfact=0.5, origin=(0, 0)),
            xoff=longitude,
            yoff=latitude,
        )
        for shape in shapes
    ]
    return points, queries
