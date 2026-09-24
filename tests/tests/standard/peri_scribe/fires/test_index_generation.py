"""Whole index reuse requires complete classification and authenticated output."""

from __future__ import annotations

import pathlib

import pytest

import peri_scribe.fires.classification
import peri_scribe.fires.index
import peri_scribe.fires.sources
import peri_scribe.models
import peri_scribe.preparation
import peri_scribe.sources.snapshots
import spatial_data.product_cache
import tests.helpers.doubles.errors
import tests.helpers.doubles.peri_scribe.fires.index


def test_index_fire_sources_skips_all_parsing_for_authenticated_generation(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    history_inputs: list[peri_scribe.fires.sources.ReadFireSources],
) -> None:
    recorder = tests.helpers.doubles.peri_scribe.fires.index.ClassificationRecorder(
        classification=peri_scribe.models.FireClassification(
            classification=peri_scribe.models.BorderClassification.INSIDE_CALIFORNIA,
            outside_area_fraction=0.0,
            inside_area_fraction=1.0,
        ),
    )
    monkeypatch.setattr(
        peri_scribe.fires.classification,
        "classify_fire_sources",
        recorder.classify,
    )
    peri_scribe.fires.index.index_fire_sources(tmp_path)
    path = peri_scribe.sources.snapshots.fire_index_path(tmp_path)
    before = (path.read_bytes(), path.stat().st_mtime_ns)
    monkeypatch.setattr(
        peri_scribe.fires.sources,
        "prepare_fire_sources",
        tests.helpers.doubles.errors.raising_stub(AssertionError("Repeated parsing")),
    )
    peri_scribe.fires.index.index_fire_sources(tmp_path)
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before


@pytest.mark.parametrize(
    "change",
    ["missing", "edited", "generation", "corrupt", "bypass"],
)
def test_generation_matches_rejects_unvalidated_index(
    tmp_path: pathlib.Path,
    change: str,
) -> None:
    path = peri_scribe.sources.snapshots.fire_index_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"published")
    with peri_scribe.preparation.scope(tmp_path):
        spatial_data.product_cache.put(
            peri_scribe.fires.index.GENERATION_NAMESPACE,
            "current",
            peri_scribe.fires.index.generation_signature(path, "first"),
        )
    if change == "missing":
        path.unlink()
    elif change == "edited":
        path.write_bytes(b"modified")
    with peri_scribe.preparation.scope(tmp_path, unconditional=change == "bypass"):
        if change == "corrupt":
            spatial_data.product_cache.put(
                peri_scribe.fires.index.GENERATION_NAMESPACE,
                "current",
                b"malformed",
            )
        assert not peri_scribe.fires.index.generation_matches(
            tmp_path,
            "changed" if change == "generation" else "first",
        )


def test_index_fire_sources_retries_incomplete_classification(
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
    peri_scribe.fires.index.index_fire_sources(tmp_path)
    peri_scribe.fires.index.index_fire_sources(tmp_path)
    assert recorder.calls == [("First", "Second"), ("First", "Second")]
