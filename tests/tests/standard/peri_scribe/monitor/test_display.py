"""Prepared diagnostics retain selected evidence, literal formatting, and ordering."""

import peri_scribe.monitor.display
import peri_scribe.monitor.model
import peri_scribe.phases
import tests.helpers.factories.peri_scribe.monitor.events


def test_event_rows_keeps_captured_filters_and_literal_event_identity() -> None:
    path = (peri_scribe.phases.Segment(phase="fetch"),)
    run = tests.helpers.factories.peri_scribe.monitor.events.run(
        tests.helpers.factories.peri_scribe.monitor.events.record(
            "[red]Alpha",
            path=path,
            level="warning",
        ),
        tests.helpers.factories.peri_scribe.monitor.events.record("Alpha"),
        tests.helpers.factories.peri_scribe.monitor.events.record(
            "Beta",
            path=path,
            level="warning",
        ),
    )
    rows = peri_scribe.monitor.display.event_rows(
        run,
        peri_scribe.monitor.display.Filter(
            minimum_level="warning",
            query="Alpha",
            path=path,
        ),
    )
    assert len(rows) == 1
    assert rows[0].event is run.events[0]
    assert rows[0].cells[-1].plain == "[red]Alpha"


def test_prepare_keeps_inspected_run_separate_from_live_history_and_filters() -> None:
    selected = tests.helpers.factories.peri_scribe.monitor.events.run(
        tests.helpers.factories.peri_scribe.monitor.events.record(
            "Starting command",
            command="run",
        ),
        tests.helpers.factories.peri_scribe.monitor.events.record(
            "Starting phase",
            path=(peri_scribe.phases.Segment(phase="score"),),
        ),
        tests.helpers.factories.peri_scribe.monitor.events.record(
            "Finished command",
            status="failed",
            level="error",
        ),
    )
    state = peri_scribe.monitor.model.State(
        runs=(
            peri_scribe.monitor.model.Run(identifier="older"),
            peri_scribe.monitor.model.Run(identifier="newer"),
        ),
    )
    prepared = peri_scribe.monitor.display.prepare(
        state,
        selected,
        tests.helpers.factories.peri_scribe.monitor.events.BRANCHES,
        peri_scribe.monitor.display.Filter(minimum_level="error", query=""),
        peri_scribe.monitor.display.Filter(minimum_level="debug", query=""),
    )
    assert [row.run.identifier for row in prepared.runs] == ["newer", "older"]
    assert [row.event for row in prepared.logs] == list(selected.events)
    assert [row.event for row in prepared.pipeline] == [selected.events[-1]]
    assert prepared.phases[0][0].status == "unfinished"
    assert "score" in prepared.phases[0][1].plain
    assert "Not reached: command failed" in prepared.reasons[0]
