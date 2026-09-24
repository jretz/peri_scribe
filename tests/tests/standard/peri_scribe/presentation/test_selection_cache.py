"""Incremental history preparation must preserve exact current evidence."""

from __future__ import annotations

import dataclasses
import pathlib

import pytest

import peri_scribe.areas
import peri_scribe.presentation.prepared_cache
import peri_scribe.presentation.selection
import spatial_data.product_cache
import tests.helpers.doubles.peri_scribe.presentation.prepared_cache
import tests.helpers.factories.geography
import tests.helpers.factories.peri_scribe.fires.scores


def test_prepare_histories_reuses_persisted_evidence_in_a_new_run(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    empty = tests.helpers.factories.geography.empty_frame()
    points = tests.helpers.factories.peri_scribe.fires.scores.reported_frame([
        ("example", "Example", 100),
    ])
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "test"):
        expected = peri_scribe.presentation.selection.prepare_histories(empty, points)
    monkeypatch.setattr(
        peri_scribe.areas,
        "prepare_history",
        lambda *_args: pytest.fail("Unchanged evidence was prepared again"),
    )
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "test"):
        actual = peri_scribe.presentation.selection.prepare_histories(
            empty,
            points.copy(),
        )
    assert actual == expected


@pytest.mark.parametrize("change", ["latest", "older", "delete", "reorder", "alias"])
def test_prepare_histories_invalidates_only_the_changed_fire(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    empty = tests.helpers.factories.geography.empty_frame()
    points = tests.helpers.factories.peri_scribe.fires.scores.reported_frame([
        ("changed", "Changed", 100),
        ("unchanged", "Unchanged", 200),
        ("changed", "Changed", 300),
    ])
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "test"):
        peri_scribe.presentation.selection.prepare_histories(empty, points)
    changed = points.copy()
    aliases = {}
    match change:
        case "latest":
            changed.loc[2, "incident_size"] = 400
        case "older":
            changed.loc[0, "incident_size"] = 150
        case "delete":
            changed = changed.iloc[1:]
        case "reorder":
            changed = changed.iloc[[2, 1, 0]]
        case _:
            aliases = {"changed": "canonical"}
    expected = peri_scribe.presentation.selection.prepare_histories(
        empty,
        changed,
        aliases=aliases,
    )
    cache_doubles = tests.helpers.doubles.peri_scribe.presentation.prepared_cache
    calls = cache_doubles.record_preparations(monkeypatch)
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "test"):
        actual = peri_scribe.presentation.selection.prepare_histories(
            empty,
            changed,
            aliases=aliases,
        )
    assert actual == expected
    assert calls == [frozenset({"changed"})]


def test_prepare_histories_invalidates_alias_merges_and_reuses_split_evidence(
    tmp_path: pathlib.Path,
) -> None:
    empty = tests.helpers.factories.geography.empty_frame()
    points = tests.helpers.factories.peri_scribe.fires.scores.reported_frame([
        ("canonical", "Example", 100),
        ("alias", "Example", 200),
    ])
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "test"):
        split = peri_scribe.presentation.selection.prepare_histories(empty, points)
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "test"):
        merged = peri_scribe.presentation.selection.prepare_histories(
            empty,
            points,
            aliases={"alias": "canonical"},
        )
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "test"):
        split_again = peri_scribe.presentation.selection.prepare_histories(
            empty,
            points,
        )
    assert set(merged) == {("id", "canonical")}
    assert split_again == split


def test_prepare_histories_invalidates_changed_runtime_policy(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    empty = tests.helpers.factories.geography.empty_frame()
    points = tests.helpers.factories.peri_scribe.fires.scores.reported_frame([
        ("example", "Example", 100),
    ])
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "test"):
        peri_scribe.presentation.selection.prepare_histories(empty, points)
    monkeypatch.setattr(
        peri_scribe.areas,
        "DEFAULT_POLICY",
        dataclasses.replace(peri_scribe.areas.DEFAULT_POLICY, significant_ratio=1.5),
    )
    cache_doubles = tests.helpers.doubles.peri_scribe.presentation.prepared_cache
    calls = cache_doubles.record_preparations(monkeypatch)
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "test"):
        peri_scribe.presentation.selection.prepare_histories(empty, points)
    assert calls == [frozenset({"example"})]


def test_prepare_histories_recomputes_invalid_typed_payloads(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    empty = tests.helpers.factories.geography.empty_frame()
    points = tests.helpers.factories.peri_scribe.fires.scores.reported_frame([
        ("example", "Example", 100),
    ])
    expected = peri_scribe.presentation.selection.prepare_histories(empty, points)
    monkeypatch.setattr(spatial_data.product_cache, "get", lambda *_args: b"invalid")
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "test"):
        actual = peri_scribe.presentation.selection.prepare_histories(empty, points)
    assert actual == expected


def test_prepare_histories_keeps_working_with_unsupported_source_values(
    tmp_path: pathlib.Path,
) -> None:
    empty = tests.helpers.factories.geography.empty_frame()
    points = tests.helpers.factories.peri_scribe.fires.scores.reported_frame([
        ("example", "Example", 100),
    ])
    points["unused"] = [object()]
    expected = peri_scribe.presentation.selection.prepare_histories(empty, points)
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "test"):
        actual = peri_scribe.presentation.selection.prepare_histories(empty, points)
    assert actual == expected


def test_prepare_histories_keeps_working_with_unserializable_prepared_values(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    empty = tests.helpers.factories.geography.empty_frame()
    points = tests.helpers.factories.peri_scribe.fires.scores.reported_frame([
        ("example", "Example", 100),
    ])
    expected = peri_scribe.presentation.selection.prepare_histories(empty, points)
    monkeypatch.setattr(
        peri_scribe.presentation.prepared_cache,
        "history_bytes",
        tests.helpers.doubles.peri_scribe.presentation.prepared_cache.reject_serialization,
    )
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "test"):
        actual = peri_scribe.presentation.selection.prepare_histories(empty, points)
    assert actual == expected
