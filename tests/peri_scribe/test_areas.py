"""Tests for peri_scribe.areas."""

from __future__ import annotations

import pytest

import peri_scribe.areas


def test_presented_area_in_acres_prefers_calculated_when_significantly_larger() -> None:
    assert peri_scribe.areas.presented_area_in_acres(1100.0, 2939.0) == pytest.approx(
        2939.0,
    )


def test_presented_area_in_acres_keeps_reported_within_agreement() -> None:
    assert peri_scribe.areas.presented_area_in_acres(1100.0, 1110.0) == pytest.approx(
        1100.0,
    )


def test_presented_area_in_acres_keeps_reported_when_calculated_is_smaller() -> None:
    assert peri_scribe.areas.presented_area_in_acres(1100.0, 900.0) == pytest.approx(
        1100.0,
    )


def test_presented_area_in_acres_prefers_calculated_at_the_ratio_boundary() -> None:
    reported_in_acres = 200.0
    boundary_in_acres = (
        reported_in_acres * peri_scribe.areas.SIGNIFICANTLY_LARGER_AREA_RATIO
    )
    assert peri_scribe.areas.presented_area_in_acres(
        reported_in_acres,
        boundary_in_acres,
    ) == pytest.approx(boundary_in_acres)


def test_presented_area_in_acres_returns_none_without_reported_area() -> None:
    assert peri_scribe.areas.presented_area_in_acres(None, 2939.0) is None


def test_presented_area_in_acres_keeps_reported_without_calculated_area() -> None:
    assert peri_scribe.areas.presented_area_in_acres(1100.0, None) == pytest.approx(
        1100.0,
    )


def test_presented_area_in_acres_prefers_calculated_when_reported_is_zero() -> None:
    assert peri_scribe.areas.presented_area_in_acres(0.0, 2939.0) == pytest.approx(
        2939.0,
    )


def test_presented_area_in_acres_keeps_zero_when_calculated_is_zero() -> None:
    assert peri_scribe.areas.presented_area_in_acres(0.0, 0.0) == pytest.approx(0.0)
