"""Tests for peri_scribe.svg."""

from __future__ import annotations

import hypothesis
import hypothesis.strategies
import pytest

import peri_scribe.svg


@hypothesis.given(
    span=hypothesis.strategies.floats(1e-9, 1e15),
    intervals=hypothesis.strategies.integers(1, 20),
)
def test_nice_step_covers_the_span_without_excessive_spacing(
    span: float,
    intervals: int,
) -> None:
    step = peri_scribe.svg.nice_step(span, intervals)
    assert step > 0
    assert span <= step * intervals * (1 + 1e-12)
    assert step * intervals <= 2 * span * (1 + 1e-12)


def test_nice_step_handles_an_empty_span_with_eight_intervals() -> None:
    assert peri_scribe.svg.nice_step(0.0, 8) == pytest.approx(1.0)


def test_nice_step_handles_an_empty_span_with_four_intervals() -> None:
    assert peri_scribe.svg.nice_step(0.0, 4) == pytest.approx(1.0)
