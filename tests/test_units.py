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
