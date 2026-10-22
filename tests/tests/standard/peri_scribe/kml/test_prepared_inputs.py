"""Qualified map inputs preserve cached facts and exact latest attribute selection."""

from __future__ import annotations

import compression.zstd
import contextlib
import dataclasses
import pathlib
import sqlite3

import geopandas
import geopandas.testing
import pyogrio.errors
import pytest

import peri_scribe.areas
import peri_scribe.execution
import peri_scribe.fires.derived_layers
import peri_scribe.fires.files
import peri_scribe.kml.prepared_inputs
import peri_scribe.pipeline_state
import peri_scribe.presentation.index
import peri_scribe.presentation.prepared_cache
import spatial_data.cache_values
import spatial_data.product_cache
import tests.helpers.doubles.errors
import tests.helpers.doubles.peri_scribe.kml.prepared_inputs
import tests.helpers.factories.peri_scribe.kml.parsing
import tests.helpers.factories.peri_scribe.kml.prepared_inputs
from measurement_units import units


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (("id", "a"), True),
        (("name", "a"), True),
        (("component", "a"), True),
        ([], False),
        ((), False),
        (("id",), False),
        (("id", "a", "extra"), False),
        (("unknown", "a"), False),
        (("id", 1), False),
    ],
)
def test_valid_identity_keeps_tag_and_scalar_types_distinct(
    value: object,
    *,
    expected: bool,
) -> None:
    assert peri_scribe.kml.prepared_inputs.valid_identity(value) is expected


@pytest.mark.parametrize(
    "records",
    [
        (None,),
        ((),),
        ((("id", "a"), b"", "extra"),),
        (((), b""),),
        ((("id", "a"), 1),),
    ],
)
def test_decoded_histories_rejects_malformed_record_shapes(records: object) -> None:
    with pytest.raises(ValueError, match="history"):
        peri_scribe.kml.prepared_inputs.decoded_histories(records)


def test_decoded_histories_rejects_non_tuple_records() -> None:
    with pytest.raises(TypeError, match="must be a tuple"):
        peri_scribe.kml.prepared_inputs.decoded_histories([])


def test_decoded_histories_rejects_duplicate_owners() -> None:
    history = tests.helpers.factories.peri_scribe.kml.prepared_inputs.history(30)
    record = (
        ("id", "a"),
        compression.zstd.compress(
            peri_scribe.presentation.prepared_cache.history_bytes(history),
        ),
    )
    with pytest.raises(ValueError, match="must be unique"):
        peri_scribe.kml.prepared_inputs.decoded_histories((record, record))


@pytest.mark.parametrize("suffix", [b"trailing", compression.zstd.compress(b"second")])
def test_read_compressed_history_rejects_trailing_or_concatenated_frames(
    suffix: bytes,
) -> None:
    history = tests.helpers.factories.peri_scribe.kml.prepared_inputs.history(30)
    content = compression.zstd.compress(
        peri_scribe.presentation.prepared_cache.history_bytes(history),
    )
    with pytest.raises(ValueError, match="one complete compressed frame"):
        peri_scribe.kml.prepared_inputs.read_compressed_history(content + suffix)


def test_read_compressed_history_rejects_truncated_frames() -> None:
    history = tests.helpers.factories.peri_scribe.kml.prepared_inputs.history(30)
    content = compression.zstd.compress(
        peri_scribe.presentation.prepared_cache.history_bytes(history),
    )
    with pytest.raises(ValueError, match="one complete compressed frame"):
        peri_scribe.kml.prepared_inputs.read_compressed_history(content[:-1])


def test_read_histories_returns_missing_without_a_product() -> None:
    assert peri_scribe.kml.prepared_inputs.read_histories("absent") is None


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (b"invalid", None),
        (spatial_data.cache_values.dumps([]), None),
        (spatial_data.cache_values.dumps(((("id", "a"), b"invalid"),)), None),
        (
            spatial_data.cache_values.dumps((
                (("id", "a"), compression.zstd.compress(b"invalid")),
            )),
            None,
        ),
        (spatial_data.cache_values.dumps(()), {}),
    ],
)
def test_read_histories_distinguishes_malformed_and_valid_empty_products(
    tmp_path: pathlib.Path,
    payload: bytes,
    expected: dict[object, object] | None,
) -> None:
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "test"):
        spatial_data.product_cache.put(
            peri_scribe.kml.prepared_inputs.NAMESPACE,
            "key",
            payload,
        )
        result = peri_scribe.kml.prepared_inputs.read_histories("key")
    assert result == expected


@pytest.mark.parametrize("area", [None, 0.0, 24.0])
def test_read_histories_rejects_ineligible_retained_facts(
    tmp_path: pathlib.Path,
    area: float | None,
) -> None:
    history = tests.helpers.factories.peri_scribe.kml.prepared_inputs.history(area)
    payload = spatial_data.cache_values.dumps((
        (
            ("id", "a"),
            compression.zstd.compress(
                peri_scribe.presentation.prepared_cache.history_bytes(history),
            ),
        ),
    ))
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "test"):
        spatial_data.product_cache.put(
            peri_scribe.kml.prepared_inputs.NAMESPACE,
            "key",
            payload,
        )
        assert peri_scribe.kml.prepared_inputs.read_histories("key") is None


def test_read_histories_rejects_wrong_area_dimensions(tmp_path: pathlib.Path) -> None:
    history = dataclasses.replace(
        tests.helpers.factories.peri_scribe.kml.prepared_inputs.history(30),
        historical_area=30 * units.meters,
    )
    payload = spatial_data.cache_values.dumps((
        (
            ("id", "a"),
            compression.zstd.compress(
                peri_scribe.presentation.prepared_cache.history_bytes(history),
            ),
        ),
    ))
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "test"):
        spatial_data.product_cache.put(
            peri_scribe.kml.prepared_inputs.NAMESPACE,
            "key",
            payload,
        )
        assert peri_scribe.kml.prepared_inputs.read_histories("key") is None


def test_write_histories_preserves_qualifying_objects_and_omits_small_fires(
    tmp_path: pathlib.Path,
) -> None:
    large = tests.helpers.factories.peri_scribe.kml.prepared_inputs.history(25)
    small = tests.helpers.factories.peri_scribe.kml.prepared_inputs.history(24)
    histories = {("id", "large"): large, ("id", "small"): small}
    assert peri_scribe.kml.prepared_inputs.qualifying_histories(histories) == {
        ("id", "large"): large,
    }
    assert (
        peri_scribe.kml.prepared_inputs.qualifying_histories(histories)["id", "large"]
        is large
    )
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "test"):
        peri_scribe.kml.prepared_inputs.write_histories("key", histories)
        assert peri_scribe.kml.prepared_inputs.read_histories("key") == {
            ("id", "large"): large,
        }
        payload = spatial_data.product_cache.get(
            peri_scribe.kml.prepared_inputs.NAMESPACE,
            "key",
        )
        assert payload is not None
        records = spatial_data.cache_values.loads(payload)
        assert isinstance(records, tuple)
        assert records[0][0] == ("id", "large")
        assert compression.zstd.decompress(records[0][1]) == (
            peri_scribe.presentation.prepared_cache.history_bytes(large)
        )


def test_write_histories_leaves_unencodable_facts_uncached(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        peri_scribe.presentation.prepared_cache,
        "history_bytes",
        tests.helpers.doubles.errors.raising_stub(ValueError("unsupported")),
    )
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "test"):
        peri_scribe.kml.prepared_inputs.write_histories(
            "key",
            {
                (
                    "id",
                    "a",
                ): tests.helpers.factories.peri_scribe.kml.prepared_inputs.history(25),
            },
        )
        assert peri_scribe.kml.prepared_inputs.read_histories("key") is None


def test_write_histories_leaves_failed_compression_uncached(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        compression.zstd,
        "compress",
        tests.helpers.doubles.errors.raising_stub(
            compression.zstd.ZstdError("compression failed"),
        ),
    )
    histories = {
        ("id", "a"): tests.helpers.factories.peri_scribe.kml.prepared_inputs.history(
            25,
        ),
    }
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "test"):
        peri_scribe.kml.prepared_inputs.write_histories("key", histories)
        assert peri_scribe.kml.prepared_inputs.read_histories("key") is None


def test_preparation_key_tracks_aliases_generation_and_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = tests.helpers.factories.peri_scribe.kml.parsing.fire_index_entry(
        "Example",
        "active",
        identifier="id-a",
    )
    index = tests.helpers.factories.peri_scribe.kml.parsing.fire_index([entry])
    identity = ("full", "differential")
    original = peri_scribe.kml.prepared_inputs.preparation_key(identity, index)
    assert (
        peri_scribe.kml.prepared_inputs.preparation_key(("full", "changed"), index)
        != original
    )
    entry.aliases.append("alias")
    assert peri_scribe.kml.prepared_inputs.preparation_key(identity, index) != original
    entry.aliases.clear()
    monkeypatch.setattr(
        peri_scribe.areas,
        "DEFAULT_POLICY",
        dataclasses.replace(peri_scribe.areas.DEFAULT_POLICY, rapid_confirmations=3),
    )
    assert peri_scribe.kml.prepared_inputs.preparation_key(identity, index) != original


def test_selected_latest_positions_preserves_alias_and_empty_selection_rules() -> None:
    frame = geopandas.GeoDataFrame(
        {
            "fire_identifier": ["a", "b", "alias", None],
            "fire_name": ["Example", "Other", "Example", "Anonymous"],
        },
        geometry=[None] * 4,
    )
    index = tests.helpers.factories.peri_scribe.kml.parsing.fire_index([
        tests.helpers.factories.peri_scribe.kml.parsing.fire_index_entry(
            "Example",
            "active",
            identifier="a",
            aliases=["alias"],
        ),
        tests.helpers.factories.peri_scribe.kml.parsing.fire_index_entry(
            "Missing",
            "active",
        ),
    ])
    assert peri_scribe.kml.prepared_inputs.selected_latest_positions(frame, index) == (
        2,
    )
    assert (
        peri_scribe.kml.prepared_inputs.selected_latest_positions(
            frame.iloc[0:0],
            index,
        )
        == ()
    )


def test_read_attribute_rows_preserves_feature_id_gaps_batches_and_quoted_tables(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "attributes.sqlite"
    with contextlib.closing(sqlite3.connect(path)) as connection:
        connection.execute(
            'CREATE TABLE "quoted""table" (fid INTEGER, source_attributes TEXT)',
        )
        connection.executemany(
            'INSERT INTO "quoted""table" VALUES (?, ?)',
            [(1, "first"), (5, "middle"), (9, None)],
        )
        connection.commit()
    monkeypatch.setattr(peri_scribe.kml.prepared_inputs, "ATTRIBUTE_BATCH_SIZE", 2)
    assert peri_scribe.kml.prepared_inputs.read_attribute_rows(
        path,
        'quoted"table',
        (9, 1, 5),
    ) == {1: "first", 5: "middle", 9: None}
    assert (
        peri_scribe.kml.prepared_inputs.read_attribute_rows(
            path,
            'quoted"table',
            (),
        )
        == {}
    )


def test_read_projected_layer_keeps_schema_and_exact_latest_attributes(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = tests.helpers.factories.peri_scribe.kml.prepared_inputs.geography(
        tmp_path,
    )
    path = fixture.full_path
    selected = peri_scribe.kml.prepared_inputs.qualified_index(
        fixture.index,
        fixture.histories,
    )
    with monkeypatch.context() as options:
        options.setattr(geopandas.options, "io_engine", "fiona")
        actual = peri_scribe.kml.prepared_inputs.read_projected_layer(
            path,
            "perimeter_history",
            selected,
        )
    expected = geopandas.read_file(path, layer="perimeter_history")
    expected.loc[[0, 1], "source_attributes"] = None
    geopandas.testing.assert_geodataframe_equal(actual, expected)


def test_read_projected_layer_keeps_fid_gaps_separate_from_row_positions(
    tmp_path: pathlib.Path,
) -> None:
    fixture = tests.helpers.factories.peri_scribe.kml.prepared_inputs.geography(
        tmp_path,
    )
    path = fixture.full_path
    with contextlib.closing(sqlite3.connect(path)) as connection:
        connection.execute("DELETE FROM perimeter_history WHERE fid = 2")
        connection.commit()
    actual = peri_scribe.kml.prepared_inputs.read_projected_layer(
        path,
        "perimeter_history",
        fixture.index,
    )
    assert list(actual.index) == [0, 1]
    assert actual["source_attributes"].isna().tolist() == [True, False]
    assert actual["source_attributes"].iloc[-1] == '{"new": 3}'


@pytest.mark.parametrize("attributes", [None, (1.0, 2.0, 3.0), (None, None, None)])
def test_read_projected_layer_preserves_original_attribute_schema(
    tmp_path: pathlib.Path,
    attributes: tuple[object, ...] | None,
) -> None:
    fixture = tests.helpers.factories.peri_scribe.kml.prepared_inputs.geography(
        tmp_path,
        attributes=attributes,
    )
    path = fixture.full_path
    actual = peri_scribe.kml.prepared_inputs.read_projected_layer(
        path,
        "perimeter_history",
        fixture.index,
    )
    geopandas.testing.assert_geodataframe_equal(
        actual,
        geopandas.read_file(path, layer="perimeter_history"),
    )


def test_prepare_inputs_populates_then_reuses_only_qualified_complete_histories(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = tests.helpers.factories.peri_scribe.kml.prepared_inputs.geography(
        tmp_path,
    )
    tests.helpers.doubles.peri_scribe.kml.prepared_inputs.fixed_preparation(
        monkeypatch,
        fixture,
    )
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "test"):
        cold = peri_scribe.kml.prepared_inputs.prepare_inputs(
            fixture.year_directory,
            fixture.index,
        )
        assert cold.histories is fixture.histories
        warm = peri_scribe.kml.prepared_inputs.prepare_inputs(
            fixture.year_directory,
            fixture.index,
        )
    assert set(warm.histories) == {("id", "id-a")}
    assert warm.layers.incidents.empty
    assert warm.layers.perimeters["source_attributes"].isna().tolist() == [
        True,
        True,
        False,
    ]
    assert warm.layers.points["source_attributes"].isna().tolist() == [
        True,
        True,
        False,
    ]
    assert warm.layers.differential_perimeters["source_attributes"].isna().all()


@pytest.mark.parametrize("existing", [False, True])
def test_prepare_inputs_prefers_shared_full_layers_over_projected_cache(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    existing: bool,
) -> None:
    fixture = tests.helpers.factories.peri_scribe.kml.prepared_inputs.geography(
        tmp_path,
    )
    tests.helpers.doubles.peri_scribe.kml.prepared_inputs.fixed_preparation(
        monkeypatch,
        fixture,
    )
    with (
        peri_scribe.execution.sharing(),
        spatial_data.product_cache.scope(tmp_path / "products.sqlite", "test"),
    ):
        key = peri_scribe.kml.prepared_inputs.preparation_key(
            fixture.identity,
            fixture.index,
        )
        if existing:
            spatial_data.product_cache.put(
                peri_scribe.kml.prepared_inputs.NAMESPACE,
                key,
                b"existing",
            )
            monkeypatch.setattr(
                peri_scribe.presentation.prepared_cache,
                "history_bytes",
                tests.helpers.doubles.errors.raising_stub(
                    AssertionError("An existing manifest avoids serialization"),
                ),
            )
        peri_scribe.execution.put(
            peri_scribe.execution.Group.DERIVED,
            (fixture.year_directory.resolve(), fixture.identity),
            fixture.layers,
        )
        monkeypatch.setattr(
            peri_scribe.kml.prepared_inputs,
            "read_histories",
            tests.helpers.doubles.errors.raising_stub(
                AssertionError("Shared layers take precedence"),
            ),
        )
        result = peri_scribe.kml.prepared_inputs.prepare_inputs(
            fixture.year_directory,
            fixture.index,
        )
        payload = spatial_data.product_cache.get(
            peri_scribe.kml.prepared_inputs.NAMESPACE,
            key,
        )
        assert payload is not None
        assert (payload == b"existing") is existing
    assert result.layers is fixture.layers
    assert result.histories is fixture.histories


@pytest.mark.parametrize(
    "error",
    [
        KeyError("missing"),
        ValueError("invalid"),
        sqlite3.OperationalError("failed"),
        pyogrio.errors.DataLayerError("invalid layer"),
        pyogrio.errors.DataSourceError("invalid source"),
    ],
)
def test_prepare_inputs_rebuilds_full_evidence_after_projection_failure(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
) -> None:
    fixture = tests.helpers.factories.peri_scribe.kml.prepared_inputs.geography(
        tmp_path,
    )
    tests.helpers.doubles.peri_scribe.kml.prepared_inputs.fixed_preparation(
        monkeypatch,
        fixture,
    )
    key = peri_scribe.kml.prepared_inputs.preparation_key(
        fixture.identity,
        fixture.index,
    )
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "test"):
        peri_scribe.kml.prepared_inputs.write_histories(key, fixture.histories)
        monkeypatch.setattr(
            peri_scribe.kml.prepared_inputs,
            "read_projected_layers",
            tests.helpers.doubles.errors.raising_stub(error),
        )
        result = peri_scribe.kml.prepared_inputs.prepare_inputs(
            fixture.year_directory,
            fixture.index,
        )
    assert result.histories is fixture.histories
    assert result.layers.perimeters["source_attributes"].notna().all()


def test_prepare_inputs_replaces_malformed_manifest_after_full_preparation(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = tests.helpers.factories.peri_scribe.kml.prepared_inputs.geography(
        tmp_path,
    )
    tests.helpers.doubles.peri_scribe.kml.prepared_inputs.fixed_preparation(
        monkeypatch,
        fixture,
    )
    key = peri_scribe.kml.prepared_inputs.preparation_key(
        fixture.identity,
        fixture.index,
    )
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "test"):
        spatial_data.product_cache.put(
            peri_scribe.kml.prepared_inputs.NAMESPACE,
            key,
            b"malformed",
        )
        result = peri_scribe.kml.prepared_inputs.prepare_inputs(
            fixture.year_directory,
            fixture.index,
        )
        assert peri_scribe.kml.prepared_inputs.read_histories(key) == {
            ("id", "id-a"): fixture.histories["id", "id-a"],
        }
    assert result.histories is fixture.histories
    assert result.layers.perimeters["source_attributes"].notna().all()


def test_prepare_inputs_rejects_alias_only_cache_without_canonical_history(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = tests.helpers.factories.peri_scribe.kml.prepared_inputs.geography(
        tmp_path,
    )
    tests.helpers.doubles.peri_scribe.kml.prepared_inputs.fixed_preparation(
        monkeypatch,
        fixture,
    )
    entry = fixture.index.fires[0].model_copy(
        update={"identifier": "canonical", "aliases": ["id-a"]},
    )
    index = tests.helpers.factories.peri_scribe.kml.parsing.fire_index([entry])
    key = peri_scribe.kml.prepared_inputs.preparation_key(fixture.identity, index)
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "test"):
        peri_scribe.kml.prepared_inputs.write_histories(key, fixture.histories)
        result = peri_scribe.kml.prepared_inputs.prepare_inputs(
            fixture.year_directory,
            index,
        )
    assert result.histories is fixture.histories
    assert result.layers.perimeters["source_attributes"].notna().all()


@pytest.mark.parametrize(
    ("active", "full_exists"),
    [(False, False), (True, False), (True, True)],
)
def test_prepare_inputs_uses_complete_loader_when_real_geography_is_absent(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    active: bool,
    full_exists: bool,
) -> None:
    index = tests.helpers.factories.peri_scribe.kml.parsing.fire_index([])
    layers = peri_scribe.fires.derived_layers.DerivedLayers(
        perimeters=geopandas.GeoDataFrame(),
        points=geopandas.GeoDataFrame(),
        differential_perimeters=geopandas.GeoDataFrame(),
    )
    monkeypatch.setattr(
        peri_scribe.fires.derived_layers,
        "read_derived_layers",
        lambda *_args, **_kwargs: layers,
    )
    monkeypatch.setattr(
        peri_scribe.presentation.index,
        "prepare_histories",
        lambda *_args, **_kwargs: {},
    )
    if full_exists:
        full = peri_scribe.fires.files.history_geopackage_path(tmp_path)
        full.parent.mkdir(parents=True)
        full.touch()
    scope = (
        spatial_data.product_cache.scope(tmp_path / "products.sqlite", "test")
        if active
        else contextlib.nullcontext()
    )
    with scope:
        result = peri_scribe.kml.prepared_inputs.prepare_inputs(tmp_path, index)
    assert result.layers is layers
    assert result.histories == {}


def test_prepare_inputs_retains_valid_empty_qualification_without_attributes(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = tests.helpers.factories.peri_scribe.kml.prepared_inputs.geography(
        tmp_path,
    )
    tests.helpers.doubles.peri_scribe.kml.prepared_inputs.fixed_preparation(
        monkeypatch,
        fixture,
    )
    key = peri_scribe.kml.prepared_inputs.preparation_key(
        fixture.identity,
        fixture.index,
    )
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "test"):
        peri_scribe.kml.prepared_inputs.write_histories(key, {})
        result = peri_scribe.kml.prepared_inputs.prepare_inputs(
            fixture.year_directory,
            fixture.index,
        )
    assert result.histories == {}
    assert result.layers.perimeters["source_attributes"].isna().all()


def test_prepare_inputs_rejects_unrelated_writer_before_reading_products(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = tests.helpers.factories.peri_scribe.kml.prepared_inputs.geography(
        tmp_path,
    )
    tests.helpers.doubles.peri_scribe.kml.prepared_inputs.legacy_paths(
        monkeypatch,
        fixture,
    )
    with (
        spatial_data.product_cache.scope(tmp_path / "products.sqlite", "test"),
        peri_scribe.pipeline_state.file_lock(
            fixture.year_directory,
            shared=False,
        ) as acquired,
    ):
        assert acquired
        with pytest.raises(RuntimeError, match="A writer owns"):
            peri_scribe.kml.prepared_inputs.prepare_inputs(
                fixture.year_directory,
                fixture.index,
            )
