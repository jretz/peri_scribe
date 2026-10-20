"""Tests for peri_scribe.perimeters.progression."""

from __future__ import annotations

import datetime
import hashlib

import pytest
import shapely

import peri_scribe.perimeters.progression
import spatial_data.surface_measurements
import tests.helpers.factories.geometry
import tests.helpers.factories.peri_scribe.geo.growth_geometry
from measurement_units import units


def test_added_areas_preserves_growth_after_duplicate_ring() -> None:
    first = shapely.box(-100, 40, -99.99, 40.01)
    second = shapely.box(-100, 40.02, -99.99, 40.03)
    additions = peri_scribe.perimeters.progression.added_areas([first, first, second])
    assert additions[-1].m_as("meters**2") == pytest.approx(
        spatial_data.surface_measurements.area(second).m_as("meters**2"),
    )


def test_added_areas_does_not_invent_growth_when_a_part_is_revisited() -> None:
    first = shapely.box(-99.98, 40, -99.97, 40.01)
    second = shapely.box(-100, 40, -99.99, 40.01)
    additions = peri_scribe.perimeters.progression.added_areas(
        [first, first, second, first],
    )
    assert additions[-1].m_as("meters**2") == pytest.approx(0, abs=0.001)


def test_added_areas_ignores_lines_and_points_in_the_display_sequence() -> None:
    polygon = shapely.box(-100, 40, -99, 41)
    line = shapely.LineString([(-100, 40), (-99.5, 40), (-99, 40)])
    mixed = shapely.GeometryCollection([polygon, line, shapely.Point(-98, 40)])
    additions = peri_scribe.perimeters.progression.added_areas(
        [line, polygon, mixed, shapely.Point(-98, 40)],
    )
    assert additions[0].m_as("meters ** 2") == 0
    assert additions[1] == spatial_data.surface_measurements.area(polygon)
    assert additions[2].m_as("meters ** 2") == 0
    assert additions[3].m_as("meters ** 2") == 0


def test_added_areas_is_unchanged_when_edges_gain_collinear_vertices() -> None:
    polygon = shapely.box(-100, 40, -99, 41)
    segmented = shapely.segmentize(polygon, 0.5)
    additions = peri_scribe.perimeters.progression.added_areas([polygon, segmented])
    assert additions[1].m_as("meters ** 2") == 0


def test_sequence_digest_rejects_unversioned_geometry_only_measurements() -> None:
    polygon = shapely.box(-100, 40, -99, 41)
    content = shapely.to_wkb(polygon, include_srid=True)
    unversioned = hashlib.sha256(len(content).to_bytes(8) + content).hexdigest()
    assert peri_scribe.perimeters.progression.sequence_digest([polygon]) != unversioned


def test_added_areas_preserves_the_existing_0432_hole() -> None:
    left, right = (
        tests.helpers.factories.peri_scribe.geo.growth_geometry.hole_union_operands()
    )
    additions = peri_scribe.perimeters.progression.added_areas([left, right])
    assert 0 <= additions[1].m_as("meters ** 2") < 1


def test_ring_carries_its_geometry_time_and_area() -> None:
    observation_time = datetime.datetime(2026, 8, 5, 20, 30, tzinfo=datetime.UTC)
    ring = peri_scribe.perimeters.progression.Ring(
        geometry=tests.helpers.factories.geometry.square(1.0),
        observation_time=observation_time,
        area=42.5 * units.Unit("meters ** 2"),
    )
    assert ring.geometry == tests.helpers.factories.geometry.square(1.0)
    assert ring.observation_time == observation_time
    assert ring.area.m_as("meters ** 2") == pytest.approx(42.5)


def test_ring_defaults_to_zero_area() -> None:
    ring = peri_scribe.perimeters.progression.Ring(
        geometry=tests.helpers.factories.geometry.square(1.0),
        observation_time=None,
    )
    assert ring.area.m_as("meters ** 2") == pytest.approx(0.0)
