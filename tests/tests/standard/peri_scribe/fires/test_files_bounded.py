"""Bounded source preparation publishes the same complete logical geography."""

import pathlib

import geopandas.testing
import pytest

import peri_scribe.fires.files
import peri_scribe.fires.history
import peri_scribe.fires.index
import peri_scribe.fires.reuse
import peri_scribe.fires.sources
import peri_scribe.geo.catalog
import peri_scribe.models
import peri_scribe.sources.snapshots
import spatial_data.product_cache
import tests.helpers.doubles.errors
import tests.helpers.doubles.peri_scribe.fires.files
import tests.helpers.doubles.peri_scribe.fires.files_bounded


def test_build_bounded_full_geography_matches_complete_source_adapter(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tests.helpers.doubles.peri_scribe.fires.files_bounded.configure(
        monkeypatch,
        tmp_path,
    )
    path = peri_scribe.fires.files.build_bounded_full_geography(
        tmp_path,
        generation="current",
        unconditional=True,
    )
    bounded = {
        layer: peri_scribe.fires.reuse.read_published_layer(path, layer)
        for layer in peri_scribe.fires.files.FULL_LAYER_NAMES
    }
    prepared = peri_scribe.fires.sources.prepare_fire_sources(tmp_path / "sources")
    peri_scribe.fires.files.write_prepared_full_geography(
        tmp_path,
        prepared,
        generation="current",
        unconditional=True,
    )
    for layer, actual in bounded.items():
        expected = peri_scribe.fires.reuse.read_published_layer(path, layer)
        geopandas.testing.assert_geodataframe_equal(actual, expected)
        assert list(actual.geometry.to_wkb()) == list(expected.geometry.to_wkb())


def test_build_bounded_full_geography_marks_missing_classification_incomplete(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tests.helpers.doubles.peri_scribe.fires.files_bounded.configure(
        monkeypatch,
        tmp_path,
    )
    path = peri_scribe.fires.files.build_bounded_full_geography(
        tmp_path,
        generation="current",
        unconditional=False,
    )
    signature = peri_scribe.fires.reuse.validated_signature(
        path,
        peri_scribe.fires.files.FULL_LAYER_NAMES,
    )
    assert signature is not None
    assert signature.generation is None


def test_build_bounded_full_geography_publishes_complete_generation(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tests.helpers.doubles.peri_scribe.fires.files_bounded.configure(
        monkeypatch,
        tmp_path,
        classified=True,
    )
    path = peri_scribe.fires.files.build_bounded_full_geography(
        tmp_path,
        generation="current",
        unconditional=False,
    )
    assert peri_scribe.fires.reuse.generation_matches(
        path,
        "current",
        peri_scribe.fires.files.FULL_LAYER_NAMES,
    )


def test_build_bounded_full_geography_reuses_complete_cached_rows(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tests.helpers.doubles.peri_scribe.fires.files_bounded.configure(
        monkeypatch,
        tmp_path,
        classified=True,
    )
    path = peri_scribe.fires.files.build_bounded_full_geography(
        tmp_path,
        generation="first",
        unconditional=False,
    )
    expected = {
        layer: peri_scribe.fires.reuse.read_published_layer(path, layer)
        for layer in peri_scribe.fires.files.FULL_LAYER_NAMES
    }
    monkeypatch.setattr(
        peri_scribe.fires.history,
        "history_rows_for_fire",
        tests.helpers.doubles.peri_scribe.fires.files.reject_history_reconstruction,
    )
    peri_scribe.fires.files.build_bounded_full_geography(
        tmp_path,
        generation="second",
        unconditional=False,
    )
    for layer, frame in expected.items():
        geopandas.testing.assert_geodataframe_equal(
            peri_scribe.fires.reuse.read_published_layer(path, layer),
            frame,
        )


@pytest.mark.parametrize("unconditional", [False, True])
def test_build_bounded_full_geography_recomputes_incomplete_or_forced_rows(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    unconditional: bool,
) -> None:
    tests.helpers.doubles.peri_scribe.fires.files_bounded.configure(
        monkeypatch,
        tmp_path,
        classified=unconditional,
    )
    peri_scribe.fires.files.build_bounded_full_geography(
        tmp_path,
        generation="first",
        unconditional=False,
    )
    monkeypatch.setattr(
        peri_scribe.fires.history,
        "history_rows_for_fire",
        tests.helpers.doubles.errors.raising_stub(RuntimeError("recomputed")),
    )
    with pytest.raises(RuntimeError, match="recomputed"):
        peri_scribe.fires.files.build_bounded_full_geography(
            tmp_path,
            generation="second",
            unconditional=unconditional,
        )


def test_build_bounded_full_geography_warms_completed_classifications(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tests.helpers.doubles.peri_scribe.fires.files_bounded.configure(
        monkeypatch,
        tmp_path,
        classified=True,
    )
    with spatial_data.product_cache.scope(tmp_path / "cache.sqlite", "policy"):
        peri_scribe.fires.files.build_bounded_full_geography(
            tmp_path,
            generation="current",
            unconditional=False,
        )
        store = spatial_data.product_cache.CURRENT.get()
        assert store is not None
        rows = store.connection.execute(
            "SELECT key FROM products WHERE namespace = ?",
            (peri_scribe.fires.index.CLASSIFICATION_NAMESPACE,),
        ).fetchall()
        expected_fire_count = 2
        assert len(rows) == expected_fire_count
        for (key,) in rows:
            payload = spatial_data.product_cache.get(
                peri_scribe.fires.index.CLASSIFICATION_NAMESPACE,
                key,
            )
            assert payload is not None
            assert peri_scribe.models.FireClassification.model_validate_json(
                payload,
            ) == (
                tests.helpers.doubles.peri_scribe.fires.files_bounded.classification(
                    key,
                )
            )


@pytest.mark.parametrize("unconditional", [False, True])
def test_build_bounded_full_geography_refreshes_index_only_when_requested(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    unconditional: bool,
) -> None:
    tests.helpers.doubles.peri_scribe.fires.files_bounded.configure(
        monkeypatch,
        tmp_path,
    )
    index = peri_scribe.sources.snapshots.fire_index_path(tmp_path)
    index.write_bytes(b"previous index")
    peri_scribe.fires.files.build_bounded_full_geography(
        tmp_path,
        generation="current",
        unconditional=unconditional,
    )
    if unconditional:
        assert {
            fire.name
            for fire in peri_scribe.fires.index.load_fire_index(tmp_path).fires
        } == {"Park", "Hill"}
    else:
        assert index.read_bytes() == b"previous index"


def test_write_bounded_full_geography_returns_unavailable_for_optional_cache(
    tmp_path: pathlib.Path,
) -> None:
    assert (
        peri_scribe.fires.files.write_bounded_full_geography(
            tmp_path,
            generation="current",
            unconditional=False,
        )
        is None
    )


def test_write_bounded_full_geography_propagates_publication_failure(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tests.helpers.doubles.peri_scribe.fires.files_bounded.configure(
        monkeypatch,
        tmp_path,
    )
    monkeypatch.setattr(
        peri_scribe.fires.reuse,
        "write_layers",
        tests.helpers.doubles.errors.raising_stub(OSError("publication failed")),
    )
    with pytest.raises(OSError, match="publication failed"):
        peri_scribe.fires.files.write_bounded_full_geography(
            tmp_path,
            generation="current",
            unconditional=False,
        )


def test_write_history_of_full_geography_consumes_available_catalog(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tests.helpers.doubles.peri_scribe.fires.files_bounded.configure(
        monkeypatch,
        tmp_path,
    )
    monkeypatch.setattr(
        peri_scribe.fires.sources,
        "prepare_fire_sources",
        tests.helpers.doubles.errors.raising_stub(AssertionError("eager fallback")),
    )
    assert peri_scribe.fires.files.write_history_of_full_geography(
        tmp_path,
        unconditional=True,
    ).is_file()


def test_write_bounded_full_geography_preserves_output_on_hydration_fallback(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tests.helpers.doubles.peri_scribe.fires.files_bounded.configure(
        monkeypatch,
        tmp_path,
    )
    path = peri_scribe.fires.files.build_bounded_full_geography(
        tmp_path,
        generation="previous",
        unconditional=False,
    )
    previous = path.read_bytes()
    monkeypatch.setattr(
        peri_scribe.geo.catalog.Catalog,
        "hydrate",
        tests.helpers.doubles.errors.raising_stub(
            peri_scribe.geo.catalog.UnavailableError("damaged payload"),
        ),
    )
    assert (
        peri_scribe.fires.files.write_bounded_full_geography(
            tmp_path,
            generation="current",
            unconditional=False,
        )
        is None
    )
    assert path.read_bytes() == previous


def test_write_bounded_full_geography_propagates_source_race_before_publication(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tests.helpers.doubles.peri_scribe.fires.files_bounded.configure(
        monkeypatch,
        tmp_path,
    )
    path = peri_scribe.fires.files.build_bounded_full_geography(
        tmp_path,
        generation="previous",
        unconditional=False,
    )
    previous = path.read_bytes()
    monkeypatch.setattr(
        peri_scribe.geo.catalog.Catalog,
        "verify",
        tests.helpers.doubles.errors.raising_stub(OSError("Sources changed")),
    )
    with pytest.raises(OSError, match="Sources changed"):
        peri_scribe.fires.files.write_bounded_full_geography(
            tmp_path,
            generation="current",
            unconditional=False,
        )
    assert path.read_bytes() == previous
