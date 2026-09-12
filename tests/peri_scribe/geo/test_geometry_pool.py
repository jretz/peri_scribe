"""Tests for scoped snapshot geometry sharing."""

from __future__ import annotations

import concurrent.futures
import gc
import weakref

import pytest
import shapely

import peri_scribe.geo.geometry_pool


@pytest.mark.parametrize(
    "geometry",
    [shapely.Point(1, 2), shapely.Polygon(), shapely.box(0, 0, 1, 1)],
)
def test_geometry_pool_from_wkb_shares_identical_geometries(
    geometry: shapely.Geometry,
) -> None:
    pool = peri_scribe.geo.geometry_pool.GeometryPool()
    first = pool.from_wkb(geometry.wkb)
    second = pool.from_wkb(geometry.wkb)
    assert first is second


@pytest.mark.parametrize(
    ("first", "second"),
    [
        (shapely.Point(1, 2), shapely.Point(2, 1)),
        (shapely.Point(1, 2, 3), shapely.Point(1, 2, 4)),
        (shapely.Point(1, 2), shapely.Point(1, 2, 3)),
        (shapely.box(0, 0, 1, 1), shapely.reverse(shapely.box(0, 0, 1, 1))),
        (
            shapely.set_srid(shapely.Point(1, 2), 4326),
            shapely.Point(1, 2),
        ),
        (shapely.Point(), shapely.Polygon()),
    ],
)
def test_geometry_pool_from_wkb_preserves_geometry_on_digest_collision(
    first: shapely.Geometry,
    second: shapely.Geometry,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        peri_scribe.geo.geometry_pool,
        "geometry_digest",
        lambda _wkb: b"collision",
    )
    pool = peri_scribe.geo.geometry_pool.GeometryPool()
    first_wkb = shapely.to_wkb(first, include_srid=True)
    second_wkb = shapely.to_wkb(second, include_srid=True)
    first_shared = pool.from_wkb(first_wkb)
    second_shared = pool.from_wkb(second_wkb)
    assert first_shared is not second_shared
    assert shapely.to_wkb(first_shared, include_srid=True) == first_wkb
    assert shapely.to_wkb(second_shared, include_srid=True) == second_wkb
    assert pool.from_wkb(second_wkb) is second_shared


def test_geometry_pool_from_wkb_preserves_non_native_byte_order() -> None:
    geometry = shapely.Point(1, 2, 3)
    pool = peri_scribe.geo.geometry_pool.GeometryPool()
    decoded = pool.from_wkb(shapely.to_wkb(geometry, byte_order=0))
    assert decoded.wkb == geometry.wkb


def test_geometry_pool_from_wkb_shares_across_threads() -> None:
    pool = peri_scribe.geo.geometry_pool.GeometryPool()
    wkb = shapely.box(0, 0, 1, 1).wkb
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        geometries = list(executor.map(pool.from_wkb, [wkb] * 32))
    assert all(geometry is geometries[0] for geometry in geometries)


def test_geometry_pool_from_wkb_releases_geometries_with_pool() -> None:
    pool = peri_scribe.geo.geometry_pool.GeometryPool()
    geometry = pool.from_wkb(shapely.Point(1, 2).wkb)
    reference = weakref.ref(geometry)
    del geometry, pool
    gc.collect()
    assert reference() is None
