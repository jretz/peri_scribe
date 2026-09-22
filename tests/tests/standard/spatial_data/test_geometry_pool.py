"""Tests for scoped snapshot geometry sharing."""

from __future__ import annotations

import concurrent.futures
import gc
import weakref

import pytest
import shapely

import spatial_data.geometry_pool


def test_geometry_pool_from_wkb_handles_digest_sorted_observations() -> None:
    serialized = sorted(
        (shapely.Point(index, index).wkb for index in range(1200)),
        key=spatial_data.geometry_pool.geometry_digest,
    )
    pool = spatial_data.geometry_pool.GeometryPool()
    geometries = [pool.from_wkb(wkb) for wkb in serialized]
    assert all(
        pool.from_wkb(wkb) is geometry
        for wkb, geometry in zip(serialized, geometries, strict=True)
    )


@pytest.mark.parametrize("digest", [b"a", b"m", b"z"])
def test_shared_geometry_preserves_prior_snapshot(digest: bytes) -> None:
    original, first = spatial_data.geometry_pool.shared_geometry(
        None,
        b"m",
        shapely.Point(1, 2).wkb,
    )
    updated, second = spatial_data.geometry_pool.shared_geometry(
        original,
        digest,
        shapely.Point(3, 4).wkb,
    )
    assert original.geometries == (first,)
    assert original.smaller is None
    assert original.larger is None
    assert second.wkb == shapely.Point(3, 4).wkb
    assert updated is not original


@pytest.mark.parametrize("digest", [b"a", b"m", b"z"])
def test_shared_geometry_reuses_unchanged_snapshot(digest: bytes) -> None:
    original, _first = spatial_data.geometry_pool.shared_geometry(
        None,
        b"m",
        shapely.Point(1, 2).wkb,
    )
    cached, geometry = spatial_data.geometry_pool.shared_geometry(
        original,
        digest,
        shapely.Point(3, 4).wkb,
    )
    reused, same_geometry = spatial_data.geometry_pool.shared_geometry(
        cached,
        digest,
        shapely.Point(3, 4).wkb,
    )
    assert reused is cached
    assert same_geometry is geometry


@pytest.mark.parametrize(
    "geometry",
    [shapely.Point(1, 2), shapely.Polygon(), shapely.box(0, 0, 1, 1)],
)
def test_geometry_pool_from_wkb_shares_identical_geometries(
    geometry: shapely.Geometry,
) -> None:
    pool = spatial_data.geometry_pool.GeometryPool()
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
        (shapely.set_srid(shapely.Point(1, 2), 4326), shapely.Point(1, 2)),
        (shapely.Point(), shapely.Polygon()),
    ],
)
def test_geometry_pool_from_wkb_preserves_geometry_on_digest_collision(
    first: shapely.Geometry,
    second: shapely.Geometry,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        spatial_data.geometry_pool,
        "geometry_digest",
        lambda _wkb: b"collision",
    )
    pool = spatial_data.geometry_pool.GeometryPool()
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
    pool = spatial_data.geometry_pool.GeometryPool()
    decoded = pool.from_wkb(shapely.to_wkb(geometry, byte_order=0))
    assert decoded.wkb == geometry.wkb


def test_geometry_pool_from_wkb_shares_across_threads() -> None:
    pool = spatial_data.geometry_pool.GeometryPool()
    wkb = shapely.box(0, 0, 1, 1).wkb
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        geometries = list(executor.map(pool.from_wkb, [wkb] * 32))
    assert all(geometry is geometries[0] for geometry in geometries)


def test_geometry_pool_from_wkb_releases_geometries_with_pool() -> None:
    pool = spatial_data.geometry_pool.GeometryPool()
    geometry = pool.from_wkb(shapely.Point(1, 2).wkb)
    reference = weakref.ref(geometry)
    del geometry, pool
    gc.collect()
    assert reference() is None
