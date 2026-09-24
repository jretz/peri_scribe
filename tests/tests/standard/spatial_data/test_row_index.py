"""Published reuse retains typed row identities and only the current generation."""

import hashlib
import pathlib

import geopandas
import pytest

import spatial_data.cache_values
import spatial_data.layers
import spatial_data.product_cache
import spatial_data.row_index
import tests.helpers.doubles.errors


def test_read_misses_without_an_index(tmp_path: pathlib.Path) -> None:
    assert (
        spatial_data.row_index.read(tmp_path / "history.gpkg", "points", "file") is None
    )


@pytest.mark.parametrize("keys", [None, frozenset(), frozenset({"second", "absent"})])
def test_read_returns_only_requested_histories_in_published_order(
    tmp_path: pathlib.Path,
    cached_layers: list[spatial_data.layers.LayerData],
    keys: frozenset[str] | None,
) -> None:
    frame = cached_layers[0].dataframe.iloc[[1, 0, 1]].reset_index(drop=True)
    expected = frame.to_dict("records")
    all_rows = {"second": [expected[0], expected[2]], "first": [expected[1]]}
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "policy"):
        spatial_data.row_index.seed(tmp_path / "history.gpkg", "points", "file", frame)

        actual = spatial_data.row_index.read(
            tmp_path / "history.gpkg",
            "points",
            "file",
            keys,
        )

    assert actual == {
        key: rows for key, rows in all_rows.items() if keys is None or key in keys
    }


def test_read_binds_index_to_published_checksum(
    tmp_path: pathlib.Path,
    cached_layers: list[spatial_data.layers.LayerData],
) -> None:
    path = tmp_path / "history.gpkg"
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "policy"):
        spatial_data.row_index.seed(
            path,
            "points",
            "original",
            cached_layers[0].dataframe,
        )

        assert spatial_data.row_index.read(path, "points", "changed") is None


@pytest.mark.parametrize("damage", ["missing", "digest", "shape", "encoding"])
def test_read_rejects_promised_but_invalid_payloads(
    tmp_path: pathlib.Path,
    damage: str,
) -> None:
    path = tmp_path / "history.gpkg"
    manifest_namespace, payload_namespace = spatial_data.row_index.namespaces(
        path,
        "points",
    )
    payload = (
        spatial_data.cache_values.dumps([]) if damage != "encoding" else b"invalid"
    )
    digest = hashlib.sha256(payload).hexdigest() if damage != "digest" else "wrong"
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "policy"):
        spatial_data.product_cache.put(
            manifest_namespace,
            "current",
            spatial_data.cache_values.dumps((
                "file",
                ("derivation_key",),
                (("fire", digest),),
            )),
        )
        if damage != "missing":
            spatial_data.product_cache.put(payload_namespace, digest, payload)

        assert spatial_data.row_index.read(path, "points", "file") is None


def test_read_does_not_decode_unrequested_payloads(
    tmp_path: pathlib.Path,
    cached_layers: list[spatial_data.layers.LayerData],
) -> None:
    path = tmp_path / "history.gpkg"
    frame = cached_layers[0].dataframe
    first_payload = spatial_data.cache_values.dumps([frame.to_dict("records")[0]])
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "policy"):
        spatial_data.row_index.seed(path, "points", "file", frame)
        _manifest_namespace, payload_namespace = spatial_data.row_index.namespaces(
            path,
            "points",
        )
        spatial_data.product_cache.put(
            payload_namespace,
            hashlib.sha256(first_payload).hexdigest(),
            b"invalid",
        )

        assert spatial_data.row_index.read(path, "points", "file", {"second"}) == {
            "second": [frame.to_dict("records")[1]],
        }


@pytest.mark.parametrize(
    "document",
    [
        None,
        (1, (), ()),
        ("file", ["key"], ()),
        ("file", (1,), ()),
        ("file", (), [()]),
        ("file", (), (None,)),
        ("file", (), (("key",),)),
        ("file", (), ((1, "digest"),)),
        ("file", (), (("key", "first"), ("key", "second"))),
    ],
)
def test_read_manifest_rejects_incomplete_or_duplicate_entries(
    document: object,
) -> None:
    with pytest.raises(ValueError, match="Invalid published row manifest"):
        spatial_data.row_index.read_manifest(spatial_data.cache_values.dumps(document))


@pytest.mark.parametrize(
    "document",
    [None, [], [1], [{}], [{"other": "fire"}], [{"derivation_key": "other"}]],
)
def test_read_payload_rejects_incomplete_or_mismatched_rows(document: object) -> None:
    with pytest.raises(ValueError, match="Invalid published row payload"):
        spatial_data.row_index.read_payload(
            spatial_data.cache_values.dumps(document),
            "fire",
            ("derivation_key",),
        )


def test_read_rejects_malformed_manifest(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "history.gpkg"
    namespace, _payload_namespace = spatial_data.row_index.namespaces(path, "points")
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "policy"):
        spatial_data.product_cache.put(namespace, "current", b"invalid")

        assert spatial_data.row_index.read(path, "points", "file") is None


def test_grouped_rows_accepts_empty_layers_without_keys() -> None:
    assert spatial_data.row_index.grouped_rows(geopandas.GeoDataFrame()) == {}


def test_grouped_rows_rejects_populated_layer_without_keys(
    cached_layers: list[spatial_data.layers.LayerData],
) -> None:
    with pytest.raises(ValueError, match="Missing history derivation keys"):
        spatial_data.row_index.grouped_rows(
            geopandas.GeoDataFrame(
                cached_layers[0].dataframe.drop(columns="derivation_key"),
            ),
        )


def test_grouped_rows_excludes_null_derivation_keys(
    cached_layers: list[spatial_data.layers.LayerData],
) -> None:
    frame = cached_layers[0].dataframe
    frame.loc[0, "derivation_key"] = None

    assert spatial_data.row_index.grouped_rows(frame) == {
        "second": [frame.to_dict("records")[1]],
    }


def test_seed_ignores_inactive_store(
    tmp_path: pathlib.Path,
    cached_layers: list[spatial_data.layers.LayerData],
) -> None:
    path = tmp_path / "history.gpkg"
    spatial_data.row_index.seed(path, "points", "file", cached_layers[0].dataframe)

    assert spatial_data.row_index.read(path, "points", "file") is None


def test_seed_preserves_empty_layer_as_available_index(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "history.gpkg"
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "policy"):
        spatial_data.row_index.seed(path, "points", "file", geopandas.GeoDataFrame())

        assert spatial_data.row_index.read(path, "points", "file") == {}
        assert spatial_data.row_index.read(path, "points", "file", adaptive=True) == {}


def test_seed_fails_open_for_unserializable_normalized_values(
    tmp_path: pathlib.Path,
    cached_layers: list[spatial_data.layers.LayerData],
) -> None:
    path = tmp_path / "history.gpkg"
    frame = cached_layers[0].dataframe
    frame["unsupported"] = [object(), object()]
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "policy"):
        spatial_data.row_index.seed(path, "points", "file", frame)

        assert spatial_data.row_index.read(path, "points", "file") is None


def test_seed_reuses_identical_row_payloads_across_file_generations(
    tmp_path: pathlib.Path,
    cached_layers: list[spatial_data.layers.LayerData],
) -> None:
    path = tmp_path / "history.gpkg"
    frame = cached_layers[0].dataframe
    _manifest_namespace, namespace = spatial_data.row_index.namespaces(path, "points")
    second_payload = spatial_data.cache_values.dumps([frame.to_dict("records")[1]])
    second_digest = hashlib.sha256(second_payload).hexdigest()
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "policy"):
        spatial_data.row_index.seed(path, "points", "original", frame)
        spatial_data.row_index.seed(path, "points", "changed", frame.iloc[:1])

        assert spatial_data.product_cache.get(namespace, second_digest) is None
        assert spatial_data.row_index.read(path, "points", "changed") == {
            "first": [frame.to_dict("records")[0]],
        }


def test_seed_accepts_already_grouped_rows_without_changing_types(
    tmp_path: pathlib.Path,
    cached_layers: list[spatial_data.layers.LayerData],
) -> None:
    path = tmp_path / "history.gpkg"
    frame = cached_layers[0].dataframe
    groups = spatial_data.row_index.grouped_rows(frame)
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "policy"):
        spatial_data.row_index.seed(path, "points", "file", frame, rows=groups)
        loaded = spatial_data.row_index.read(path, "points", "file")

    assert spatial_data.cache_values.dumps(loaded) == spatial_data.cache_values.dumps(
        groups,
    )


@pytest.mark.parametrize(
    ("keys", "available", "expected"),
    [
        (None, set(), True),
        (set(), {"first", "second"}, False),
        ({"unknown", "other"}, {"first", "second"}, False),
        ({"first"}, {"first", "second"}, False),
        ({"first", "second"}, {"first", "second", "third", "fourth"}, True),
        (
            {"first", "second"},
            {"first", "second", "third", "fourth", "fifth"},
            False,
        ),
    ],
)
def test_prefer_bulk_requires_a_large_matching_share_of_available_groups(
    monkeypatch: pytest.MonkeyPatch,
    keys: set[str] | None,
    available: set[str],
    *,
    expected: bool,
) -> None:
    monkeypatch.setattr(spatial_data.row_index, "MINIMUM_BULK_GROUPS", 2)

    assert spatial_data.row_index.prefer_bulk(keys, available) is expected


@pytest.mark.parametrize("keys", [None, frozenset({"first", "second"})])
def test_read_adaptive_dense_selection_defers_without_decoding_payloads(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    cached_layers: list[spatial_data.layers.LayerData],
    keys: frozenset[str] | None,
) -> None:
    path = tmp_path / "history.gpkg"
    monkeypatch.setattr(spatial_data.row_index, "MINIMUM_BULK_GROUPS", 2)
    monkeypatch.setattr(
        spatial_data.row_index,
        "load_groups",
        tests.helpers.doubles.errors.raising_stub(AssertionError("Dense JSON decode")),
    )
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "policy"):
        spatial_data.row_index.seed(path, "points", "file", cached_layers[0].dataframe)

        assert (
            spatial_data.row_index.read(
                path,
                "points",
                "file",
                keys,
                adaptive=True,
            )
            is None
        )


@pytest.mark.parametrize("keys", [frozenset(), frozenset({"unknown"})])
def test_read_adaptive_unknown_selection_needs_no_row_payloads(
    tmp_path: pathlib.Path,
    cached_layers: list[spatial_data.layers.LayerData],
    keys: frozenset[str],
) -> None:
    path = tmp_path / "history.gpkg"
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "policy"):
        spatial_data.row_index.seed(path, "points", "file", cached_layers[0].dataframe)
        _manifest_namespace, payload_namespace = spatial_data.row_index.namespaces(
            path,
            "points",
        )
        spatial_data.product_cache.prune(payload_namespace, [])

        assert (
            spatial_data.row_index.read(
                path,
                "points",
                "file",
                keys,
                adaptive=True,
            )
            == {}
        )
