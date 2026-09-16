"""Tests for peri_scribe.perimeters.progression."""

from __future__ import annotations

import datetime

import hypothesis
import pytest
import shapely
import shapely.affinity

import peri_scribe.perimeters.progression
import peri_scribe.units
import tests.factories
import tests.geometry_strategies
from peri_scribe.units import units


def test_added_areas_preserves_growth_after_duplicate_ring() -> None:
    first = shapely.box(-100, 40, -99.99, 40.01)
    second = shapely.box(-100, 40.02, -99.99, 40.03)
    additions = peri_scribe.perimeters.progression.added_areas([first, first, second])
    assert additions[-1].m_as("meters**2") == pytest.approx(
        peri_scribe.units.area(second).m_as("meters**2"),
    )


def test_added_areas_does_not_invent_growth_when_a_part_is_revisited() -> None:
    first = shapely.box(-99.98, 40, -99.97, 40.01)
    second = shapely.box(-100, 40, -99.99, 40.01)
    additions = peri_scribe.perimeters.progression.added_areas(
        [first, first, second, first],
    )
    assert additions[-1].m_as("meters**2") == pytest.approx(0, abs=0.001)


@hypothesis.given(
    geometries=tests.geometry_strategies.disjoint_coverage_sequences(),
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
    geometries=tests.geometry_strategies.disjoint_coverage_sequences(),
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


@hypothesis.given(outer=tests.geometry_strategies.rectangles())
def test_added_areas_ignore_fully_contained_perimeters(outer: shapely.Polygon) -> None:
    inner = shapely.affinity.scale(outer, xfact=0.5, yfact=0.5)
    additions = peri_scribe.perimeters.progression.added_areas([outer, inner])
    assert additions[-1].m_as("meters**2") == pytest.approx(0, abs=0.001)


def test_ring_carries_its_geometry_time_and_area() -> None:
    observation_time = datetime.datetime(2026, 8, 5, 20, 30, tzinfo=datetime.UTC)
    ring = peri_scribe.perimeters.progression.Ring(
        geometry=tests.factories.square(1.0),
        observation_time=observation_time,
        area=42.5 * units.meters**2,
    )
    assert ring.geometry == tests.factories.square(1.0)
    assert ring.observation_time == observation_time
    assert ring.area.m_as("meters ** 2") == pytest.approx(42.5)


def test_ring_defaults_to_zero_area() -> None:
    ring = peri_scribe.perimeters.progression.Ring(
        geometry=tests.factories.square(1.0),
        observation_time=None,
    )
    assert ring.area.m_as("meters ** 2") == pytest.approx(0.0)
