"""Standalone partial rebuilds carry forward only authenticated classification proof."""

from __future__ import annotations

import dataclasses
import pathlib

import pytest

import peri_scribe.fires.classification
import peri_scribe.fires.files
import peri_scribe.fires.generation
import peri_scribe.fires.history
import peri_scribe.fires.reuse
import peri_scribe.fires.sources
import peri_scribe.models
import spatial_data.layers
import tests.helpers.doubles.errors
import tests.helpers.doubles.peri_scribe.fires.index


@pytest.mark.parametrize("available", [False, True])
def test_write_history_of_full_geography_partial_rebuild_keeps_classification_proof(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    classified_history_inputs: list[peri_scribe.fires.sources.ReadFireSources],
    *,
    available: bool,
) -> None:
    generation = ["initial"]
    monkeypatch.setattr(
        peri_scribe.fires.generation,
        "source_key",
        lambda _year: generation[0],
    )
    path = peri_scribe.fires.files.write_history_of_full_geography(tmp_path)
    read = classified_history_inputs[0]
    classified_history_inputs[0] = dataclasses.replace(
        read,
        rows=(
            dataclasses.replace(
                read.rows[0],
                attributes={
                    **read.rows[0].attributes,
                    "attr_EstimatedCostToDate": 2000,
                },
            ),
            *read.rows[1:],
        ),
    )
    generation[0] = "changed"
    recorder = tests.helpers.doubles.peri_scribe.fires.index.ClassificationRecorder(
        classification=(
            peri_scribe.models.FireClassification(
                classification=peri_scribe.models.BorderClassification.INSIDE_CALIFORNIA,
                outside_area_fraction=0.0,
                inside_area_fraction=1.0,
            )
            if available
            else None
        ),
    )
    monkeypatch.setattr(
        peri_scribe.fires.classification,
        "classify_fire_sources",
        recorder.classify,
    )

    peri_scribe.fires.files.write_history_of_full_geography(tmp_path)

    assert recorder.calls == [("First",)]
    signature = peri_scribe.fires.reuse.validated_signature(path)
    assert signature is not None
    assert signature.generation == ("changed" if available else None)
    original = (path.read_bytes(), path.stat().st_mtime_ns)
    monkeypatch.setattr(
        peri_scribe.fires.sources,
        "read_fire_sources",
        tests.helpers.doubles.errors.raising_stub(
            AssertionError("Repeated source read"),
        ),
    )
    if available:
        assert peri_scribe.fires.files.write_history_of_full_geography(tmp_path) == path
    else:
        with pytest.raises(AssertionError, match="Repeated source read"):
            peri_scribe.fires.files.write_history_of_full_geography(tmp_path)
    assert (path.read_bytes(), path.stat().st_mtime_ns) == original


def test_write_history_of_full_geography_recovers_unclassified_reused_histories(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    history_inputs: list[peri_scribe.fires.sources.ReadFireSources],
) -> None:
    path = peri_scribe.fires.files.write_history_of_full_geography(tmp_path)
    original = spatial_data.layers.read_layer(
        path,
        peri_scribe.fires.files.PERIMETER_LAYER_NAME,
    )
    assert original.border_classification.isna().all()
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

    peri_scribe.fires.files.write_history_of_full_geography(tmp_path)

    assert recorder.calls == [("First", "Second")]
    recovered = spatial_data.layers.read_layer(
        path,
        peri_scribe.fires.files.PERIMETER_LAYER_NAME,
    )
    assert set(recovered.border_classification) == {"inside_california"}
    assert len(recovered) == len(original)
    signature = peri_scribe.fires.reuse.validated_signature(path)
    assert signature is not None
    assert signature.generation is not None
    monkeypatch.setattr(
        peri_scribe.fires.sources,
        "read_fire_sources",
        tests.helpers.doubles.errors.raising_stub(
            AssertionError("Repeated source read"),
        ),
    )
    assert peri_scribe.fires.files.write_history_of_full_geography(tmp_path) == path


def test_write_history_of_full_geography_keeps_failed_classification_retryable(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    history_inputs: list[peri_scribe.fires.sources.ReadFireSources],
) -> None:
    path = peri_scribe.fires.files.write_history_of_full_geography(tmp_path)
    recorder = tests.helpers.doubles.peri_scribe.fires.index.ClassificationRecorder(
        classification=None,
    )
    monkeypatch.setattr(
        peri_scribe.fires.classification,
        "classify_fire_sources",
        recorder.classify,
    )
    monkeypatch.setattr(
        peri_scribe.fires.history,
        "history_rows_for_fire",
        tests.helpers.doubles.errors.raising_stub(AssertionError("Unchanged history")),
    )

    peri_scribe.fires.files.write_history_of_full_geography(tmp_path)

    assert recorder.calls == [("First", "Second")]
    signature = peri_scribe.fires.reuse.validated_signature(path)
    assert signature is not None
    assert signature.generation is None


@pytest.mark.parametrize("damage", ["missing", "incomplete", "layers", "checksum"])
def test_classified_reused_fires_requires_complete_authenticated_history(
    tmp_path: pathlib.Path,
    classified_history_inputs: list[peri_scribe.fires.sources.ReadFireSources],
    damage: str,
) -> None:
    path = peri_scribe.fires.files.write_history_of_full_geography(tmp_path)
    metadata = peri_scribe.fires.reuse.signature_path(path)
    signature = peri_scribe.fires.reuse.validated_signature(path)
    assert signature is not None
    if damage == "missing":
        metadata.unlink()
    elif damage == "checksum":
        path.write_bytes(b"unverified output")
    else:
        field, value = (
            ("generation", None) if damage == "incomplete" else ("layers", ())
        )
        metadata.write_text(
            signature.model_copy(update={field: value}).model_dump_json(),
        )

    assert peri_scribe.fires.files.classified_reused_fires(path, {1}) == frozenset()
