"""Tests for spatial_data.measurements."""

import hypothesis
import pyproj
import pytest
import shapely.geometry

import spatial_data.measurements
import tests.helpers.strategies.geometry


@hypothesis.given(geometry=tests.helpers.strategies.geometry.polygons())
def test_area_matches_geodesic_calculator_exactly(geometry: shapely.Polygon) -> None:
    measured_area, _perimeter = pyproj.Geod(ellps="WGS84").geometry_area_perimeter(
        shapely.orient_polygons(geometry),
    )
    actual = spatial_data.measurements.area(geometry).m_as("meters**2")
    assert float(actual).hex() == float(abs(measured_area)).hex()


@hypothesis.given(geometry=tests.helpers.strategies.geometry.polygons())
def test_area_is_independent_of_ring_orientation(geometry: shapely.Polygon) -> None:
    reversed_shell = shapely.Polygon(
        list(geometry.exterior.coords)[::-1],
        geometry.interiors,
    )
    assert spatial_data.measurements.area(reversed_shell).m_as(
        "meters**2",
    ) == pytest.approx(
        spatial_data.measurements.area(geometry).m_as("meters**2"),
        rel=1e-8,
        abs=0.001,
    )
