"""Tests for peri_scribe.geo.geometry."""

from __future__ import annotations

import hypothesis
import numpy as np
import pyproj
import shapely.geometry

import peri_scribe.geo.geometry
import tests.geometry_strategies


@hypothesis.given(case=tests.geometry_strategies.nested_collections())
def test_polygonal_parts_preserves_polygons_through_nested_collections(
    case: tuple[shapely.Geometry, list[shapely.Polygon]],
) -> None:
    geometry, expected = case
    assert peri_scribe.geo.geometry.polygonal_parts(geometry) == expected


def test_polygonal_parts_keeps_polygon_inside_nested_collection() -> None:
    polygon = shapely.Polygon([(0, 0), (0, 1), (1, 0)])
    collection = shapely.GeometryCollection([
        shapely.GeometryCollection([polygon]),
    ])
    assert peri_scribe.geo.geometry.polygonal_parts(collection) == [polygon]


@hypothesis.given(geometry=tests.geometry_strategies.footprints())
def test_transform_coordinates_round_trips_projection(
    geometry: shapely.Polygon | shapely.MultiPolygon,
) -> None:
    projected = peri_scribe.geo.geometry.transform_coordinates(
        geometry,
        pyproj.Transformer.from_crs(4326, 3857, always_xy=True),
    )
    restored = peri_scribe.geo.geometry.transform_coordinates(
        projected,
        pyproj.Transformer.from_crs(3857, 4326, always_xy=True),
    )
    np.testing.assert_allclose(
        shapely.get_coordinates(restored),
        shapely.get_coordinates(geometry),
        rtol=0,
        atol=1e-10,
    )


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
    collection = shapely.geometry.GeometryCollection([
        shapely.geometry.MultiPolygon([first, second]),
    ])
    parts = peri_scribe.geo.geometry.polygonal_parts(collection)
    assert parts == [first, second]


def test_polygonal_parts_skips_empty_members() -> None:
    box = shapely.geometry.box(0.0, 0.0, 1.0, 1.0)
    collection = shapely.geometry.GeometryCollection([shapely.geometry.Polygon(), box])
    parts = peri_scribe.geo.geometry.polygonal_parts(collection)
    assert parts == [box]


def test_polygonal_parts_ignores_non_polygonal_members() -> None:
    box = shapely.geometry.box(0.0, 0.0, 1.0, 1.0)
    collection = shapely.geometry.GeometryCollection([
        box,
        shapely.geometry.Point(5.0, 5.0),
    ])
    parts = peri_scribe.geo.geometry.polygonal_parts(collection)
    assert parts == [box]


def test_polygonal_parts_returns_empty_for_line() -> None:
    line = shapely.geometry.LineString([(0.0, 0.0), (1.0, 1.0)])
    assert peri_scribe.geo.geometry.polygonal_parts(line) == []
