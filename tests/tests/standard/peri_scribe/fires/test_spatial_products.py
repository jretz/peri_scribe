"""Exact spatial reuse must observe geometry, projection, and building-data changes."""

from __future__ import annotations

import os
import pathlib

import numpy as np
import pyproj
import pytest
import shapely

import peri_scribe.execution
import peri_scribe.fires.buffering
import peri_scribe.fires.reuse
import peri_scribe.fires.spatial_products
import spatial_data.point_store
import spatial_data.product_cache
import spatial_data.reference
import tests.helpers.doubles.errors
import tests.helpers.factories.spatial_data.point_store
from measurement_units import units


def test_buffered_geometries_reuses_exact_outputs_in_original_order(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    geometries = [
        shapely.box(-121, 40, -120.9, 40.1),
        None,
        shapely.Point(),
        shapely.Point(-110, 35),
    ]
    expected = peri_scribe.fires.buffering.buffered_fire_geometries(geometries)
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "runtime"):
        actual = peri_scribe.fires.spatial_products.buffered_geometries(geometries)
    monkeypatch.setattr(
        peri_scribe.fires.buffering,
        "buffered_fire_geometries",
        tests.helpers.doubles.errors.raising_stub(AssertionError("Repeated buffer")),
    )
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "runtime"):
        warm = peri_scribe.fires.spatial_products.buffered_geometries(geometries)
    assert list(shapely.to_wkb(actual)) == list(shapely.to_wkb(expected))
    assert list(shapely.to_wkb(warm)) == list(shapely.to_wkb(expected))


def test_buffered_geometries_preserves_inactive_and_unconditional_operation(
    tmp_path: pathlib.Path,
) -> None:
    geometries: list[shapely.Geometry | None] = [shapely.Point(-120, 40)]
    expected = peri_scribe.fires.spatial_products.buffered_geometries(geometries)
    with spatial_data.product_cache.scope(
        tmp_path / "products.sqlite",
        "runtime",
        unconditional=True,
    ):
        actual = peri_scribe.fires.spatial_products.buffered_geometries(geometries)
    assert list(shapely.to_wkb(actual)) == list(shapely.to_wkb(expected))


@pytest.mark.parametrize("change", ["geometry", "distance", "projection", "runtime"])
def test_buffered_geometries_invalidates_changed_inputs(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    geometries: list[shapely.Geometry | None] = [shapely.Point(-120, 40)]
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "runtime"):
        peri_scribe.fires.spatial_products.buffered_geometries(geometries)
    if change == "geometry":
        geometries = [shapely.Point(-121, 40)]
    elif change == "distance":
        monkeypatch.setattr(
            peri_scribe.fires.buffering,
            "BUILDING_BUFFER",
            2 * units.miles,
        )
    elif change == "projection":
        monkeypatch.setattr(
            spatial_data.reference,
            "WEB_MERCATOR_SPATIAL_REFERENCE",
            pyproj.CRS.from_epsg(3310),
        )
    expected = peri_scribe.fires.buffering.buffered_fire_geometries(geometries)
    with spatial_data.product_cache.scope(
        tmp_path / "products.sqlite",
        "changed" if change == "runtime" else "runtime",
    ):
        actual = peri_scribe.fires.spatial_products.buffered_geometries(geometries)
    assert list(shapely.to_wkb(actual)) == list(shapely.to_wkb(expected))


@pytest.mark.parametrize(
    "payload",
    [None, b"invalid", shapely.to_wkb(shapely.Point(1, 2))],
)
def test_read_buffer_rejects_missing_or_invalid_products(
    tmp_path: pathlib.Path,
    payload: bytes | None,
) -> None:
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "runtime"):
        if payload is not None:
            spatial_data.product_cache.put(
                peri_scribe.fires.spatial_products.BUFFER_NAMESPACE,
                "key",
                payload,
            )
        assert peri_scribe.fires.spatial_products.read_buffer("key") is None


def test_building_counts_reuses_strict_containment_with_duplicates_and_holes(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "buildings.sqlite"
    tests.helpers.factories.spatial_data.point_store.write_database(
        np.array([[1, 1], [1, 1], [0, 1], [2, 2], [4, 4]], dtype=float),
        path,
    )
    geometries = [
        None,
        shapely.Polygon(),
        shapely.Polygon(
            [(0, 0), (3, 0), (3, 3), (0, 3)],
            holes=[[(1.5, 1.5), (2.5, 1.5), (2.5, 2.5), (1.5, 2.5)]],
        ),
        shapely.box(3, 3, 5, 5),
    ]
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "runtime"):
        assert peri_scribe.fires.spatial_products.building_counts(geometries, path) == [
            0,
            0,
            2,
            1,
        ]
    monkeypatch.setattr(
        spatial_data.point_store,
        "point_counts_within",
        tests.helpers.doubles.errors.raising_stub(
            AssertionError("Repeated spatial query"),
        ),
    )
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "runtime"):
        assert peri_scribe.fires.spatial_products.building_counts(geometries, path) == [
            0,
            0,
            2,
            1,
        ]


def test_building_counts_requeries_only_changed_geometry(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "buildings.sqlite"
    tests.helpers.factories.spatial_data.point_store.write_database(
        np.array([[1, 1]]),
        path,
    )
    first = shapely.box(0, 0, 2, 2)
    other = shapely.box(2, 2, 3, 3)
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "runtime"):
        assert peri_scribe.fires.spatial_products.building_counts([first], path) == [1]
        queried: list[list[shapely.Geometry | None]] = []
        monkeypatch.setattr(
            spatial_data.point_store,
            "point_counts_within",
            lambda geometries, _path: queried.append(geometries) or [0],
        )
        assert peri_scribe.fires.spatial_products.building_counts(
            [first, other],
            path,
        ) == [1, 0]
    assert queried == [[other]]


def test_building_counts_invalidates_replaced_database_even_with_preserved_mtime(
    tmp_path: pathlib.Path,
) -> None:
    path = tmp_path / "buildings.sqlite"
    geometries = [shapely.box(0, 0, 2, 2)]
    tests.helpers.factories.spatial_data.point_store.write_database(
        np.array([[1, 1]]),
        path,
    )
    stamp = path.stat()
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "runtime"):
        assert peri_scribe.fires.spatial_products.building_counts(geometries, path) == [
            1,
        ]
    tests.helpers.factories.spatial_data.point_store.write_database(
        np.array([[1, 1], [1, 1]]),
        path,
    )
    os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "runtime"):
        assert peri_scribe.fires.spatial_products.building_counts(geometries, path) == [
            2,
        ]


def test_building_counts_missing_database_does_not_hide_new_dataset(
    tmp_path: pathlib.Path,
) -> None:
    path = tmp_path / "buildings.sqlite"
    geometries = [shapely.box(0, 0, 2, 2)]
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "runtime"):
        assert peri_scribe.fires.spatial_products.building_counts(geometries, path) == [
            0,
        ]
        tests.helpers.factories.spatial_data.point_store.write_database(
            np.array([[1, 1]]),
            path,
        )
        assert peri_scribe.fires.spatial_products.building_counts(geometries, path) == [
            1,
        ]


@pytest.mark.parametrize("mode", ["inactive", "wal", "unconditional"])
def test_building_counts_bypasses_cache_when_dataset_is_not_a_closed_snapshot(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    path = tmp_path / "buildings.sqlite"
    path.write_bytes(b"published database")
    if mode == "wal":
        path.with_name(f"{path.name}-wal").touch()
    monkeypatch.setattr(
        spatial_data.point_store,
        "point_counts_within",
        lambda _geometries, _path: [3],
    )
    if mode == "inactive":
        assert peri_scribe.fires.spatial_products.building_counts(
            [shapely.box(0, 0, 1, 1)],
            path,
        ) == [3]
    else:
        with spatial_data.product_cache.scope(
            tmp_path / "products.sqlite",
            "runtime",
            unconditional=mode == "unconditional",
        ):
            assert peri_scribe.fires.spatial_products.building_counts(
                [shapely.box(0, 0, 1, 1)],
                path,
            ) == [3]


@pytest.mark.parametrize("payload", [None, b"invalid", b"-1", b"01"])
def test_read_count_rejects_missing_or_invalid_products(
    tmp_path: pathlib.Path,
    payload: bytes | None,
) -> None:
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "runtime"):
        if payload is not None:
            spatial_data.product_cache.put(
                peri_scribe.fires.spatial_products.COUNT_NAMESPACE,
                "key",
                payload,
            )
        assert peri_scribe.fires.spatial_products.read_count("key") is None


def test_file_generation_shares_content_hash_only_within_owned_execution(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "buildings.sqlite"
    path.write_bytes(b"source bytes")
    with peri_scribe.execution.sharing():
        first = peri_scribe.fires.spatial_products.file_generation(path)
        monkeypatch.setattr(
            peri_scribe.fires.reuse,
            "file_digest",
            lambda _path: "changed",
        )
        assert peri_scribe.fires.spatial_products.file_generation(path) == first
    assert peri_scribe.fires.spatial_products.file_generation(path) != first


def test_buffered_geometries_computes_only_missing_positions_without_numeric_change(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = shapely.Point(-120, 40)
    other = shapely.box(-111, 36, -110.9, 36.1)
    geometries: list[shapely.Geometry | None] = [other, None, first]
    original = peri_scribe.fires.buffering.buffered_fire_geometries
    expected = original(geometries)
    queried: list[list[shapely.Geometry | None]] = []
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "runtime"):
        peri_scribe.fires.spatial_products.buffered_geometries([first])
        monkeypatch.setattr(
            peri_scribe.fires.buffering,
            "buffered_fire_geometries",
            lambda inputs: queried.append(inputs) or original(inputs),
        )
        actual = peri_scribe.fires.spatial_products.buffered_geometries(geometries)
    assert queried == [[other]]
    assert list(shapely.to_wkb(actual)) == list(shapely.to_wkb(expected))
