"""Terminal formatting keeps timestamps, severity, and structured fields readable."""

import datetime
import json

import pytest

import peri_scribe.monitor.events
import peri_scribe.monitor.model
import peri_scribe.monitor.presentation
import peri_scribe.monitor.storage
import peri_scribe.phases
import tests.helpers.factories.peri_scribe.monitor.events
from peri_scribe.units import units


@pytest.mark.parametrize("status", peri_scribe.monitor.model.Status)
def test_phase_label_handles_each_status_with_literal_source_name(
    status: peri_scribe.monitor.model.Status,
) -> None:
    view = peri_scribe.monitor.model.PhaseView(
        path=(peri_scribe.phases.Segment(phase="collect-feed", branch="[red]alpha"),),
        status=status,
        duration=2 * units.seconds,
    )
    label = peri_scribe.monitor.presentation.phase_label(view)
    assert "[red]alpha" in label.plain
    assert bool(label.style)
    if status in {"completed", "failed"}:
        assert "2.0s" in label.plain


@pytest.mark.parametrize("level", ["debug", "info", "warning", "error", "critical"])
def test_event_cells_style_severity_without_interpreting_message_markup(
    level: str,
) -> None:
    event = peri_scribe.monitor.events.make_event(
        {"event": "[red]Details", "level": level, "fire": "Moonshine"},
        1,
        (),
    )
    when, severity, message = peri_scribe.monitor.presentation.event_cells(event)
    assert when == "—"
    assert severity.plain == level.upper()
    assert message.plain == "[red]Details · Moonshine"


def test_run_cells_explains_gate_skip() -> None:
    run = tests.helpers.factories.peri_scribe.monitor.events.run(
        tests.helpers.factories.peri_scribe.monitor.events.record(
            "Publication gate skipped",
            reason="below threshold",
        ),
    )
    assert (
        "below threshold" in peri_scribe.monitor.presentation.run_cells(run)[-1].plain
    )


def test_run_cells_handles_missing_timestamps() -> None:
    when, command, status = peri_scribe.monitor.presentation.run_cells(
        peri_scribe.monitor.model.Run(identifier="unknown"),
    )
    assert (when, command.plain, status.plain) == ("Unknown", "unattributed", "open")


def test_details_preserves_exception_fields() -> None:
    fields: dict[str, object] = {
        "event": "Failure",
        "exception": "Full traceback\nsecond line",
    }
    event = peri_scribe.monitor.events.make_event(fields, 1, ())
    assert json.loads(peri_scribe.monitor.presentation.details(event)) == fields


def test_report_heading_waits_for_first_report() -> None:
    assert (
        peri_scribe.monitor.presentation.report_heading(
            peri_scribe.monitor.storage.Report(),
        )
        == "Waiting for report"
    )


def test_report_heading_uses_file_time_and_timezone() -> None:
    report = peri_scribe.monitor.storage.Report(
        modified=datetime.datetime(2026, 9, 16, 12, 34, 56, tzinfo=datetime.UTC),
    )
    assert peri_scribe.monitor.presentation.report_heading(report) == (
        "Report written 2026-09-16 12:34:56 UTC (UTC+0000)"
    )


def test_activity_handles_clock_skew() -> None:
    run = tests.helpers.factories.peri_scribe.monitor.events.run(
        tests.helpers.factories.peri_scribe.monitor.events.record("Future event"),
    )
    assert peri_scribe.monitor.presentation.activity(
        run,
        datetime.datetime(2020, 1, 1, tzinfo=datetime.UTC),
    ).endswith("last event 0s ago")
