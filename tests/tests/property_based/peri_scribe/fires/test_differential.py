"""Tests for peri_scribe.fires.differential."""

import hypothesis
import hypothesis.strategies
import shapely.geometry

import peri_scribe.fires.differential
import peri_scribe.geo.growth_geometry
import tests.helpers.strategies.geometry


@hypothesis.given(
    geometries=hypothesis.strategies.lists(
        tests.helpers.strategies.geometry.rectangles(),
        min_size=1,
        max_size=8,
    ),
)
def test_corrected_geometries_match_all_later_intersections(
    geometries: list[shapely.Polygon],
) -> None:
    actual = peri_scribe.fires.differential.corrected_geometries(geometries)
    assert len(actual) == len(geometries)
    grid = peri_scribe.geo.growth_geometry.GRID_SIZE.m_as("degrees")
    bounds = [
        tuple(round(value / grid) * grid for value in geometry.bounds)
        for geometry in geometries
    ]
    for index, corrected in enumerate(actual):
        left = max(bound[0] for bound in bounds[index:])
        bottom = max(bound[1] for bound in bounds[index:])
        right = min(bound[2] for bound in bounds[index:])
        top = min(bound[3] for bound in bounds[index:])
        if left >= right or bottom >= top:
            assert corrected is None
        else:
            assert corrected is not None
            assert corrected.equals(shapely.box(left, bottom, right, top))
