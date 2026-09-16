"""Recovery requirements survive failures and respect stage ordering."""

import pathlib
import tempfile

import hypothesis
import pytest

import peri_scribe.pipeline_stages
import peri_scribe.pipeline_state
import tests.peri_scribe.pipeline_state_helpers


@hypothesis.given(actions=tests.peri_scribe.pipeline_state_helpers.run_actions())
def test_complete_stage_matches_recovery_model_after_generated_actions(
    actions: list[tests.peri_scribe.pipeline_state_helpers.RunAction],
) -> None:
    order = peri_scribe.pipeline_state.DERIVED_STAGES
    pending: set[peri_scribe.pipeline_stages.Stage] = set()
    unconditional = False
    with tempfile.TemporaryDirectory() as directory:
        year_directory = pathlib.Path(directory)
        for action in actions:
            if action.require:
                peri_scribe.pipeline_state.require_stages(
                    year_directory,
                    (action.stage,),
                    unconditional=action.unconditional,
                )
                pending.add(action.stage)
                unconditional |= action.unconditional
            else:
                peri_scribe.pipeline_state.complete_stage(year_directory, action.stage)
                if pending and action.stage == min(pending, key=order.index):
                    pending.remove(action.stage)
                    unconditional &= bool(pending)
            state = peri_scribe.pipeline_state.read_state(year_directory)
            assert state.remaining == tuple(sorted(pending, key=order.index))
            assert state.unconditional == unconditional


def test_read_state_starts_without_pending_work(tmp_path: pathlib.Path) -> None:
    assert not peri_scribe.pipeline_state.read_state(tmp_path).remaining


@pytest.mark.parametrize(
    "content",
    [
        b"broken",
        b"\xff",
        b'{"version":2}',
        b'{"unknown":true}',
        b'{"remaining":["kmz","geography"]}',
        b'{"remaining":["geography","geography"]}',
        b'{"remaining":["unknown"]}',
    ],
)
def test_read_state_recovers_invalid_markers(
    tmp_path: pathlib.Path,
    content: bytes,
) -> None:
    peri_scribe.pipeline_state.state_path(tmp_path).write_bytes(content)
    state = peri_scribe.pipeline_state.read_state(tmp_path)
    assert state.remaining == peri_scribe.pipeline_state.DERIVED_STAGES
    assert state.unconditional


def test_require_stages_preserves_force_and_reinvalidates_prerequisites(
    tmp_path: pathlib.Path,
) -> None:
    peri_scribe.pipeline_state.require_stages(
        tmp_path,
        (
            peri_scribe.pipeline_stages.Stage.KMZ,
            peri_scribe.pipeline_stages.Stage.REPORTS,
        ),
        unconditional=True,
    )
    peri_scribe.pipeline_state.require_stages(
        tmp_path,
        (
            peri_scribe.pipeline_stages.Stage.GEOGRAPHY,
            peri_scribe.pipeline_stages.Stage.SCORE,
        ),
    )
    state = peri_scribe.pipeline_state.read_state(tmp_path)
    assert state.remaining == peri_scribe.pipeline_state.DERIVED_STAGES
    assert state.unconditional


def test_complete_stage_requires_prerequisites(tmp_path: pathlib.Path) -> None:
    peri_scribe.pipeline_state.require_stages(
        tmp_path,
        (
            peri_scribe.pipeline_stages.Stage.GEOGRAPHY,
            peri_scribe.pipeline_stages.Stage.KMZ,
        ),
        unconditional=True,
    )
    peri_scribe.pipeline_state.complete_stage(
        tmp_path,
        peri_scribe.pipeline_stages.Stage.KMZ,
    )
    assert peri_scribe.pipeline_state.read_state(tmp_path).remaining == (
        "geography",
        "kmz",
    )
    peri_scribe.pipeline_state.complete_stage(
        tmp_path,
        peri_scribe.pipeline_stages.Stage.GEOGRAPHY,
    )
    assert peri_scribe.pipeline_state.read_state(tmp_path).unconditional
    peri_scribe.pipeline_state.complete_stage(
        tmp_path,
        peri_scribe.pipeline_stages.Stage.KMZ,
    )
    assert (
        peri_scribe.pipeline_state.read_state(tmp_path)
        == peri_scribe.pipeline_state.PendingRun()
    )
    peri_scribe.pipeline_state.complete_stage(
        tmp_path,
        peri_scribe.pipeline_stages.Stage.REPORTS,
    )


def test_run_lock_excludes_another_writer_and_releases_on_failure(
    tmp_path: pathlib.Path,
) -> None:

    interrupted_run = (
        tests.peri_scribe.pipeline_state_helpers.make_interrupted_locked_run(
            tmp_path=tmp_path,
        )
    )

    with pytest.raises(ValueError, match="interrupted"):
        interrupted_run()
    with peri_scribe.pipeline_state.run_lock(tmp_path) as retry:
        assert retry


def test_write_state_retains_previous_marker_when_publish_fails(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = peri_scribe.pipeline_state.PendingRun(
        remaining=(peri_scribe.pipeline_stages.Stage.GEOGRAPHY,),
        unconditional=True,
    )
    peri_scribe.pipeline_state.write_state(tmp_path, original)

    fail_replace = tests.peri_scribe.pipeline_state_helpers.fail_marker_replacement

    monkeypatch.setattr(pathlib.Path, "replace", fail_replace)
    with pytest.raises(OSError, match="interrupted"):
        peri_scribe.pipeline_state.write_state(
            tmp_path,
            peri_scribe.pipeline_state.PendingRun(),
        )
    assert peri_scribe.pipeline_state.read_state(tmp_path) == original
