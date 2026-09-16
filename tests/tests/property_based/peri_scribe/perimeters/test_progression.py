"""Tests for peri_scribe.perimeters.progression."""

from __future__ import annotations

import hypothesis
import pytest
import shapely
import shapely.affinity

import peri_scribe.perimeters.progression
import peri_scribe.units
import tests.helpers.strategies.geometry


@hypothesis.given(
    geometries=tests.helpers.strategies.geometry.disjoint_coverage_sequences(),
)
def test_added_areas_count_each_disjoint_component_once(
    geometries: list[shapely.Polygon],
) -> None:
    additions = peri_scribe.perimeters.progression.added_areas(geometries)
    expected = sum(
        peri_scribe.units.area(geometry).m_as("meters**2")
        for geometry in set(geometries)
    )
    assert sum(area.m_as("meters**2") for area in additions) == pytest.approx(
        expected,
        abs=0.001,
    )


@hypothesis.given(
    geometries=tests.helpers.strategies.geometry.disjoint_coverage_sequences(),
)
def test_added_areas_ignore_repeated_coverage(
    geometries: list[shapely.Polygon],
) -> None:
    additions = peri_scribe.perimeters.progression.added_areas(
        [*geometries, *geometries],
    )
    assert [area.m_as("meters**2") for area in additions[len(geometries) :]] == (
        pytest.approx([0.0] * len(geometries), abs=0.001)
    )


@hypothesis.given(outer=tests.helpers.strategies.geometry.rectangles())
def test_added_areas_ignore_fully_contained_perimeters(outer: shapely.Polygon) -> None:
    inner = shapely.affinity.scale(outer, xfact=0.5, yfact=0.5)
    additions = peri_scribe.perimeters.progression.added_areas([outer, inner])
    assert additions[-1].m_as("meters**2") == pytest.approx(0, abs=0.001)
