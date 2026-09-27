"""Input mutation cannot outrun the persistent requirement to rebuild its outputs."""

from __future__ import annotations

import datetime
import pathlib

import pytest

import peri_scribe.pipeline
import peri_scribe.pipeline_stages
import peri_scribe.pipeline_state
import tests.helpers.doubles.peri_scribe.pipeline_fetch_recovery


@pytest.mark.parametrize(
    "mutation",
    list(tests.helpers.doubles.peri_scribe.pipeline_fetch_recovery.Mutation),
)
def test_run_fetch_stage_preserves_rebuild_after_process_loss(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: tests.helpers.doubles.peri_scribe.pipeline_fetch_recovery.Mutation,
) -> None:
    directory = tmp_path / "data" / "2026"
    scenario = tests.helpers.doubles.peri_scribe.pipeline_fetch_recovery.Scenario(
        directory=directory,
        changes=frozenset({mutation}),
        interrupt=mutation,
    )
    tests.helpers.doubles.peri_scribe.pipeline_fetch_recovery.install(
        monkeypatch,
        scenario,
    )
    with pytest.raises(
        tests.helpers.doubles.peri_scribe.pipeline_fetch_recovery.ProcessLoss,
    ):
        peri_scribe.pipeline.run_fetch_stage(
            directory,
            full_fetch_interval=None,
            unconditional=False,
        )
    assert scenario.path(mutation).is_file()
    assert peri_scribe.pipeline_state.read_state(directory).remaining == (
        peri_scribe.pipeline_state.DERIVED_STAGES
    )
    scenario.interrupt = None
    assert peri_scribe.pipeline.run_fetch_stage(
        directory,
        full_fetch_interval=None,
        unconditional=False,
    )


@pytest.mark.parametrize(
    "prior",
    [
        peri_scribe.pipeline_state.PendingRun(),
        peri_scribe.pipeline_state.PendingRun(
            remaining=(peri_scribe.pipeline_stages.Stage.REPORTS,),
        ),
        peri_scribe.pipeline_state.PendingRun(
            remaining=(peri_scribe.pipeline_stages.Stage.REPORTS,),
            unconditional=True,
        ),
        peri_scribe.pipeline_state.PendingRun(
            remaining=peri_scribe.pipeline_state.DERIVED_STAGES,
        ),
    ],
)
@pytest.mark.parametrize("force", [False, True])
def test_run_fetch_stage_unchanged_preserves_existing_recovery_requirements(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    prior: peri_scribe.pipeline_state.PendingRun,
    *,
    force: bool,
) -> None:
    directory = tmp_path / "data" / "2026"
    peri_scribe.pipeline_state.write_state(directory, prior)
    scenario = tests.helpers.doubles.peri_scribe.pipeline_fetch_recovery.Scenario(
        directory=directory,
    )
    tests.helpers.doubles.peri_scribe.pipeline_fetch_recovery.install(
        monkeypatch,
        scenario,
    )
    assert peri_scribe.pipeline.run_fetch_stage(
        directory,
        full_fetch_interval=None,
        unconditional=force,
    ) == (force or bool(prior.remaining))
    assert peri_scribe.pipeline_state.read_state(directory) == prior


def test_run_fetch_stage_unchanged_full_fetch_keeps_unconditional_rebuild(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = tmp_path / "data" / "2026"
    scenario = tests.helpers.doubles.peri_scribe.pipeline_fetch_recovery.Scenario(
        directory=directory,
    )
    tests.helpers.doubles.peri_scribe.pipeline_fetch_recovery.install(
        monkeypatch,
        scenario,
    )
    assert peri_scribe.pipeline.run_fetch_stage(
        directory,
        full_fetch_interval=datetime.timedelta(days=1),
        unconditional=False,
    )
    assert scenario.full_fetches == [True]
    assert peri_scribe.pipeline_state.read_state(directory) == (
        peri_scribe.pipeline_state.PendingRun(
            remaining=peri_scribe.pipeline_state.DERIVED_STAGES,
            unconditional=True,
        )
    )


@pytest.mark.parametrize(
    "mutation",
    list(tests.helpers.doubles.peri_scribe.pipeline_fetch_recovery.Mutation),
)
def test_run_fetch_stage_input_changes_require_all_derived_stages(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: tests.helpers.doubles.peri_scribe.pipeline_fetch_recovery.Mutation,
) -> None:
    directory = tmp_path / "data" / "2026"
    scenario = tests.helpers.doubles.peri_scribe.pipeline_fetch_recovery.Scenario(
        directory=directory,
        changes=frozenset({mutation}),
    )
    tests.helpers.doubles.peri_scribe.pipeline_fetch_recovery.install(
        monkeypatch,
        scenario,
    )
    assert peri_scribe.pipeline.run_fetch_stage(
        directory,
        full_fetch_interval=None,
        unconditional=False,
    )
    assert peri_scribe.pipeline_state.read_state(directory).remaining == (
        peri_scribe.pipeline_state.DERIVED_STAGES
    )


def test_run_fetch_stage_cannot_change_inputs_without_recovery_storage(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = tmp_path / "data" / "2026"
    scenario = tests.helpers.doubles.peri_scribe.pipeline_fetch_recovery.Scenario(
        directory=directory,
        changes=frozenset(
            tests.helpers.doubles.peri_scribe.pipeline_fetch_recovery.Mutation,
        ),
    )
    tests.helpers.doubles.peri_scribe.pipeline_fetch_recovery.install(
        monkeypatch,
        scenario,
    )
    monkeypatch.setattr(
        peri_scribe.pipeline_state,
        "write_state",
        tests.helpers.doubles.peri_scribe.pipeline_fetch_recovery.fail_state_write,
    )
    with pytest.raises(OSError, match="recovery state unavailable"):
        peri_scribe.pipeline.run_fetch_stage(
            directory,
            full_fetch_interval=None,
            unconditional=False,
        )
    assert scenario.calls == []
    assert not (directory / "sources").exists()


def test_run_fetch_stage_retains_recovery_when_unchanged_restoration_fails(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = tmp_path / "data" / "2026"
    prior = peri_scribe.pipeline_state.PendingRun(
        remaining=(peri_scribe.pipeline_stages.Stage.REPORTS,),
        unconditional=True,
    )
    peri_scribe.pipeline_state.write_state(directory, prior)
    scenario = tests.helpers.doubles.peri_scribe.pipeline_fetch_recovery.Scenario(
        directory=directory,
    )
    tests.helpers.doubles.peri_scribe.pipeline_fetch_recovery.install(
        monkeypatch,
        scenario,
    )
    with monkeypatch.context() as failure:
        tests.helpers.doubles.peri_scribe.pipeline_fetch_recovery.reject_restoration(
            failure,
            prior,
        )
        with pytest.raises(OSError, match="restoration unavailable"):
            peri_scribe.pipeline.run_fetch_stage(
                directory,
                full_fetch_interval=None,
                unconditional=False,
            )
    assert peri_scribe.pipeline_state.read_state(directory) == (
        peri_scribe.pipeline_state.PendingRun(
            remaining=peri_scribe.pipeline_state.DERIVED_STAGES,
            unconditional=True,
        )
    )
    assert peri_scribe.pipeline.run_fetch_stage(
        directory,
        full_fetch_interval=None,
        unconditional=False,
    )
