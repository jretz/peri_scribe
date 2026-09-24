"""Indexed histories retain exact published values and recover from missing products."""

from __future__ import annotations

import contextlib
import pathlib

import pandas as pd
import pytest

import peri_scribe.fires.reuse
import spatial_data.cache_values
import spatial_data.layers
import spatial_data.product_cache
import spatial_data.row_index
import tests.helpers.doubles.errors


@pytest.mark.parametrize(
    "keys",
    [frozenset({"first"}), frozenset({"second"})],
)
def test_read_rows_index_reuses_exact_normalized_requested_histories(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    cached_layers: list[spatial_data.layers.LayerData],
    keys: frozenset[str],
) -> None:
    path = tmp_path / "history.gpkg"
    cached_layers[0].dataframe["observed"] = pd.to_datetime(
        ["2026-09-23T01:02:03.456Z", None],
    )
    cached_layers[0].dataframe["optional"] = [None, 2.5]
    peri_scribe.fires.reuse.write_layers(path, cached_layers)
    normalized = spatial_data.layers.read_layer(path, "perimeters")
    expected = {
        key: rows
        for key, rows in spatial_data.row_index.grouped_rows(normalized).items()
        if key in keys
    }
    database = tmp_path / "products.sqlite"
    with spatial_data.product_cache.scope(database, "test"):
        cold = peri_scribe.fires.reuse.read_rows(path, ("perimeters",), keys=keys)
    monkeypatch.setattr(
        spatial_data.layers,
        "read_layer",
        tests.helpers.doubles.errors.raising_stub(AssertionError("Repeated GDAL read")),
    )
    with spatial_data.product_cache.scope(database, "test"):
        warm = peri_scribe.fires.reuse.read_rows(path, ("perimeters",), keys=keys)

    expected_bytes = spatial_data.cache_values.dumps({"perimeters": expected})
    assert spatial_data.cache_values.dumps(cold) == expected_bytes
    assert spatial_data.cache_values.dumps(warm) == expected_bytes


@pytest.mark.parametrize("damage", ["manifest", "payload", "missing_payload"])
def test_read_rows_index_recovers_and_repairs_corrupt_products(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    cached_layers: list[spatial_data.layers.LayerData],
    damage: str,
) -> None:
    path = tmp_path / "history.gpkg"
    peri_scribe.fires.reuse.write_layers(path, cached_layers)
    database = tmp_path / "products.sqlite"
    with spatial_data.product_cache.scope(database, "test"):
        expected = peri_scribe.fires.reuse.read_rows(
            path,
            ("perimeters",),
            keys={"first"},
        )
        manifest_namespace, payload_namespace = spatial_data.row_index.namespaces(
            path,
            "perimeters",
        )
        if damage == "manifest":
            spatial_data.product_cache.put(manifest_namespace, "current", b"invalid")
        elif damage == "payload":
            payload = spatial_data.product_cache.get(manifest_namespace, "current")
            assert payload is not None
            manifest = spatial_data.row_index.read_manifest(payload)
            spatial_data.product_cache.put(
                payload_namespace,
                manifest.entries[0][1],
                b"invalid",
            )
        else:
            spatial_data.product_cache.prune(payload_namespace, set())

        assert (
            peri_scribe.fires.reuse.read_rows(
                path,
                ("perimeters",),
                keys={"first"},
            )
            == expected
        )
    monkeypatch.setattr(
        spatial_data.layers,
        "read_layer",
        tests.helpers.doubles.errors.raising_stub(AssertionError("Unrepaired index")),
    )
    with spatial_data.product_cache.scope(database, "test"):
        assert (
            peri_scribe.fires.reuse.read_rows(
                path,
                ("perimeters",),
                keys={"first"},
            )
            == expected
        )


def test_read_rows_index_does_not_authenticate_modified_published_output(
    tmp_path: pathlib.Path,
    cached_layers: list[spatial_data.layers.LayerData],
) -> None:
    path = tmp_path / "history.gpkg"
    peri_scribe.fires.reuse.write_layers(path, cached_layers)
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "test"):
        assert peri_scribe.fires.reuse.read_rows(path, ("perimeters",), keys={"first"})
        path.write_bytes(b"partial replacement")
        assert (
            peri_scribe.fires.reuse.read_rows(
                path,
                ("perimeters",),
                keys={"first"},
            )
            == {}
        )


@pytest.mark.parametrize("keys", [frozenset(), frozenset({"unknown"})])
def test_read_rows_without_requested_matches_avoids_building_obsolete_index(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    cached_layers: list[spatial_data.layers.LayerData],
    keys: frozenset[str],
) -> None:
    path = tmp_path / "history.gpkg"
    peri_scribe.fires.reuse.write_layers(path, cached_layers)
    monkeypatch.setattr(
        spatial_data.product_cache,
        "put",
        tests.helpers.doubles.errors.raising_stub(
            AssertionError("Unneeded row products"),
        ),
    )
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "test"):
        assert peri_scribe.fires.reuse.read_rows(
            path,
            ("perimeters",),
            keys=keys,
        ) == {"perimeters": {}}


@pytest.mark.parametrize("selection", ["implicit_all", "explicit_all"])
@pytest.mark.parametrize("indexed", [False, True])
def test_read_rows_dense_requests_read_bulk_without_index_writes(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    cached_layers: list[spatial_data.layers.LayerData],
    selection: str,
    *,
    indexed: bool,
) -> None:
    path = tmp_path / "history.gpkg"
    frame = cached_layers[0].dataframe.iloc[[0] * 256].reset_index(drop=True)
    frame["derivation_key"] = [f"fire-{index}" for index in range(len(frame))]
    frame["revision"] = range(len(frame))
    cached_layers[0] = spatial_data.layers.LayerData(name="perimeters", dataframe=frame)
    peri_scribe.fires.reuse.write_layers(path, cached_layers)
    expected = spatial_data.row_index.grouped_rows(
        spatial_data.layers.read_layer(path, "perimeters"),
    )
    keys = None if selection == "implicit_all" else set(expected)
    database = tmp_path / "products.sqlite"
    if indexed:
        with spatial_data.product_cache.scope(database, "test"):
            peri_scribe.fires.reuse.read_rows(
                path,
                ("perimeters",),
                keys={"fire-0"},
            )
    monkeypatch.setattr(
        spatial_data.row_index,
        "read_payload",
        tests.helpers.doubles.errors.raising_stub(
            AssertionError("Dense payload decode"),
        ),
    )
    monkeypatch.setattr(
        spatial_data.product_cache,
        "put",
        tests.helpers.doubles.errors.raising_stub(AssertionError("Dense index write")),
    )
    with spatial_data.product_cache.scope(database, "test"):
        assert peri_scribe.fires.reuse.read_rows(
            path,
            ("perimeters",),
            keys=keys,
        ) == {"perimeters": expected}


def test_read_rows_index_replaces_generation_and_promoted_scalar_types(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    cached_layers: list[spatial_data.layers.LayerData],
) -> None:
    path = tmp_path / "history.gpkg"
    peri_scribe.fires.reuse.write_layers(path, cached_layers)
    database = tmp_path / "products.sqlite"
    with spatial_data.product_cache.scope(database, "test"):
        first = peri_scribe.fires.reuse.read_rows(path, ("perimeters",), keys={"first"})
    updated_revision = 3
    cached_layers[0].dataframe["revision"] = [updated_revision, None]
    peri_scribe.fires.reuse.write_layers(path, cached_layers)
    normalized = spatial_data.layers.read_layer(path, "perimeters")
    expected = spatial_data.row_index.grouped_rows(normalized)["first"]
    with spatial_data.product_cache.scope(database, "test"):
        changed = peri_scribe.fires.reuse.read_rows(
            path,
            ("perimeters",),
            keys={"first"},
        )
    assert first["perimeters"]["first"][0]["revision"] == 1
    assert changed["perimeters"]["first"][0]["revision"] == updated_revision
    assert isinstance(first["perimeters"]["first"][0]["revision"], int)
    assert isinstance(changed["perimeters"]["first"][0]["revision"], float)
    assert spatial_data.cache_values.dumps(changed["perimeters"]["first"]) == (
        spatial_data.cache_values.dumps(expected)
    )
    monkeypatch.setattr(
        spatial_data.layers,
        "read_layer",
        tests.helpers.doubles.errors.raising_stub(AssertionError("Stale index")),
    )
    with spatial_data.product_cache.scope(database, "test"):
        assert (
            peri_scribe.fires.reuse.read_rows(
                path,
                ("perimeters",),
                keys={"first"},
            )
            == changed
        )


@pytest.mark.parametrize("authenticated", [False, True])
@pytest.mark.parametrize("cache_active", [False, True])
def test_read_published_layer_reads_normalized_values_without_cache_work(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    cached_layers: list[spatial_data.layers.LayerData],
    *,
    authenticated: bool,
    cache_active: bool,
) -> None:
    path = tmp_path / "history.gpkg"
    if authenticated:
        peri_scribe.fires.reuse.write_layers(path, cached_layers)
    else:
        spatial_data.layers.write_geopackage(path, cached_layers)
    monkeypatch.setattr(
        peri_scribe.fires.reuse,
        "validated_signature",
        tests.helpers.doubles.errors.raising_stub(AssertionError("Unexpected hashing")),
    )
    monkeypatch.setattr(
        spatial_data.product_cache,
        "put",
        tests.helpers.doubles.errors.raising_stub(AssertionError("Eager cache write")),
    )
    with (
        spatial_data.product_cache.scope(tmp_path / "products.sqlite", "test")
        if cache_active
        else contextlib.nullcontext()
    ):
        frame = peri_scribe.fires.reuse.read_published_layer(path, "perimeters")

    assert frame.revision.tolist() == [1, 2]
