"""Tests for peri_scribe.units."""

import pytest
import shapely.geometry

import peri_scribe.units
import tests.helpers.factories.geometry


def test_area_sums_parts_with_opposite_orientations() -> None:
    first = shapely.box(-100, 40, -99.99, 40.01)
    second = shapely.reverse(shapely.box(-100, 40.02, -99.99, 40.03))
    combined = shapely.MultiPolygon([first, second])
    expected = peri_scribe.units.area(first) + peri_scribe.units.area(second)
    assert peri_scribe.units.area(combined).m_as("meters**2") == pytest.approx(
        expected.m_as("meters**2"),
    )


def test_area_subtracts_holes_with_the_same_orientation_as_the_shell() -> None:
    outer = shapely.box(-100, 40, -99.9, 40.1)
    hole = shapely.box(-99.98, 40.02, -99.96, 40.04)
    polygon = shapely.Polygon(outer.exterior, [hole.exterior])
    expected = peri_scribe.units.area(outer) - peri_scribe.units.area(hole)
    assert peri_scribe.units.area(polygon).m_as("meters**2") == pytest.approx(
        expected.m_as("meters**2"),
    )


def test_area_measures_geometry() -> None:
    larger = peri_scribe.units.area(tests.helpers.factories.geometry.square(2.0))
    smaller = peri_scribe.units.area(tests.helpers.factories.geometry.square(1.0))
    assert larger > smaller > 0.0


def test_area_measures_geodesically_across_latitudes() -> None:
    equatorial = peri_scribe.units.area(shapely.geometry.box(-0.5, -0.5, 0.5, 0.5))
    northern = peri_scribe.units.area(shapely.geometry.box(-0.5, 65.5, 0.5, 66.5))
    assert equatorial.m_as("acres") == pytest.approx(3_041_678, rel=0.01)
    assert northern.m_as("acres") == pytest.approx(1_251_021, rel=0.01)
    assert northern < equatorial


def test_exterior_perimeter_measures_geometry() -> None:
    larger = peri_scribe.units.exterior_perimeter(
        tests.helpers.factories.geometry.square(2.0),
    )
    smaller = peri_scribe.units.exterior_perimeter(
        tests.helpers.factories.geometry.square(1.0),
    )
    assert larger is not None
    assert smaller is not None
    assert larger > smaller > 0.0


def test_exterior_perimeter_measures_geodesically_across_latitudes() -> None:
    equatorial = peri_scribe.units.exterior_perimeter(
        shapely.geometry.box(-0.5, -0.5, 0.5, 0.5),
    )
    northern = peri_scribe.units.exterior_perimeter(
        shapely.geometry.box(-0.5, 65.5, 0.5, 66.5),
    )
    assert equatorial is not None
    assert equatorial.m_as("miles") == pytest.approx(275.75, rel=0.01)
    assert northern is not None
    assert northern.m_as("miles") == pytest.approx(195.0, rel=0.01)
    assert equatorial is not None
    assert northern is not None
    assert northern < equatorial


def test_exterior_perimeter_excludes_holes() -> None:
    outer = shapely.geometry.box(0.0, 0.0, 2.0, 2.0)
    hole = shapely.geometry.box(0.5, 0.5, 1.5, 1.5)
    with_hole = shapely.geometry.Polygon(outer.exterior, [hole.exterior])
    assert peri_scribe.units.exterior_perimeter(
        with_hole,
    ) == peri_scribe.units.exterior_perimeter(outer)


def test_exterior_perimeter_sums_multipolygon_parts() -> None:
    multi = shapely.geometry.MultiPolygon([
        shapely.geometry.box(0.0, 0.0, 1.0, 1.0),
        shapely.geometry.box(10.0, 0.0, 11.0, 1.0),
    ])
    single = shapely.geometry.box(0.0, 0.0, 1.0, 1.0)
    single_perimeter = peri_scribe.units.exterior_perimeter(single)
    multi_perimeter = peri_scribe.units.exterior_perimeter(multi)
    assert single_perimeter is not None
    assert multi_perimeter is not None
    assert multi_perimeter.m_as("meters") == pytest.approx(
        2.0 * single_perimeter.m_as("meters"),
        rel=1e-6,
    )


def test_exterior_perimeter_returns_none_without_exterior() -> None:
    assert peri_scribe.units.exterior_perimeter(None) is None
    assert peri_scribe.units.exterior_perimeter(shapely.geometry.Polygon()) is None
    assert (
        peri_scribe.units.exterior_perimeter(shapely.geometry.Point(0.0, 0.0)) is None
    )
