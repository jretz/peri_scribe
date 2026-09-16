"""Persisted measurements and standalone geometry produce the same values."""

import pytest
import shapely

import peri_scribe.geo.measurements
import peri_scribe.units


@pytest.mark.parametrize("stored", [None, float("nan"), "missing"])
def test_area_measures_without_a_stored_number(stored: object) -> None:
    geometry = shapely.box(0, 0, 1, 1)
    assert peri_scribe.geo.measurements.area(
        geometry,
        stored,
    ) == peri_scribe.units.area(geometry)


def test_area_uses_a_persisted_measurement() -> None:
    expected = 123.0
    assert (
        peri_scribe.geo.measurements.area(shapely.Point(0, 0), expected).m_as(
            "meters ** 2",
        )
        == expected
    )


def test_exterior_perimeter_uses_a_persisted_measurement() -> None:
    result = peri_scribe.geo.measurements.exterior_perimeter(None, 123.0)
    assert result is not None
    expected = 123.0
    assert result.m_as("meters") == expected


def test_exterior_perimeter_handles_missing_geometry() -> None:
    assert peri_scribe.geo.measurements.exterior_perimeter(None) is None
