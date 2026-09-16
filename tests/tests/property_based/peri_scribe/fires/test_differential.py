"""Tests for peri_scribe.fires.differential."""

import hypothesis
import hypothesis.strategies
import pytest
import shapely.geometry

import peri_scribe.fires.differential
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
    for index, corrected in enumerate(actual):
        expected = shapely.intersection_all(geometries[index:])
        if expected.area == 0:
            assert corrected is None
        else:
            assert corrected is not None
            assert corrected.symmetric_difference(expected).area == pytest.approx(
                0,
                abs=1e-12,
            )
