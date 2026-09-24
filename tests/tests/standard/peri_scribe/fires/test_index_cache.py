"""Persist only classifications authenticated by complete evidence and dependencies."""

from __future__ import annotations

import dataclasses
import pathlib

import pytest

import peri_scribe.execution
import peri_scribe.fires.classification
import peri_scribe.fires.index
import peri_scribe.fires.sources
import peri_scribe.models
import peri_scribe.sources.administrative_boundaries
import spatial_data.product_cache
import tests.helpers.doubles.peri_scribe.fires.index


def test_classifications_for_prepared_sources_reuses_results_across_executions(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    history_inputs: list[peri_scribe.fires.sources.ReadFireSources],
) -> None:
    classification = peri_scribe.models.FireClassification(
        classification=peri_scribe.models.BorderClassification.INSIDE_CALIFORNIA,
        outside_area_fraction=0.0,
        inside_area_fraction=1.0,
        wfigs_to_firis_area_ratio=1.0000000000000002,
        signals=[peri_scribe.models.BorderSignal.GEOMETRY_NEAR],
    )
    recorder = tests.helpers.doubles.peri_scribe.fires.index.ClassificationRecorder(
        classification=classification,
    )
    monkeypatch.setattr(
        peri_scribe.fires.classification,
        "classify_fire_sources",
        recorder.classify,
    )
    for _iteration in range(2):
        with (
            peri_scribe.execution.sharing(),
            spatial_data.product_cache.scope(tmp_path / "products.sqlite", "context"),
        ):
            prepared = peri_scribe.fires.sources.prepare_fire_sources(
                tmp_path / "sources",
            )
            classifications = (
                peri_scribe.fires.index.classifications_for_prepared_sources(
                    tmp_path,
                    prepared,
                )
            )
            assert classifications == {
                id(fire): classification for fire in prepared.groups.fires
            }

    assert recorder.calls == [("First", "Second")]


@pytest.mark.parametrize("change", ["source", "boundary", "context"])
def test_classifications_for_prepared_sources_invalidates_changed_dependencies(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    history_inputs: list[peri_scribe.fires.sources.ReadFireSources],
    change: str,
) -> None:
    recorder = tests.helpers.doubles.peri_scribe.fires.index.ClassificationRecorder(
        classification=peri_scribe.models.FireClassification(
            classification=peri_scribe.models.BorderClassification.OUTSIDE_CALIFORNIA,
            outside_area_fraction=1.0,
            inside_area_fraction=0.0,
        ),
    )
    monkeypatch.setattr(
        peri_scribe.fires.classification,
        "classify_fire_sources",
        recorder.classify,
    )
    with (
        peri_scribe.execution.sharing(),
        spatial_data.product_cache.scope(tmp_path / "products.sqlite", "context"),
    ):
        prepared = peri_scribe.fires.sources.prepare_fire_sources(tmp_path / "sources")
        peri_scribe.fires.index.classifications_for_prepared_sources(tmp_path, prepared)
    recorder.calls.clear()
    if change == "source":
        rows = history_inputs[0].rows
        history_inputs[0] = dataclasses.replace(
            history_inputs[0],
            rows=(dataclasses.replace(rows[0], attributes={"revision": 2}), *rows[1:]),
        )
    elif change == "boundary":
        boundary = peri_scribe.sources.administrative_boundaries.output_geopackage_path(
            tmp_path,
        )
        boundary.parent.mkdir(parents=True)
        boundary.write_bytes(b"changed boundary")
    with (
        peri_scribe.execution.sharing(),
        spatial_data.product_cache.scope(
            tmp_path / "products.sqlite",
            "changed" if change == "context" else "context",
        ),
    ):
        prepared = peri_scribe.fires.sources.prepare_fire_sources(tmp_path / "sources")
        peri_scribe.fires.index.classifications_for_prepared_sources(tmp_path, prepared)

    assert recorder.calls == [("First",) if change == "source" else ("First", "Second")]


def test_classifications_for_prepared_sources_keeps_unavailable_results_uncached(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    history_inputs: list[peri_scribe.fires.sources.ReadFireSources],
) -> None:
    recorder = tests.helpers.doubles.peri_scribe.fires.index.ClassificationRecorder(
        classification=None,
    )
    monkeypatch.setattr(
        peri_scribe.fires.classification,
        "classify_fire_sources",
        recorder.classify,
    )
    prepared = peri_scribe.fires.sources.prepare_fire_sources(tmp_path / "sources")
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "context"):
        for _iteration in range(2):
            assert (
                peri_scribe.fires.index.classifications_for_prepared_sources(
                    tmp_path,
                    prepared,
                )
                == {}
            )

    assert recorder.calls == [("First", "Second"), ("First", "Second")]


def test_classifications_for_prepared_sources_preserves_uncached_operation(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    history_inputs: list[peri_scribe.fires.sources.ReadFireSources],
) -> None:
    recorder = tests.helpers.doubles.peri_scribe.fires.index.ClassificationRecorder(
        classification=None,
    )
    monkeypatch.setattr(
        peri_scribe.fires.classification,
        "classify_fire_sources",
        recorder.classify,
    )
    prepared = peri_scribe.fires.sources.prepare_fire_sources(tmp_path / "sources")
    peri_scribe.fires.index.classifications_for_prepared_sources(tmp_path, prepared)

    assert recorder.calls == [("First", "Second")]


@pytest.mark.parametrize(
    "payload",
    [None, b"invalid json", b'{"classification": "bad"}'],
)
def test_cached_classification_ignores_missing_or_invalid_products(
    tmp_path: pathlib.Path,
    payload: bytes | None,
) -> None:
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "context"):
        if payload is not None:
            spatial_data.product_cache.put(
                peri_scribe.fires.index.CLASSIFICATION_NAMESPACE,
                "key",
                payload,
            )

        assert peri_scribe.fires.index.cached_classification("key") is None
