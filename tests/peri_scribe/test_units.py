"""Tests for peri_scribe.units."""

import pytest
import shapely.geometry

import peri_scribe.units


def square(side: float) -> shapely.geometry.Polygon:
    """Return a square of the given side, centered at the origin.

    Args:
        side: The length of each side.

    Returns:
        The square.
    """
    half = side / 2
    return shapely.geometry.box(-half, -half, half, half)


def test_area_in_acres_measures_geometry() -> None:
    larger = peri_scribe.units.area_in_acres(square(2.0))
    smaller = peri_scribe.units.area_in_acres(square(1.0))
    assert larger > smaller > 0.0


def test_area_in_acres_measures_geodesically_across_latitudes() -> None:
    equatorial = peri_scribe.units.area_in_acres(
        shapely.geometry.box(-0.5, -0.5, 0.5, 0.5),
    )
    northern = peri_scribe.units.area_in_acres(
        shapely.geometry.box(-0.5, 65.5, 0.5, 66.5),
    )
    assert equatorial == pytest.approx(3_041_678, rel=0.01)
    assert northern == pytest.approx(1_251_021, rel=0.01)
    assert northern < equatorial


def test_exterior_perimeter_in_miles_measures_geometry() -> None:
    larger = peri_scribe.units.exterior_perimeter_in_miles(square(2.0))
    smaller = peri_scribe.units.exterior_perimeter_in_miles(square(1.0))
    assert larger is not None
    assert smaller is not None
    assert larger > smaller > 0.0


def test_exterior_perimeter_in_miles_measures_geodesically_across_latitudes() -> None:
    equatorial = peri_scribe.units.exterior_perimeter_in_miles(
        shapely.geometry.box(-0.5, -0.5, 0.5, 0.5),
    )
    northern = peri_scribe.units.exterior_perimeter_in_miles(
        shapely.geometry.box(-0.5, 65.5, 0.5, 66.5),
    )
    assert equatorial == pytest.approx(275.75, rel=0.01)
    assert northern == pytest.approx(195.0, rel=0.01)
    assert equatorial is not None
    assert northern is not None
    assert northern < equatorial


def test_exterior_perimeter_in_miles_excludes_holes() -> None:
    outer = shapely.geometry.box(0.0, 0.0, 2.0, 2.0)
    hole = shapely.geometry.box(0.5, 0.5, 1.5, 1.5)
    with_hole = shapely.geometry.Polygon(outer.exterior, [hole.exterior])
    assert peri_scribe.units.exterior_perimeter_in_miles(
        with_hole,
    ) == peri_scribe.units.exterior_perimeter_in_miles(outer)


def test_exterior_perimeter_in_miles_sums_multipolygon_parts() -> None:
    multi = shapely.geometry.MultiPolygon(
        [
            shapely.geometry.box(0.0, 0.0, 1.0, 1.0),
            shapely.geometry.box(10.0, 0.0, 11.0, 1.0),
        ],
    )
    single = shapely.geometry.box(0.0, 0.0, 1.0, 1.0)
    single_perimeter = peri_scribe.units.exterior_perimeter_in_miles(single)
    assert single_perimeter is not None
    assert peri_scribe.units.exterior_perimeter_in_miles(
        multi,
    ) == pytest.approx(
        2.0 * single_perimeter,
        rel=1e-6,
    )


def test_exterior_perimeter_in_miles_returns_none_without_exterior() -> None:
    assert peri_scribe.units.exterior_perimeter_in_miles(None) is None
    assert (
        peri_scribe.units.exterior_perimeter_in_miles(
            shapely.geometry.Polygon(),
        )
        is None
    )
    assert (
        peri_scribe.units.exterior_perimeter_in_miles(
            shapely.geometry.Point(0.0, 0.0),
        )
        is None
    )
