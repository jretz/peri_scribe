"""Tests for peri_scribe.fires.buffering."""

from __future__ import annotations

import threading
import typing

import geopandas
import shapely.geometry

import peri_scribe.fires.buffering
import spatial_data.reference
import tests.helpers.doubles.peri_scribe.fires.buffering
import tests.helpers.factories.geometry


if typing.TYPE_CHECKING:
    import pytest


def test_union_geometry_returns_single_geometry_unchanged() -> None:
    geometry = tests.helpers.factories.geometry.square(1.0)
    result = peri_scribe.fires.buffering.union_geometry(
        geopandas.GeoSeries([geometry], crs="EPSG:4326"),
    )
    assert result is not None
    assert result.equals(geometry)


def test_union_geometry_unions_multiple_geometries() -> None:
    result = peri_scribe.fires.buffering.union_geometry(
        geopandas.GeoSeries(
            [
                tests.helpers.factories.geometry.square(1.0),
                shapely.geometry.box(2.0, 2.0, 3.0, 3.0),
            ],
            crs="EPSG:4326",
        ),
    )
    assert result is not None
    assert result.geom_type == "MultiPolygon"


def test_union_geometry_returns_none_for_all_empty() -> None:
    result = peri_scribe.fires.buffering.union_geometry(
        geopandas.GeoSeries([shapely.geometry.Polygon(), None], crs="EPSG:4326"),
    )
    assert result is None


def test_buffered_fire_geometries_buffers_each_geometry() -> None:
    buffered = peri_scribe.fires.buffering.buffered_fire_geometries([
        tests.helpers.factories.geometry.point(0, 0),
        None,
    ])
    assert buffered[0] is not None
    assert buffered[0].geom_type == "Polygon"
    assert buffered[0].contains(tests.helpers.factories.geometry.point(0, 0))
    assert buffered[1] is None


def test_buffered_fire_geometries_preserves_empty_and_missing_entries() -> None:
    assert peri_scribe.fires.buffering.buffered_fire_geometries([]) == []
    assert peri_scribe.fires.buffering.buffered_fire_geometries([None, None]) == [
        None,
        None,
    ]


def test_buffered_fire_geometries_preserves_order_with_parallel_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    geometries = [
        shapely.Point(-122, 38),
        None,
        shapely.box(-112, 35, -111.9, 35.1),
        shapely.LineString([(-100, 40), (-99.9, 40.1)]),
        None,
        shapely.Polygon([(-80, 30), (-79.9, 30), (-80, 30.1)]),
    ]
    monkeypatch.setattr(peri_scribe.fires.buffering, "buffer_worker_count", lambda: 1)
    expected = peri_scribe.fires.buffering.buffered_fire_geometries(geometries)
    metric = geopandas.GeoSeries(
        [geometry for geometry in geometries if geometry is not None],
        crs=spatial_data.reference.WGS84_SPATIAL_REFERENCE,
    ).to_crs(spatial_data.reference.WEB_MERCATOR_SPATIAL_REFERENCE)
    worker_count = 4
    workers = tests.helpers.doubles.peri_scribe.fires.buffering.BufferingWorkers(
        operation=peri_scribe.fires.buffering.buffer_geometry,
        positions={geometry.wkb: index for index, geometry in enumerate(metric)},
        barrier=threading.Barrier(worker_count),
    )
    monkeypatch.setattr(
        peri_scribe.fires.buffering,
        "buffer_worker_count",
        lambda: worker_count,
    )
    monkeypatch.setattr(peri_scribe.fires.buffering, "buffer_geometry", workers)
    tests.helpers.doubles.peri_scribe.fires.buffering.observe_submissions(
        workers,
        monkeypatch,
    )
    actual = peri_scribe.fires.buffering.buffered_fire_geometries(geometries)
    assert list(shapely.to_wkb(actual)) == list(shapely.to_wkb(expected))
    assert actual[1] is None
    assert actual[4] is None
    assert workers.completions.index(1) < workers.completions.index(0)
    assert sorted(workers.completions) == list(range(worker_count))
    assert workers.counts == {"active": 0, "peak": worker_count}
    assert len(workers.threads) == worker_count
    assert all(not thread.is_alive() for thread in workers.threads)
