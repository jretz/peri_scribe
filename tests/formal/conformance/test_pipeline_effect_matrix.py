"""Keep byte-level and physical evidence for composed pipeline execution."""

import dataclasses
import os
import pathlib
import types

import pytest
import structlog.testing

import peri_scribe.durable_file
import peri_scribe.pipeline_state
import peri_scribe.sources.fetch_control
import tests.formal.helpers.oracle
import tests.formal.helpers.pipeline_batch_checks
import tests.formal.helpers.pipeline_batches
import tests.formal.helpers.pipeline_composition
import tests.formal.helpers.pipeline_effect_matrix
import tests.formal.helpers.pipeline_file_footprint
import tests.formal.helpers.pipeline_ordered_binding
import tests.formal.helpers.pipeline_ordered_replay
import tests.formal.helpers.pipeline_replay_files
import tests.helpers.doubles.peri_scribe.pipeline_fetch_recovery


files = tests.formal.helpers.pipeline_replay_files
matrix = tests.formal.helpers.pipeline_effect_matrix
footprint = tests.formal.helpers.pipeline_file_footprint
ordered = tests.formal.helpers.pipeline_ordered_replay
ordered_binding = tests.formal.helpers.pipeline_ordered_binding


def test_replay_memory_matches_ordered_physical_execution(
    tmp_path: pathlib.Path,
    pipeline_executions: tests.formal.helpers.pipeline_composition.Executions,
    pipeline_batches: tuple[
        tuple[tests.formal.helpers.pipeline_batches.Branch, ...],
        ...,
    ],
) -> None:
    selected = max(
        pipeline_batches,
        key=lambda batch: len(
            tuple(tests.formal.helpers.pipeline_batches.histories(batch)),
        ),
    )
    qualified = ordered_binding.resolve()
    if qualified is not None and ordered.compare(
        selected,
        tmp_path / "qualified",
        pipeline_executions.checked,
        qualified,
    ):
        return
    physical_trace: dict[
        tuple[tests.formal.helpers.pipeline_composition.Invocation, ...],
        list[files.Event],
    ] = {}
    memory_trace: dict[
        tuple[tests.formal.helpers.pipeline_composition.Invocation, ...],
        list[files.Event],
    ] = {}
    physical = tests.formal.helpers.pipeline_batches.replay(
        selected,
        tmp_path / "physical",
        pipeline_executions.checked,
        traces=physical_trace,
    )
    virtual = tests.formal.helpers.pipeline_batches.replay_memory(
        selected,
        tmp_path / "memory",
        pipeline_executions.checked,
        {},
        traces=memory_trace,
    )
    expected = set(tests.formal.helpers.pipeline_batches.histories(selected))
    assert set(physical) == expected
    assert physical == virtual
    assert physical_trace == memory_trace


def test_ordered_admission_rejects_changed_fixture_source(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert ordered_binding.source_matches(files)
    original = pathlib.Path(files.__file__).read_text(encoding="utf-8")
    source = tmp_path / "pipeline_replay_files.py"
    source.write_text(
        original.replace("return self.entry().content", "return b'other'"),
        encoding="utf-8",
    )
    monkeypatch.setattr(files, "__file__", str(source))
    monkeypatch.setattr(
        footprint,
        "resolve",
        lambda *_args: pytest.fail("changed ordered source reached the proof oracle"),
    )
    assert not ordered_binding.source_matches(files)
    assert ordered_binding.resolve() is None


@pytest.mark.parametrize(
    ("owner", "name"),
    [
        (peri_scribe.durable_file.LocalFile, "read_bytes"),
        (tests.formal.helpers.pipeline_composition.Replay, "inspect"),
    ],
)
def test_ordered_admission_rejects_live_reader_and_observer_overrides(
    monkeypatch: pytest.MonkeyPatch,
    owner: type[object],
    name: str,
) -> None:
    monkeypatch.setattr(owner, name, lambda *_args: b"changed")
    assert ordered_binding.resolve() is None


@pytest.mark.parametrize(
    ("module", "name"),
    [
        (peri_scribe.pipeline_state, "required_state"),
        (peri_scribe.pipeline_state, "completed_state"),
        (peri_scribe.sources.fetch_control, "restore_previous_state"),
        (peri_scribe.sources.fetch_control, "proceed_without_pending"),
    ],
)
def test_ordered_admission_rejects_policy_code_outside_reviewed_source(
    monkeypatch: pytest.MonkeyPatch,
    module: types.ModuleType,
    name: str,
) -> None:
    monkeypatch.setattr(module, name, lambda *_args: None)
    assert not ordered_binding.source_matches(module)
    assert ordered_binding.resolve() is None


@pytest.mark.parametrize("corruption", ["change", "drop"])
def test_ordered_frame_rejects_changed_or_missing_read(corruption: str) -> None:
    invocation = tests.formal.helpers.pipeline_batch_checks.invocations()[0]
    image = (files.Entry(content=b"1"), *(None,) * (len(files.FILES) - 1))
    read = files.Read(
        reader=files.Reader.FIXTURE,
        kind=files.ReadKind.BYTES,
        name=files.FILES[0],
        value=b"1",
        number=0,
    )
    tape: list[files.Event] = [
        read,
        files.Calls(stages=(), forces=()),
        files.ReadCount(total=1),
    ]
    prior = ordered.Prefix(image=image)
    certificate = footprint.Footprint(transfers=())
    assert ordered.verify_tape(prior, invocation, tape, certificate).image == image
    if corruption == "change":
        tape[0] = dataclasses.replace(read, value=b"2")
    else:
        del tape[0]
    with pytest.raises(AssertionError):
        ordered.verify_tape(prior, invocation, tape, certificate)


def pending_replacement() -> tuple[files.Effect, files.Image]:
    """Keep a source generation present while replacing the pending marker.

    Returns:
        One marker replacement and its exact modeled after-image.
    """
    payload = peri_scribe.pipeline_state.PendingRun().model_dump_json().encode()
    before: list[files.Entry | None] = [None] * len(files.FILES)
    before[files.FILE_INDEX["source-generation"]] = files.Entry(content=b"1")
    effect = files.Effect(
        before=tuple(before),
        maps_present=False,
        operation=files.Operation.REPLACE,
        name=matrix.PENDING,
        argument=payload,
    )
    before[files.FILE_INDEX[matrix.PENDING]] = files.Entry(content=payload)
    return effect, tuple(before)


def test_verify_effect_rejects_wrong_marker_reply_conditioned_on_source_bytes(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    year = tmp_path / "2026"
    effect, after = pending_replacement()
    original = peri_scribe.durable_file.LocalFile.read_bytes

    def stale_read(file: peri_scribe.durable_file.LocalFile) -> bytes:
        """Read a stale marker only when the modeled sibling source exists.

        Returns:
            The original bytes or a different valid pending marker.
        """
        content = original(file)
        if file.path == year / matrix.PENDING and (year / "source-generation").exists():
            return b'{"unconditional":true}'
        return content

    monkeypatch.setattr(peri_scribe.durable_file.LocalFile, "read_bytes", stale_read)
    with pytest.raises(AssertionError, match=r"read disagrees.*run_state"):
        matrix.verify_effect(year, effect, after)


def test_verify_effect_rejects_sibling_write_conditioned_on_source_bytes(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    year = tmp_path / "2026"
    effect, after = pending_replacement()
    original = pathlib.Path.replace

    def scribble(path: pathlib.Path, target: pathlib.Path) -> pathlib.Path:
        """Corrupt a sibling only when the real source contains the selected value.

        Returns:
            The result of the actual target replacement.
        """
        result = original(path, target)
        if (year / "source-generation").read_bytes() == b"1":
            (year / matrix.SIBLING).write_bytes(b"changed")
        return result

    monkeypatch.setattr(pathlib.Path, "replace", scribble)
    with pytest.raises(AssertionError, match="physical frame changed"):
        matrix.verify_effect(year, effect, after)


def test_verify_effect_rejects_restored_sibling_write(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    year = tmp_path / "2026"
    effect, after = pending_replacement()
    original = pathlib.Path.replace

    def scribble(path: pathlib.Path, target: pathlib.Path) -> pathlib.Path:
        """Restore bytes and metadata so only the ordered operation trace can fail.

        Returns:
            The result of the actual target replacement.
        """
        result = original(path, target)
        sibling = year / matrix.SIBLING
        content, status = sibling.read_bytes(), sibling.stat()
        sibling.write_bytes(b"changed")
        sibling.write_bytes(content)
        os.utime(sibling, ns=(status.st_atime_ns, status.st_mtime_ns))
        return result

    monkeypatch.setattr(pathlib.Path, "replace", scribble)
    with pytest.raises(AssertionError, match="unexpected durable mutations"):
        matrix.verify_effect(year, effect, after)


def test_unknown_adapter_source_keeps_complete_physical_matrix(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "durable_file.py"
    source.write_text(
        footprint.ADAPTER.replace(
            "            temporary.replace(self.path)",
            "            temporary.replace(self.path)\n"
            '            (self.path.parent / "sibling").touch()',
        ),
    )
    monkeypatch.setattr(peri_scribe.durable_file, "__file__", str(source))
    monkeypatch.setattr(footprint, "current_oracle", lambda: True)
    monkeypatch.setattr(
        tests.formal.helpers.oracle,
        "evaluate",
        lambda _commands: pytest.fail("unrecognized source reached the proof oracle"),
    )
    effect, after = pending_replacement()
    matrix.check_effects({effect: after}, tmp_path)
    receipts = tmp_path / "pipeline-effect-checks"
    assert len(list(receipts.glob("full-*.json"))) == 1
    assert len(list(receipts.glob("fault-*.json"))) == 1
    assert not list(receipts.glob("footprint-*.json"))


def test_live_primitive_change_keeps_conditional_sibling_assertion(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    effect, after = pending_replacement()
    original = pathlib.Path.replace

    def scribble(path: pathlib.Path, target: pathlib.Path) -> pathlib.Path:
        """Corrupt a sibling only when the source fixture contains the trigger.

        Returns:
            The result of the actual target replacement.
        """
        result = original(path, target)
        if (
            target.name == matrix.PENDING
            and (target.parent / "source-generation").read_bytes() == b"1"
        ):
            (target.parent / matrix.SIBLING).write_bytes(b"changed")
        return result

    monkeypatch.setattr(footprint, "current_oracle", lambda: True)
    monkeypatch.setattr(
        tests.formal.helpers.oracle,
        "evaluate",
        lambda _commands: pytest.fail("changed primitive reached the proof oracle"),
    )
    monkeypatch.setattr(pathlib.Path, "replace", scribble)
    with pytest.raises(AssertionError, match="physical frame changed"):
        matrix.check_effects({effect: after}, tmp_path)


@pytest.mark.parametrize(
    "error",
    [OSError, tests.helpers.doubles.peri_scribe.pipeline_fetch_recovery.ProcessLoss],
)
@pytest.mark.parametrize("after_write", [False, True])
def test_verify_effect_cleans_interrupted_staging_write(
    tmp_path: pathlib.Path,
    error: type[BaseException],
    *,
    after_write: bool,
) -> None:
    effect, after = pending_replacement()
    matrix.verify_effect(
        tmp_path / "2026",
        effect,
        after,
        fault=matrix.Fault(error=error, after=after_write, staging=True),
    )


@pytest.mark.parametrize(
    "encoded",
    [
        b"",
        b"{",
        b"[]",
        b"\xff",
        b'{"version":0}',
        b'{"unknown":true}',
        b'{"remaining":["reports","kmz"]}',
        b'{"remaining":["score","score"]}',
        b'{"remaining":["fetch"]}',
    ],
)
def test_compare_pending_invalid_bytes_require_complete_rebuild(
    tmp_path: pathlib.Path,
    encoded: bytes,
) -> None:
    with structlog.testing.capture_logs():
        observed = matrix.compare_pending(
            tmp_path / "2026",
            files.Entry(content=encoded),
        )
    assert observed == peri_scribe.pipeline_state.PendingRun(
        remaining=peri_scribe.pipeline_state.DERIVED_STAGES,
        unconditional=True,
    )


def test_compare_pending_accepts_legacy_marker(
    tmp_path: pathlib.Path,
) -> None:
    observed = matrix.compare_pending(
        tmp_path / "2026",
        files.Entry(content=b'{"unconditional":true}'),
    )
    assert observed == peri_scribe.pipeline_state.PendingRun(unconditional=True)


@pytest.mark.parametrize("encoded", matrix.invalid_publications())
def test_compare_publication_invalid_checkpoint_cannot_authorize_skip(
    tmp_path: pathlib.Path,
    encoded: bytes,
) -> None:
    with structlog.testing.capture_logs():
        matrix.compare_publication(tmp_path, files.Entry(content=encoded), None)
