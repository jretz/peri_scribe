"""Varied numeric observations and stroke styles for chart properties."""

from __future__ import annotations

import hypothesis.strategies

import svg_charts.models


def series_points() -> hypothesis.strategies.SearchStrategy[
    tuple[svg_charts.models.SeriesPoint, ...]
]:
    """Include solid and dashed strokes when testing plot transformations.

    Returns:
        Points with inferred observation times and bounded finite measurement values.
    """
    return hypothesis.strategies.lists(
        hypothesis.strategies.builds(
            svg_charts.models.SeriesPoint,
            value=hypothesis.strategies.floats(-1_000_000, 1_000_000),
            style=...,
        ),
        max_size=20,
    ).map(tuple)
