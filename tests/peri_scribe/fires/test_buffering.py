"""Tests for peri_scribe.fires.scores."""

from __future__ import annotations

import geopandas
import shapely.geometry

import peri_scribe.fires.buffering
import tests.peri_scribe.fires.fire_helpers


def test_union_geometry_returns_single_geometry_unchanged() -> None:
    geometry = tests.peri_scribe.fires.fire_helpers.square(1.0)
    result = peri_scribe.fires.buffering.union_geometry(
        geopandas.GeoSeries([geometry], crs="EPSG:4326"),
    )
    assert result is not None
    assert result.equals(geometry)


def test_union_geometry_unions_multiple_geometries() -> None:
    result = peri_scribe.fires.buffering.union_geometry(
        geopandas.GeoSeries(
            [
                tests.peri_scribe.fires.fire_helpers.square(1.0),
                shapely.geometry.box(2.0, 2.0, 3.0, 3.0),
            ],
            crs="EPSG:4326",
        ),
    )
    assert result is not None
    assert result.geom_type == "MultiPolygon"


def test_union_geometry_returns_none_for_all_empty() -> None:
    result = peri_scribe.fires.buffering.union_geometry(
        geopandas.GeoSeries(
            [shapely.geometry.Polygon(), None],
            crs="EPSG:4326",
        ),
    )
    assert result is None


def test_buffered_fire_geometries_buffers_each_geometry() -> None:
    buffered = peri_scribe.fires.buffering.buffered_fire_geometries(
        [tests.peri_scribe.fires.fire_helpers.point(0, 0), None],
    )
    assert buffered[0] is not None
    assert buffered[0].geom_type == "Polygon"
    assert buffered[0].contains(tests.peri_scribe.fires.fire_helpers.point(0, 0))
    assert buffered[1] is None


def test_buffered_fire_geometries_returns_none_for_no_geometry() -> None:
    assert peri_scribe.fires.buffering.buffered_fire_geometries([]) == []
    assert peri_scribe.fires.buffering.buffered_fire_geometries([None, None]) == [
        None,
        None,
    ]
