"""Tests for peri_scribe.perimeters.size_filtering."""

from __future__ import annotations

import numpy as np
import pytest
import shapely.geometry

import peri_scribe.perimeters.size_filtering
import tests.factories


def test_geometry_area_returns_area_for_polygon() -> None:
    geometry = tests.factories.polygon((0, 0), (1, 0), (1, 1), (0, 0))
    area = peri_scribe.perimeters.size_filtering.geometry_area(geometry)
    assert area is not None
    assert area > 0


def test_geometry_area_returns_none_without_geometry() -> None:
    assert peri_scribe.perimeters.size_filtering.geometry_area(None) is None
    assert (
        peri_scribe.perimeters.size_filtering.geometry_area(shapely.geometry.Polygon())
        is None
    )


def test_computed_area_returns_first_positive_value() -> None:
    area = peri_scribe.perimeters.size_filtering.computed_area({
        "poly_Acres_AutoCalc": 123,
        "poly_GISAcres": 456,
        "area_acres": 789,
    })
    assert area is not None
    assert area.m_as("acres") == pytest.approx(123)


def test_computed_area_skips_missing_and_nonpositive() -> None:
    area = peri_scribe.perimeters.size_filtering.computed_area({
        "poly_Acres_AutoCalc": 0,
        "poly_GISAcres": None,
        "area_acres": 456,
    })
    assert area is not None
    assert area.m_as("acres") == pytest.approx(456)


def test_computed_area_returns_none_without_sizes() -> None:
    assert peri_scribe.perimeters.size_filtering.computed_area({}) is None


def test_incident_size_returns_first_positive_value() -> None:
    size = peri_scribe.perimeters.size_filtering.incident_size({
        "attr_IncidentSize": 100,
        "attr_FinalAcres": 200,
    })
    assert size is not None
    assert size.m_as("acres") == pytest.approx(100)


def test_incident_size_skips_missing_and_nonpositive() -> None:
    size = peri_scribe.perimeters.size_filtering.incident_size({
        "attr_IncidentSize": np.nan,
        "attr_FinalAcres": 200,
    })
    assert size is not None
    assert size.m_as("acres") == pytest.approx(200)


def test_incident_size_returns_none_without_sizes() -> None:
    assert peri_scribe.perimeters.size_filtering.incident_size({}) is None


def test_perimeter_is_implausibly_small_flags_collapsed_geometry() -> None:
    tiny = tests.factories.polygon((0, 0), (0.0001, 0), (0.0001, 0.0001), (0, 0))
    version = tests.factories.observation(
        geometry=tiny,
        attributes={"area_acres": 1_000},
    )
    assert peri_scribe.perimeters.size_filtering.perimeter_is_implausibly_small(version)


def test_perimeter_is_implausibly_small_flags_small_incident_size() -> None:
    tiny = tests.factories.polygon((0, 0), (0.0001, 0), (0.0001, 0.0001), (0, 0))
    version = tests.factories.observation(
        geometry=tiny,
        attributes={"attr_IncidentSize": 100_000},
    )
    assert peri_scribe.perimeters.size_filtering.perimeter_is_implausibly_small(version)


def test_perimeter_is_implausibly_small_keeps_matching_geometry() -> None:
    large = tests.factories.polygon((0, 0), (1, 0), (1, 1), (0, 0))
    version = tests.factories.observation(
        geometry=large,
        attributes={"area_acres": 3_000_000},
    )
    assert not peri_scribe.perimeters.size_filtering.perimeter_is_implausibly_small(
        version,
    )


def test_perimeter_is_implausibly_small_keeps_incident_running_ahead() -> None:
    medium = tests.factories.polygon((0, 0), (0.01, 0), (0.01, 0.01), (0, 0))
    version = tests.factories.observation(
        geometry=medium,
        attributes={"attr_IncidentSize": 4_000},
    )
    assert not peri_scribe.perimeters.size_filtering.perimeter_is_implausibly_small(
        version,
    )


def test_perimeter_is_implausibly_small_keeps_without_reported_size() -> None:
    tiny = tests.factories.polygon((0, 0), (0.0001, 0), (0.0001, 0.0001), (0, 0))
    version = tests.factories.observation(geometry=tiny, attributes={})
    assert not peri_scribe.perimeters.size_filtering.perimeter_is_implausibly_small(
        version,
    )


def test_perimeter_is_implausibly_small_keeps_without_geometry() -> None:
    version = tests.factories.observation(attributes={"area_acres": 1000})
    assert not peri_scribe.perimeters.size_filtering.perimeter_is_implausibly_small(
        version,
    )


def test_drop_implausibly_small_perimeters_drops_collapsed() -> None:
    tiny = tests.factories.polygon((0, 0), (0.0001, 0), (0.0001, 0.0001), (0, 0))
    large = tests.factories.polygon((0, 0), (1, 0), (1, 1), (0, 0))
    observations = [
        tests.factories.observation(
            geometry=large,
            attributes={"area_acres": 3_000_000},
        ),
        tests.factories.observation(geometry=tiny, attributes={"area_acres": 1_000}),
    ]
    survivors = peri_scribe.perimeters.size_filtering.drop_implausibly_small_perimeters(
        observations,
    )
    assert survivors == [observations[0]]
