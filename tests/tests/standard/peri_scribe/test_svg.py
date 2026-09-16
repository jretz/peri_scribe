"""Tests for peri_scribe.svg."""

from __future__ import annotations

import pytest

import peri_scribe.svg


def test_nice_step_handles_an_empty_span_with_eight_intervals() -> None:
    assert peri_scribe.svg.nice_step(0.0, 8) == pytest.approx(1.0)


def test_nice_step_handles_an_empty_span_with_four_intervals() -> None:
    assert peri_scribe.svg.nice_step(0.0, 4) == pytest.approx(1.0)
