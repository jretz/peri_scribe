"""Exact compact geometry keys preserve grouping equality and owner lifetime."""

from __future__ import annotations

import concurrent.futures
import gc
import typing
import unittest.mock
import weakref

import shapely

import spatial_data.geometry_pool


if typing.TYPE_CHECKING:
    import pytest


def test_geometry_keys_key_reuses_serialization_for_retained_object() -> None:
    geometry = shapely.box(0, 0, 1, 1)
    keys = spatial_data.geometry_pool.GeometryKeys()
    with unittest.mock.patch.object(shapely, "to_wkb", wraps=shapely.to_wkb) as encode:
        first = keys.key(geometry)
        assert all(keys.key(geometry) == first for _ in range(20))
    assert encode.call_count == 1


def test_geometry_keys_key_matches_exact_encoding_despite_digest_collisions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        spatial_data.geometry_pool,
        "geometry_digest",
        lambda _encoded: bytes(32),
    )
    geometries = (
        shapely.Point(1, 2),
        shapely.Point(1, 2, 3),
        shapely.set_srid(shapely.Point(1, 2), 4326),
        shapely.set_srid(shapely.Point(1, 2), 3857),
        shapely.LineString([(1, 2), (3, 4)]),
    )
    registry = spatial_data.geometry_pool.GeometryKeys()
    keys = [registry.key(geometry) for geometry in geometries]
    for left, first in enumerate(geometries):
        for right, second in enumerate(geometries):
            assert (keys[left] == keys[right]) == (first.wkb == second.wkb)


def test_geometry_keys_key_shares_concurrent_exact_classes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        spatial_data.geometry_pool,
        "geometry_digest",
        lambda _encoded: bytes(32),
    )
    class_count = 4
    geometries = [
        shapely.Point(index % class_count, index % class_count) for index in range(80)
    ]
    registry = spatial_data.geometry_pool.GeometryKeys()
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        keys = list(executor.map(registry.key, geometries))
    for offset in range(class_count):
        assert len(set(keys[offset::class_count])) == 1
    assert len(set(keys)) == class_count


def test_geometry_keys_key_releases_geometries_with_owner() -> None:
    registry = spatial_data.geometry_pool.GeometryKeys()
    geometry = shapely.Point(1, 2)
    reference = weakref.ref(geometry)
    registry.key(geometry)
    del geometry
    gc.collect()
    assert reference() is not None
    del registry
    gc.collect()
    assert reference() is None
