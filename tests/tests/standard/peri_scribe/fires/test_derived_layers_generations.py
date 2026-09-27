"""Readers reject the interrupted full/differential publication window."""

import concurrent.futures
import contextlib
import contextvars
import pathlib

import pytest

import peri_scribe.fires.derived_layers
import peri_scribe.fires.differential
import peri_scribe.fires.files
import peri_scribe.fires.reuse
import peri_scribe.pipeline_state
import tests.helpers.doubles.peri_scribe.fires.derived_layers
import tests.helpers.factories.peri_scribe.fires.derived_layers


def test_read_derived_layers_rejects_mixed_generation_after_interrupted_publication(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(peri_scribe.fires.reuse, "derivation_context", lambda _: "test")
    tests.helpers.factories.peri_scribe.fires.derived_layers.publish_pair(tmp_path, 1)
    tests.helpers.factories.peri_scribe.fires.derived_layers.publish_full(tmp_path, 2)
    with pytest.raises(RuntimeError, match="geography"):
        peri_scribe.fires.derived_layers.read_derived_layers(
            tmp_path,
            tolerate_missing=False,
        )


def test_read_derived_layers_refuses_another_writer(
    tmp_path: pathlib.Path,
) -> None:
    with peri_scribe.pipeline_state.run_lock(tmp_path) as writer:
        assert writer
        with pytest.raises(RuntimeError, match="writer owns"):
            contextvars.Context().run(
                peri_scribe.fires.derived_layers.read_derived_layers,
                tmp_path,
                tolerate_missing=True,
            )


def test_read_derived_layers_rejects_expired_inherited_writer_ownership(
    tmp_path: pathlib.Path,
) -> None:
    with peri_scribe.pipeline_state.run_lock(tmp_path) as writer:
        assert writer
        inherited = contextvars.copy_context()
    with peri_scribe.pipeline_state.run_lock(tmp_path) as writer:
        assert writer
        with pytest.raises(RuntimeError, match="writer owns"):
            inherited.run(
                peri_scribe.fires.derived_layers.read_derived_layers,
                tmp_path,
                tolerate_missing=True,
            )


@pytest.mark.parametrize(
    "damage",
    [
        "missing-full",
        "missing-differential",
        "full-signature",
        "diff-signature",
        "no-key",
    ],
)
def test_read_derived_layers_rejects_incomplete_or_unauthenticated_pairs(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    damage: str,
) -> None:
    monkeypatch.setattr(peri_scribe.fires.reuse, "derivation_context", lambda _: "test")
    tests.helpers.factories.peri_scribe.fires.derived_layers.publish_pair(tmp_path, 1)
    full = peri_scribe.fires.files.history_geopackage_path(tmp_path)
    differential = peri_scribe.fires.differential.differential_geopackage_path(tmp_path)
    if damage == "missing-full":
        full.unlink()
    elif damage == "missing-differential":
        differential.unlink()
    elif damage == "full-signature":
        peri_scribe.fires.reuse.signature_path(full).unlink()
    elif damage == "diff-signature":
        peri_scribe.fires.reuse.signature_path(differential).unlink()
    else:
        signature = peri_scribe.fires.reuse.validated_signature(differential)
        assert signature is not None
        peri_scribe.fires.reuse.signature_path(differential).write_text(
            signature.model_copy(update={"generation": None}).model_dump_json(),
        )
    with pytest.raises((RuntimeError, FileNotFoundError)):
        peri_scribe.fires.derived_layers.read_derived_layers(
            tmp_path,
            tolerate_missing=True,
        )


def test_read_derived_layers_allows_owner_and_excludes_writers_between_layers(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(peri_scribe.fires.reuse, "derivation_context", lambda _: "test")
    tests.helpers.factories.peri_scribe.fires.derived_layers.publish_pair(tmp_path, 1)
    recorder = tests.helpers.doubles.peri_scribe.fires.derived_layers.LockedReader(
        directory=tmp_path,
        original=peri_scribe.fires.reuse.read_published_layer,
    )
    monkeypatch.setattr(peri_scribe.fires.reuse, "read_published_layer", recorder.read)
    for owner in (False, True):
        context = (
            peri_scribe.pipeline_state.run_lock(tmp_path)
            if owner
            else contextlib.nullcontext(enter_result=True)
        )
        with context as acquired:
            assert acquired
            layers = peri_scribe.fires.derived_layers.read_derived_layers(
                tmp_path,
                tolerate_missing=False,
            )
        for frame in (
            layers.perimeters,
            layers.points,
            layers.incidents,
            layers.differential_perimeters,
        ):
            assert frame.revision.tolist() == [1]
    expected_layer_reads = 8
    assert recorder.calls == expected_layer_reads


def test_read_derived_layers_rejects_writer_ownership_copied_to_worker_thread(
    tmp_path: pathlib.Path,
) -> None:
    with (
        peri_scribe.pipeline_state.run_lock(tmp_path) as writer,
        concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor,
    ):
        assert writer
        inherited = contextvars.copy_context()
        result = executor.submit(
            inherited.run,
            peri_scribe.fires.derived_layers.read_derived_layers,
            tmp_path,
            tolerate_missing=True,
        )
        with pytest.raises(RuntimeError, match="writer owns"):
            result.result()
