"""Tests for peri_scribe.geo.geometry."""

from __future__ import annotations

import shapely.geometry

import peri_scribe.geo.geometry


def test_polygonal_parts_flattens_multipolygon() -> None:
    first = shapely.geometry.box(0.0, 0.0, 1.0, 1.0)
    second = shapely.geometry.box(2.0, 2.0, 3.0, 3.0)
    parts = peri_scribe.geo.geometry.polygonal_parts(
        shapely.geometry.MultiPolygon([first, second]),
    )
    assert parts == [first, second]


def test_polygonal_parts_flattens_nested_multipolygon() -> None:
    first = shapely.geometry.box(0.0, 0.0, 1.0, 1.0)
    second = shapely.geometry.box(2.0, 2.0, 3.0, 3.0)
    collection = shapely.geometry.GeometryCollection(
        [shapely.geometry.MultiPolygon([first, second])],
    )
    parts = peri_scribe.geo.geometry.polygonal_parts(collection)
    assert parts == [first, second]


def test_polygonal_parts_skips_empty_members() -> None:
    box = shapely.geometry.box(0.0, 0.0, 1.0, 1.0)
    collection = shapely.geometry.GeometryCollection(
        [shapely.geometry.Polygon(), box],
    )
    parts = peri_scribe.geo.geometry.polygonal_parts(collection)
    assert parts == [box]


def test_polygonal_parts_ignores_non_polygonal_members() -> None:
    box = shapely.geometry.box(0.0, 0.0, 1.0, 1.0)
    collection = shapely.geometry.GeometryCollection(
        [box, shapely.geometry.Point(5.0, 5.0)],
    )
    parts = peri_scribe.geo.geometry.polygonal_parts(collection)
    assert parts == [box]


def test_polygonal_parts_returns_empty_for_line() -> None:
    line = shapely.geometry.LineString([(0.0, 0.0), (1.0, 1.0)])
    assert peri_scribe.geo.geometry.polygonal_parts(line) == []
