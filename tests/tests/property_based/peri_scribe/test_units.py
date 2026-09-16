"""Tests for peri_scribe.units."""

import hypothesis
import pytest
import shapely.geometry

import peri_scribe.units
import tests.helpers.strategies.geometry


@hypothesis.given(geometry=tests.helpers.strategies.geometry.polygons())
def test_area_is_independent_of_ring_orientation(geometry: shapely.Polygon) -> None:
    reversed_shell = shapely.Polygon(
        list(geometry.exterior.coords)[::-1],
        geometry.interiors,
    )
    assert peri_scribe.units.area(reversed_shell).m_as("meters**2") == pytest.approx(
        peri_scribe.units.area(geometry).m_as("meters**2"),
        rel=1e-8,
        abs=0.001,
    )
