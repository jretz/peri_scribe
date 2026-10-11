"""Presentation preserves health explanations, ages, and evidence links."""

import dataclasses
import datetime
import unittest.mock

import pytest

import peri_scribe.monitor.health_presentation
import peri_scribe.monitor.history
import peri_scribe.monitor.projection
import peri_scribe.monitor.status
import peri_scribe.phases
import tests.helpers.factories.peri_scribe.monitor.status


@pytest.mark.parametrize(
    ("elapsed", "expected"),
    [
        (None, "unknown"),
        (datetime.timedelta(seconds=30), "<1m"),
        (datetime.timedelta(minutes=12), "12m"),
        (datetime.timedelta(hours=2, minutes=3), "2h 3m"),
        (datetime.timedelta(days=3, hours=2), "3d 2h"),
    ],
)
def test_age_compact_elapsed_values(
    elapsed: datetime.timedelta | None,
    expected: str,
) -> None:
    now = tests.helpers.factories.peri_scribe.monitor.status.NOW
    assert (
        peri_scribe.monitor.health_presentation.age(
            now - elapsed if elapsed is not None else None,
            now,
        )
        == expected
    )


def test_path_label_preserves_every_ancestor_and_source() -> None:
    assert (
        peri_scribe.monitor.health_presentation.path_label((
            peri_scribe.phases.Segment(phase="fetch"),
            peri_scribe.phases.Segment(phase="fire-collection"),
            peri_scribe.phases.Segment(phase="collect-feed", branch="WFIGS"),
            peri_scribe.phases.Segment(phase="query-features"),
        ))
        == "fetch → fire-collection → collect-feed [WFIGS] → query-features"
    )


@pytest.mark.parametrize(
    ("changes", "text"),
    [
        ({"caught_up": False}, "Loading"),
        ({"errors": ("unreadable",)}, "unreadable"),
        ({"coverage": ()}, "No log entries"),
        ({"undated": 1}, "undated"),
        ({}, "48-hour window loaded"),
    ],
)
def test_coverage_metric_exposes_incomplete_history(
    changes: dict[str, object],
    text: str,
) -> None:
    history = dataclasses.replace(
        tests.helpers.factories.peri_scribe.monitor.status.history(
            tests.helpers.factories.peri_scribe.monitor.status.record("Recent"),
        ),
        **changes,
    )
    assert (
        text
        in peri_scribe.monitor.health_presentation.coverage_metric(
            peri_scribe.monitor.status.coverage_metric(
                history,
                tests.helpers.factories.peri_scribe.monitor.status.NOW,
            ),
        ).text
    )


@pytest.mark.parametrize("hours", [49, -1])
def test_coverage_metric_errors_without_entries_in_the_last_48_hours(
    hours: int,
) -> None:
    now = tests.helpers.factories.peri_scribe.monitor.status.NOW
    history = tests.helpers.factories.peri_scribe.monitor.status.history(
        tests.helpers.factories.peri_scribe.monitor.status.record(
            "Outside window",
            when=now - datetime.timedelta(hours=hours),
        ),
    )
    metric = peri_scribe.monitor.health_presentation.coverage_metric(
        peri_scribe.monitor.status.coverage_metric(history, now),
    )
    assert metric.health == peri_scribe.monitor.status.Health.BAD
    assert metric.text == "No log entries in the last 48 hours"


def test_present_missing_outputs_remain_red_during_a_build() -> None:
    history = tests.helpers.factories.peri_scribe.monitor.status.history(
        tests.helpers.factories.peri_scribe.monitor.status.record(
            "Starting command",
            command="run",
        ),
        tests.helpers.factories.peri_scribe.monitor.status.record(
            "Starting phase",
            phase="kmz.build-kml",
        ),
    )
    output = peri_scribe.monitor.status.Output(error="Missing", missing=True)
    view = peri_scribe.monitor.health_presentation.present(
        peri_scribe.monitor.status.project(
            history,
            peri_scribe.monitor.status.Files(
                kmz=output,
                report=output,
                pending=("kmz", "reports"),
            ),
            tests.helpers.factories.peri_scribe.monitor.status.NOW,
        ),
        tests.helpers.factories.peri_scribe.monitor.status.NOW,
    )
    assert view.overview.health == peri_scribe.monitor.status.Health.BAD
    assert "kmz → build-kml" in view.metrics[2].text
    assert view.metrics[4].health == peri_scribe.monitor.status.Health.ACTIVE


def test_present_report_behind_latest_kmz_is_warning() -> None:
    now = tests.helpers.factories.peri_scribe.monitor.status.NOW
    history = tests.helpers.factories.peri_scribe.monitor.status.history(
        tests.helpers.factories.peri_scribe.monitor.status.finished(
            "reports",
            when=now - datetime.timedelta(minutes=1),
        ),
        tests.helpers.factories.peri_scribe.monitor.status.finished("kmz"),
    )
    view = peri_scribe.monitor.health_presentation.present(
        peri_scribe.monitor.status.project(
            history,
            tests.helpers.factories.peri_scribe.monitor.status.files(),
            now,
        ),
        now,
    )
    assert view.metrics[1].health == peri_scribe.monitor.status.Health.WARNING
    assert "caught up" in view.metrics[1].text


@pytest.mark.parametrize("phase", ["", "reports", "reports.prepare-fire-histories"])
def test_present_report_catching_up_during_build_is_active(phase: str) -> None:
    view = peri_scribe.monitor.health_presentation.present(
        peri_scribe.monitor.status.project(
            tests.helpers.factories.peri_scribe.monitor.status.report_build(
                phase=phase,
            ),
            tests.helpers.factories.peri_scribe.monitor.status.files(),
            tests.helpers.factories.peri_scribe.monitor.status.NOW,
        ),
        tests.helpers.factories.peri_scribe.monitor.status.NOW,
    )
    assert view.metrics[1].health == peri_scribe.monitor.status.Health.ACTIVE
    assert "Report generation in progress" in view.metrics[1].text
    assert "caught up" not in view.metrics[1].text


def test_present_fresh_complete_system_is_green() -> None:
    now = tests.helpers.factories.peri_scribe.monitor.status.NOW
    history = tests.helpers.factories.peri_scribe.monitor.status.history(
        tests.helpers.factories.peri_scribe.monitor.status.record(
            "Starting command",
            command="run",
            when=now - datetime.timedelta(days=3),
        ),
        tests.helpers.factories.peri_scribe.monitor.status.finished("fetch"),
        tests.helpers.factories.peri_scribe.monitor.status.record(
            "Publication gate skipped",
            reason="no unpublished data",
        ),
        tests.helpers.factories.peri_scribe.monitor.status.record(
            "Finished command",
            command="run",
            status="completed",
        ),
    )
    view = peri_scribe.monitor.health_presentation.present(
        peri_scribe.monitor.status.project(
            history,
            tests.helpers.factories.peri_scribe.monitor.status.files(),
            now,
        ),
        now,
    )
    assert view.overview.health == peri_scribe.monitor.status.Health.GOOD
    assert view.recent[0].text == "run · Checked · publication deferred"


def test_activity_metric_lock_skip_cannot_hide_active_phase() -> None:
    history = tests.helpers.factories.peri_scribe.monitor.status.history(
        tests.helpers.factories.peri_scribe.monitor.status.record(
            "Starting command",
            command="run",
        ),
        tests.helpers.factories.peri_scribe.monitor.status.record(
            "Starting phase",
            phase="fetch.query-features",
        ),
        tests.helpers.factories.peri_scribe.monitor.status.record(
            "Starting command",
            run_id="skipped",
            command="run",
        ),
        tests.helpers.factories.peri_scribe.monitor.status.record(
            "Another run owns this year; skipping invocation",
            run_id="skipped",
        ),
        tests.helpers.factories.peri_scribe.monitor.status.record(
            "Finished command",
            run_id="skipped",
            status="completed",
        ),
    )
    metric = peri_scribe.monitor.health_presentation.activity_metric(
        peri_scribe.monitor.status.activity_metric(history),
        tests.helpers.factories.peri_scribe.monitor.status.NOW,
    )
    assert metric.target is not None
    assert metric.target.run == "run-1"
    assert "fetch → query-features" in metric.text
    assert (
        "lock"
        in peri_scribe.monitor.health_presentation.recent_metrics(
            peri_scribe.monitor.status.recent_metrics(history),
        )[0].text
    )


def test_transition_metrics_include_failure_recovery_and_outputs() -> None:
    history = tests.helpers.factories.peri_scribe.monitor.status.history(
        *tests.helpers.factories.peri_scribe.monitor.status.failed_run(),
        tests.helpers.factories.peri_scribe.monitor.status.finished(
            "reports",
            run_id="later",
        ),
        tests.helpers.factories.peri_scribe.monitor.status.finished(
            "kmz",
            run_id="later",
        ),
    )
    view = peri_scribe.monitor.health_presentation.present(
        peri_scribe.monitor.status.project(
            history,
            tests.helpers.factories.peri_scribe.monitor.status.files(),
            tests.helpers.factories.peri_scribe.monitor.status.NOW,
        ),
        tests.helpers.factories.peri_scribe.monitor.status.NOW,
    )
    assert {metric.text for metric in view.transitions} == {
        "Run failed",
        "Failed work recovered",
        "KMZ updated",
        "Report updated",
    }


@pytest.mark.parametrize("same_time", [True, False])
def test_transition_metrics_format_only_the_eight_selected_rows(
    monkeypatch: pytest.MonkeyPatch,
    *,
    same_time: bool,
) -> None:
    now = tests.helpers.factories.peri_scribe.monitor.status.NOW
    history = tests.helpers.factories.peri_scribe.monitor.status.history(
        *(
            tests.helpers.factories.peri_scribe.monitor.status.finished(
                "kmz",
                run_id=str(index),
                when=now if same_time else now - datetime.timedelta(minutes=20 - index),
            )
            for index in range(20)
        ),
    )
    formatter = unittest.mock.Mock(
        wraps=peri_scribe.monitor.health_presentation.local_time,
    )
    monkeypatch.setattr(
        peri_scribe.monitor.health_presentation,
        "local_time",
        formatter,
    )
    metrics = peri_scribe.monitor.health_presentation.transition_metrics(
        peri_scribe.monitor.status.transition_metrics(
            peri_scribe.monitor.status.evidence(history),
            peri_scribe.monitor.status.FailureMetric(
                health=peri_scribe.monitor.status.Health.GOOD,
            ),
        ),
    )
    expected = range(8) if same_time else range(19, 11, -1)
    assert [metric.target.run for metric in metrics if metric.target] == [
        str(index) for index in expected
    ]
    assert formatter.call_count == len(metrics)


@pytest.mark.parametrize(
    ("elapsed", "remaining"),
    [(30, 30), (60, 60), (3600, 60), (86399, 1), (88200, 1800)],
)
def test_deadline_updates_elapsed_text_without_rebuilding_health(
    elapsed: int,
    remaining: int,
) -> None:
    now = tests.helpers.factories.peri_scribe.monitor.status.NOW
    history = peri_scribe.monitor.history.History()
    output = peri_scribe.monitor.status.Output(
        modified=now - datetime.timedelta(seconds=elapsed),
    )
    files = peri_scribe.monitor.status.Files(kmz=output, report=output)
    snapshot = peri_scribe.monitor.projection.refresh(history, files, now)
    deadline = now + datetime.timedelta(seconds=remaining)
    assert peri_scribe.monitor.health_presentation.deadline(snapshot, now) == deadline
    before = peri_scribe.monitor.health_presentation.prepare(snapshot, now)
    after = peri_scribe.monitor.health_presentation.prepare(snapshot, deadline)
    assert before.metrics[0].text != after.metrics[0].text
    assert (
        peri_scribe.monitor.projection.refresh(history, files, deadline, snapshot)
        is snapshot
    )


def test_deadline_without_ages_needs_no_clock_refresh() -> None:
    now = tests.helpers.factories.peri_scribe.monitor.status.NOW
    output = peri_scribe.monitor.status.Output(error="Missing", missing=True)
    snapshot = peri_scribe.monitor.projection.refresh(
        peri_scribe.monitor.history.History(),
        peri_scribe.monitor.status.Files(kmz=output, report=output),
        now,
    )
    assert peri_scribe.monitor.health_presentation.deadline(snapshot, now) is None


def test_deadline_handles_clock_moving_before_activity() -> None:
    now = tests.helpers.factories.peri_scribe.monitor.status.NOW
    future = now + datetime.timedelta(seconds=30)
    history = tests.helpers.factories.peri_scribe.monitor.status.history(
        tests.helpers.factories.peri_scribe.monitor.status.record(
            "Starting command",
            when=future,
            command="run",
        ),
    )
    output = peri_scribe.monitor.status.Output(error="Missing", missing=True)
    snapshot = peri_scribe.monitor.projection.refresh(
        history,
        peri_scribe.monitor.status.Files(kmz=output, report=output),
        now,
    )
    assert peri_scribe.monitor.health_presentation.deadline(snapshot, now) == future


def test_deadline_tracks_elapsed_command_time_before_latest_progress_age() -> None:
    now = tests.helpers.factories.peri_scribe.monitor.status.NOW
    history = tests.helpers.factories.peri_scribe.monitor.status.history(
        tests.helpers.factories.peri_scribe.monitor.status.record(
            "Starting command",
            when=now - datetime.timedelta(seconds=50),
            command="run",
        ),
        tests.helpers.factories.peri_scribe.monitor.status.record("Working"),
    )
    snapshot = peri_scribe.monitor.projection.refresh(
        history,
        tests.helpers.factories.peri_scribe.monitor.status.files(),
        now,
    )
    assert peri_scribe.monitor.health_presentation.deadline(
        snapshot,
        now,
    ) == now + datetime.timedelta(seconds=10)


@pytest.mark.parametrize(
    ("fields", "reason"),
    [({}, "Unknown reason"), ({"reason": ""}, ""), ({"reason": None}, "None")],
)
def test_publication_reason_retains_missing_and_empty_distinction(
    fields: dict[str, object],
    reason: str,
) -> None:
    history = tests.helpers.factories.peri_scribe.monitor.status.history(
        {
            **tests.helpers.factories.peri_scribe.monitor.status.record(
                "Publication gate skipped",
            ),
            **fields,
        },
    )
    fact = peri_scribe.monitor.status.publication_metric(
        tests.helpers.factories.peri_scribe.monitor.status.files(),
        peri_scribe.monitor.status.evidence(history),
    )
    assert (
        peri_scribe.monitor.health_presentation.publication_metric(fact).text
        == "Last decision: " + reason
    )


@pytest.mark.parametrize(
    ("error", "pending", "text"),
    [
        ("Cannot read recovery state", (), "Cannot read recovery state"),
        ("", ("kmz", "reports"), "Rebuild pending: kmz → reports"),
    ],
)
def test_publication_metric_reports_recovery_requirements(
    error: str,
    pending: tuple[str, ...],
    text: str,
) -> None:
    files = dataclasses.replace(
        tests.helpers.factories.peri_scribe.monitor.status.files(),
        error=error,
        pending=pending,
    )
    fact = peri_scribe.monitor.status.publication_metric(files, ())
    assert peri_scribe.monitor.health_presentation.publication_metric(fact).text == text
