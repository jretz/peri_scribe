"""Tests for svg_charts.svg."""

from __future__ import annotations

import hypothesis
import hypothesis.strategies

import svg_charts.svg


@hypothesis.given(
    span=hypothesis.strategies.floats(1e-9, 1e15),
    intervals=hypothesis.strategies.integers(1, 20),
)
def test_nice_step_covers_the_span_without_excessive_spacing(
    span: float,
    intervals: int,
) -> None:
    step = svg_charts.svg.nice_step(span, intervals)
    assert step > 0
    assert span <= step * intervals * (1 + 1e-12)
    assert step * intervals <= 2 * span * (1 + 1e-12)
