"""Tests for peri_scribe.areas."""

from __future__ import annotations

import pytest

import peri_scribe.areas
import peri_scribe.units
import tests.factories
from peri_scribe.units import units


def test_presented_area_prefers_calculated_when_significantly_larger() -> None:
    result = peri_scribe.areas.presented_area(
        1100.0 * units.acres,
        2939.0 * units.acres,
    )
    assert result is not None
    assert result.m_as("acres") == pytest.approx(2939.0)


def test_presented_area_keeps_reported_within_agreement() -> None:
    result = peri_scribe.areas.presented_area(
        1100.0 * units.acres,
        1110.0 * units.acres,
    )
    assert result is not None
    assert result.m_as("acres") == pytest.approx(1100.0)


def test_presented_area_keeps_reported_when_calculated_is_smaller() -> None:
    result = peri_scribe.areas.presented_area(
        1100.0 * units.acres,
        900.0 * units.acres,
    )
    assert result is not None
    assert result.m_as("acres") == pytest.approx(1100.0)


def test_presented_area_prefers_calculated_at_the_ratio_boundary() -> None:
    reported = 200.0 * units.acres
    boundary = reported * peri_scribe.areas.SIGNIFICANTLY_LARGER_AREA_RATIO
    result = peri_scribe.areas.presented_area(reported, boundary)
    assert result is not None
    assert result.m_as("acres") == pytest.approx(
        boundary.m_as("acres"),
    )


def test_presented_area_returns_none_without_reported_area() -> None:
    assert peri_scribe.areas.presented_area(None, 2939.0 * units.acres) is None


def test_presented_area_keeps_reported_without_calculated_area() -> None:
    result = peri_scribe.areas.presented_area(
        1100.0 * units.acres,
        None,
    )
    assert result is not None
    assert result.m_as("acres") == pytest.approx(1100.0)


def test_presented_area_prefers_calculated_when_reported_is_zero() -> None:
    result = peri_scribe.areas.presented_area(
        0.0 * units.acres,
        2939.0 * units.acres,
    )
    assert result is not None
    assert result.m_as("acres") == pytest.approx(2939.0)


def test_presented_area_keeps_zero_when_calculated_is_zero() -> None:
    result = peri_scribe.areas.presented_area(
        0.0 * units.acres,
        0.0 * units.acres,
    )
    assert result is not None
    assert result.m_as("acres") == pytest.approx(0.0)


def test_presented_area_for_latest_uses_perimeter_reported_area() -> None:
    perimeter_row = tests.factories.geo_frame(
        {"area_acres": [1100.0]},
        [tests.factories.square(0.01)],
    ).iloc[0]
    result = peri_scribe.areas.presented_area_for_latest(perimeter_row, None)
    assert result is not None
    assert result.m_as("acres") == pytest.approx(1100.0)


def test_presented_area_for_latest_prefers_measured_area() -> None:
    geometry = tests.factories.square(0.02)
    perimeter_row = tests.factories.geo_frame(
        {"area_acres": [100.0]},
        [geometry],
    ).iloc[0]
    result = peri_scribe.areas.presented_area_for_latest(perimeter_row, None)
    assert result is not None
    assert result.m_as("acres") == pytest.approx(
        peri_scribe.units.area(geometry).m_as("acres"),
    )


def test_presented_area_for_latest_falls_back_to_point_size() -> None:
    point_row = tests.factories.geo_frame(
        {"incident_size": [500.0]},
        [tests.factories.point(0, 0)],
    ).iloc[0]
    result = peri_scribe.areas.presented_area_for_latest(None, point_row)
    assert result is not None
    assert result.m_as("acres") == pytest.approx(500.0)


def test_presented_area_for_latest_returns_none_without_area() -> None:
    perimeter_row = tests.factories.geo_frame(
        {"area_acres": [None]},
        [tests.factories.square(0.01)],
    ).iloc[0]
    point_row = tests.factories.geo_frame(
        {"fire_name": ["Smoke"]},
        [tests.factories.point(0, 0)],
    ).iloc[0]
    assert peri_scribe.areas.presented_area_for_latest(perimeter_row, point_row) is None
