"""Domain projections represent progress, explicit skips, and incomplete evidence."""

import pytest

import peri_scribe.monitor.events
import peri_scribe.monitor.model
import peri_scribe.phases
import tests.helpers.factories.peri_scribe.monitor.events
from measurement_units import units


def test_append_records_keeps_overlapping_commands_separate() -> None:
    state = peri_scribe.monitor.model.append_records(
        peri_scribe.monitor.model.State(),
        (
            tests.helpers.factories.peri_scribe.monitor.events.record(
                "Starting command",
                command="run",
            ),
            tests.helpers.factories.peri_scribe.monitor.events.record(
                "Starting command",
                run_id="validation",
                command="validate-sources",
            ),
            tests.helpers.factories.peri_scribe.monitor.events.record(
                "Finished command",
                status="completed",
            ),
        ),
    )
    assert [(run.identifier, run.status) for run in state.runs] == [
        ("run-1", "completed"),
        ("validation", "open"),
    ]


def test_append_records_groups_unidentified_command_boundaries() -> None:
    original = peri_scribe.monitor.model.State()
    state = peri_scribe.monitor.model.append_records(
        original,
        ({"event": "Starting command", "command": "run"}, {"event": "Started work"}),
    )
    assert len(state.runs) == 1
    assert original.runs == ()


def test_append_records_bounds_retained_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(peri_scribe.monitor.model, "MAXIMUM_RUNS", 1)
    state = peri_scribe.monitor.model.append_records(
        peri_scribe.monitor.model.State(),
        tuple(
            tests.helpers.factories.peri_scribe.monitor.events.record(
                "Starting command",
                run_id=name,
            )
            for name in ("first", "second")
        ),
    )
    assert [run.identifier for run in state.runs] == ["second"]


def test_phase_tree_starts_with_all_phases_waiting() -> None:
    run = tests.helpers.factories.peri_scribe.monitor.events.run(
        tests.helpers.factories.peri_scribe.monitor.events.record(
            "Starting command",
            command="run",
            parameters={"publish_threshold": "25 acres"},
        ),
    )
    tree = peri_scribe.monitor.model.phase_tree(
        run,
        tests.helpers.factories.peri_scribe.monitor.events.BRANCHES,
    )
    assert all(phase.status == "waiting" for phase in tree.phases)


@pytest.mark.parametrize("phases", [None, "geography", {"geography": True}])
def test_phase_tree_ignores_malformed_skipped_phase_lists(phases: object) -> None:
    run = tests.helpers.factories.peri_scribe.monitor.events.run(
        tests.helpers.factories.peri_scribe.monitor.events.record(
            "Starting command",
            command="run",
        ),
        tests.helpers.factories.peri_scribe.monitor.events.record(
            "Skipped phases",
            phases=phases,
            reason="no changes",
        ),
    )
    tree = peri_scribe.monitor.model.phase_tree(
        run,
        tests.helpers.factories.peri_scribe.monitor.events.BRANCHES,
    )
    assert tree.phases
    assert all(phase.status == "waiting" for phase in tree.phases)
    assert tree.omissions == ()


def test_phase_tree_trims_gate_rejected_work_immediately() -> None:
    run = tests.helpers.factories.peri_scribe.monitor.events.run(
        tests.helpers.factories.peri_scribe.monitor.events.record(
            "Starting command",
            command="run",
        ),
        tests.helpers.factories.peri_scribe.monitor.events.record(
            "Publication gate skipped",
            reason="timer not due",
        ),
    )
    tree = peri_scribe.monitor.model.phase_tree(
        run,
        tests.helpers.factories.peri_scribe.monitor.events.BRANCHES,
    )
    assert all(phase.path[0].phase == "fetch" for phase in tree.phases)
    assert "timer not due" in tree.reasons[0]


def test_phase_tree_renders_unknown_observed_phases() -> None:
    path = (peri_scribe.phases.Segment(phase="unknown"),)
    run = tests.helpers.factories.peri_scribe.monitor.events.run(
        tests.helpers.factories.peri_scribe.monitor.events.record(
            "Starting phase",
            path=path,
        ),
    )
    tree = peri_scribe.monitor.model.phase_tree(run, peri_scribe.phases.Branches())
    assert tree.phases[0].path == path


def test_phase_tree_finished_run_has_no_waiting_phases() -> None:
    path = (peri_scribe.phases.Segment(phase="fetch"),)
    run = tests.helpers.factories.peri_scribe.monitor.events.run(
        tests.helpers.factories.peri_scribe.monitor.events.record(
            "Starting command",
            command="run",
        ),
        tests.helpers.factories.peri_scribe.monitor.events.record(
            "Starting phase",
            path=path,
        ),
        tests.helpers.factories.peri_scribe.monitor.events.record(
            "Finished phase",
            path=path,
            status="completed",
            duration={"value": 2, "units": "second"},
        ),
        tests.helpers.factories.peri_scribe.monitor.events.record(
            "Finished command",
            status="completed",
        ),
    )
    tree = peri_scribe.monitor.model.phase_tree(
        run,
        tests.helpers.factories.peri_scribe.monitor.events.BRANCHES,
    )
    assert [(phase.status, phase.duration) for phase in tree.phases] == [
        ("completed", 2 * units.seconds),
    ]


def test_phase_tree_retains_unfinished_work_when_command_failed() -> None:
    path = (peri_scribe.phases.Segment(phase="score"),)
    run = tests.helpers.factories.peri_scribe.monitor.events.run(
        tests.helpers.factories.peri_scribe.monitor.events.record(
            "Starting command",
            command="run",
        ),
        tests.helpers.factories.peri_scribe.monitor.events.record(
            "Starting phase",
            path=path,
        ),
        tests.helpers.factories.peri_scribe.monitor.events.record(
            "Finished command",
            status="failed",
        ),
    )
    tree = peri_scribe.monitor.model.phase_tree(run, peri_scribe.phases.Branches())
    assert tree.phases[0].status == "unfinished"
    assert tree.omissions[0].reason == "Not reached: command failed"


def test_phase_tree_trims_unentered_children_after_parent_completes() -> None:
    path = (peri_scribe.phases.Segment(phase="fetch"),)
    run = tests.helpers.factories.peri_scribe.monitor.events.run(
        tests.helpers.factories.peri_scribe.monitor.events.record(
            "Starting command",
            command="run",
        ),
        tests.helpers.factories.peri_scribe.monitor.events.record(
            "Finished phase",
            path=path,
            status="completed",
        ),
    )
    tree = peri_scribe.monitor.model.phase_tree(run, peri_scribe.phases.Branches())
    assert any("fetch completed" in omitted.reason for omitted in tree.omissions)


def test_phase_tree_honors_recorded_plan_and_stage_selection() -> None:
    run = tests.helpers.factories.peri_scribe.monitor.events.run(
        tests.helpers.factories.peri_scribe.monitor.events.record(
            "Starting command",
            command="run",
        ),
        tests.helpers.factories.peri_scribe.monitor.events.record(
            "Planned phases",
            gated=True,
            stages=["fetch"],
            branches={
                "feeds": ["recorded-feed"],
                "sources": ["zones"],
                "evacuations": "zones",
            },
        ),
    )
    tree = peri_scribe.monitor.model.phase_tree(run, peri_scribe.phases.Branches())
    assert any(phase.path[-1].branch == "recorded-feed" for phase in tree.phases)
    assert all(phase.path[0].phase == "fetch" for phase in tree.phases)


def test_phase_tree_retains_explicit_skip_reason() -> None:
    path = (peri_scribe.phases.Segment(phase="fetch"),)
    run = tests.helpers.factories.peri_scribe.monitor.events.run(
        tests.helpers.factories.peri_scribe.monitor.events.record(
            "Starting command",
            command="run",
        ),
        tests.helpers.factories.peri_scribe.monitor.events.record(
            "Skipped phases",
            path=path,
            phases=["source-index"],
            reason="unchanged",
        ),
    )
    tree = peri_scribe.monitor.model.phase_tree(run, peri_scribe.phases.Branches())
    assert any(omitted.reason == "unchanged" for omitted in tree.omissions)


def test_phase_tree_explains_overlapping_invocation_skip() -> None:
    run = tests.helpers.factories.peri_scribe.monitor.events.run(
        tests.helpers.factories.peri_scribe.monitor.events.record(
            "Starting command",
            command="run",
        ),
        tests.helpers.factories.peri_scribe.monitor.events.record(
            "Another run owns this year; skipping invocation",
        ),
    )
    assert not peri_scribe.monitor.model.phase_tree(
        run,
        peri_scribe.phases.Branches(),
    ).phases


@pytest.mark.parametrize(
    "value",
    [{}, {"value": "bad", "units": "second"}, {"value": 1, "units": "acres"}, None],
)
def test_recorded_duration_rejects_unusable_metadata(value: object) -> None:
    event = peri_scribe.monitor.events.make_event({"duration": value}, 1, ())
    assert peri_scribe.monitor.model.recorded_duration(event) == 0 * units.seconds


def test_filter_events_preserves_original_records() -> None:
    run = tests.helpers.factories.peri_scribe.monitor.events.run(
        tests.helpers.factories.peri_scribe.monitor.events.record(
            "Keep",
            level="warning",
            fire="Moonshine",
        ),
        tests.helpers.factories.peri_scribe.monitor.events.record(
            "Omit",
            level="debug",
        ),
    )
    assert [
        event.message
        for event in peri_scribe.monitor.model.filter_events(
            run,
            minimum_level="warning",
            query="moonshine",
        )
    ] == ["Keep"]
    assert [event.message for event in run.events] == ["Keep", "Omit"]


def test_phase_tree_retains_observed_child_without_parent_boundary() -> None:
    path = (
        peri_scribe.phases.Segment(phase="fetch"),
        peri_scribe.phases.Segment(phase="fire-collection"),
    )
    run = tests.helpers.factories.peri_scribe.monitor.events.run(
        tests.helpers.factories.peri_scribe.monitor.events.record(
            "Starting command",
            command="run",
        ),
        tests.helpers.factories.peri_scribe.monitor.events.record(
            "Finished phase",
            path=path,
            status="completed",
        ),
        tests.helpers.factories.peri_scribe.monitor.events.record(
            "Finished command",
            status="completed",
        ),
    )
    tree = peri_scribe.monitor.model.phase_tree(run, peri_scribe.phases.Branches())
    assert [(view.path, view.status) for view in tree.phases] == [
        (path[:1], "unfinished"),
        (path, "completed"),
    ]


def test_phase_tree_keeps_completed_phases_after_event_retention_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(peri_scribe.monitor.model, "MAXIMUM_EVENTS_PER_RUN", 1)
    path = (peri_scribe.phases.Segment(phase="fetch"),)
    run = tests.helpers.factories.peri_scribe.monitor.events.run(
        tests.helpers.factories.peri_scribe.monitor.events.record(
            "Starting command",
            command="run",
        ),
        tests.helpers.factories.peri_scribe.monitor.events.record(
            "Finished phase",
            path=path,
            duration={"value": 1, "units": "second"},
        ),
        tests.helpers.factories.peri_scribe.monitor.events.record("Later work"),
    )
    tree = peri_scribe.monitor.model.phase_tree(run, peri_scribe.phases.Branches())
    assert tree.phases[0].status == "completed"
    assert tree.phases[0].duration == 1 * units.seconds
    assert [event.message for event in run.events] == ["Later work"]
