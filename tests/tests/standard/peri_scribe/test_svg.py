"""Tests for peri_scribe.svg."""

from __future__ import annotations

import pytest

import peri_scribe.svg


@pytest.mark.parametrize(
    ("span", "expected"),
    [(0.8, 0.1), (1.2, 0.2), (2.0, 0.25), (3.2, 0.5), (6.0, 1.0)],
)
def test_nice_step_selects_the_smallest_rung_covering_the_interval(
    span: float,
    expected: float,
) -> None:
    assert peri_scribe.svg.nice_step(span, 8) == pytest.approx(expected)


def test_nice_step_handles_an_empty_span_with_eight_intervals() -> None:
    assert peri_scribe.svg.nice_step(0.0, 8) == pytest.approx(1.0)


def test_nice_step_handles_an_empty_span_with_four_intervals() -> None:
    assert peri_scribe.svg.nice_step(0.0, 4) == pytest.approx(1.0)
