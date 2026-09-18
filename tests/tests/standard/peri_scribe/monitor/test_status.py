"""Health colors require current artifacts and evidence of actual recovery."""

import dataclasses
import datetime
import os
import pathlib
import unittest.mock

import pytest

import peri_scribe.monitor.history
import peri_scribe.monitor.model
import peri_scribe.monitor.status
import peri_scribe.phases
import tests.helpers.doubles.errors
import tests.helpers.factories.peri_scribe.monitor.status


@pytest.mark.parametrize(
    ("elapsed", "expected"),
    [
        (datetime.timedelta(), peri_scribe.monitor.status.Health.GOOD),
        (
            datetime.timedelta(hours=5) - datetime.timedelta(microseconds=1),
            peri_scribe.monitor.status.Health.GOOD,
        ),
        (datetime.timedelta(hours=5), peri_scribe.monitor.status.Health.WARNING),
        (datetime.timedelta(hours=6), peri_scribe.monitor.status.Health.WARNING),
        (
            datetime.timedelta(hours=6, microseconds=1),
            peri_scribe.monitor.status.Health.BAD,
        ),
    ],
)
def test_output_metric_colors_exact_freshness_boundaries(
    elapsed: datetime.timedelta,
    expected: peri_scribe.monitor.status.Health,
) -> None:
    now = tests.helpers.factories.peri_scribe.monitor.status.NOW
    output = peri_scribe.monitor.status.Output(modified=now - elapsed)
    metric = peri_scribe.monitor.status.output_metric("KMZ", "kmz", output, (), now)
    assert metric.health == expected


@pytest.mark.parametrize("phase", ["kmz", "reports"])
def test_output_metric_starting_a_build_does_not_renew_freshness(phase: str) -> None:
    now = tests.helpers.factories.peri_scribe.monitor.status.NOW
    history = tests.helpers.factories.peri_scribe.monitor.status.history(
        tests.helpers.factories.peri_scribe.monitor.status.finished(
            phase,
            when=now - datetime.timedelta(hours=7),
        ),
        tests.helpers.factories.peri_scribe.monitor.status.record(
            "Starting phase",
            phase=phase,
            run_id="new",
        ),
    )
    metric = peri_scribe.monitor.status.output_metric(
        phase,
        phase,
        peri_scribe.monitor.status.Output(modified=now),
        peri_scribe.monitor.status.evidence(history),
        now,
    )
    assert metric.health == peri_scribe.monitor.status.Health.BAD
    assert metric.target is not None
    assert metric.target.run == "run-1"


@pytest.mark.parametrize(
    "output",
    [
        peri_scribe.monitor.status.Output(),
        peri_scribe.monitor.status.Output(
            modified=tests.helpers.factories.peri_scribe.monitor.status.NOW
            + datetime.timedelta(hours=1),
        ),
    ],
)
def test_output_metric_unknown_or_future_time_is_not_healthy(
    output: peri_scribe.monitor.status.Output,
) -> None:
    assert (
        peri_scribe.monitor.status.output_metric(
            "Report",
            "reports",
            output,
            (),
            tests.helpers.factories.peri_scribe.monitor.status.NOW,
        ).health
        == peri_scribe.monitor.status.Health.WARNING
    )


@pytest.mark.parametrize(
    ("missing", "expected"),
    [
        (True, peri_scribe.monitor.status.Health.BAD),
        (False, peri_scribe.monitor.status.Health.WARNING),
    ],
)
def test_output_metric_unavailable_artifact_overrides_build_history(
    *,
    missing: bool,
    expected: peri_scribe.monitor.status.Health,
) -> None:
    assert (
        peri_scribe.monitor.status.output_metric(
            "KMZ",
            "kmz",
            peri_scribe.monitor.status.Output(error="unavailable", missing=missing),
            (),
            tests.helpers.factories.peri_scribe.monitor.status.NOW,
        ).health
        == expected
    )


def test_read_output_uses_actual_modification_time(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "map.kmz"
    path.write_bytes(b"map")
    os.utime(path, (1000000000, 1000000000))
    assert peri_scribe.monitor.status.read_output(
        path,
    ).modified == datetime.datetime.fromtimestamp(1000000000, datetime.UTC)


@pytest.mark.parametrize("kind", ["missing", "empty", "directory"])
def test_read_output_unusable_artifacts_are_missing(
    tmp_path: pathlib.Path,
    kind: str,
) -> None:
    path = tmp_path / "artifact"
    if kind == "empty":
        path.touch()
    elif kind == "directory":
        path.mkdir()
    assert peri_scribe.monitor.status.read_output(path).missing


def test_read_output_read_errors_remain_unknown(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        pathlib.Path,
        "stat",
        tests.helpers.doubles.errors.raising_stub(PermissionError("denied")),
    )
    output = peri_scribe.monitor.status.read_output(tmp_path)
    assert not output.missing
    assert "denied" in output.error


@pytest.mark.parametrize(
    ("content", "pending", "error"),
    [
        (None, (), False),
        ('{"version":1,"remaining":["kmz","reports"]}', ("kmz", "reports"), False),
        ("broken", (), True),
    ],
)
def test_read_files_reports_pending_work_without_writing(
    tmp_path: pathlib.Path,
    content: str | None,
    pending: tuple[str, ...],
    *,
    error: bool,
) -> None:
    if content is not None:
        (tmp_path / "run_state.json").write_text(content)
    files = peri_scribe.monitor.status.read_files(
        tmp_path,
        tmp_path / "map.kmz",
        tmp_path / "report.md",
    )
    assert files.pending == pending
    assert bool(files.error) == error
    assert {path.name for path in tmp_path.iterdir()} == (
        {"run_state.json"} if content is not None else set()
    )


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
        peri_scribe.monitor.status.age(
            now - elapsed if elapsed is not None else None,
            now,
        )
        == expected
    )


def test_path_label_preserves_every_ancestor_and_source() -> None:
    assert (
        peri_scribe.monitor.status.path_label((
            peri_scribe.phases.Segment(phase="fetch"),
            peri_scribe.phases.Segment(phase="fire-collection"),
            peri_scribe.phases.Segment(phase="collect-feed", branch="WFIGS"),
            peri_scribe.phases.Segment(phase="query-features"),
        ))
        == "fetch → fire-collection → collect-feed [WFIGS] → query-features"
    )


def test_failure_metric_source_check_cannot_resolve_report_failure() -> None:
    history = tests.helpers.factories.peri_scribe.monitor.status.history(
        *tests.helpers.factories.peri_scribe.monitor.status.failed_run(),
        tests.helpers.factories.peri_scribe.monitor.status.finished(
            "fetch",
            run_id="later",
        ),
    )
    assert (
        peri_scribe.monitor.status.failure_metric(
            peri_scribe.monitor.status.evidence(history),
            tests.helpers.factories.peri_scribe.monitor.status.NOW,
        ).health
        == peri_scribe.monitor.status.Health.BAD
    )


def test_failure_metric_matching_stage_completion_proves_recovery() -> None:
    history = tests.helpers.factories.peri_scribe.monitor.status.history(
        *tests.helpers.factories.peri_scribe.monitor.status.failed_run(),
        tests.helpers.factories.peri_scribe.monitor.status.finished(
            "reports",
            run_id="later",
        ),
    )
    metric = peri_scribe.monitor.status.failure_metric(
        peri_scribe.monitor.status.evidence(history),
        tests.helpers.factories.peri_scribe.monitor.status.NOW,
    )
    assert metric.health == peri_scribe.monitor.status.Health.GOOD
    assert "Recovered" in metric.text
    assert metric.target is not None
    assert metric.target.run == "failed"


def test_exception_groups_count_one_propagated_failure() -> None:
    history = tests.helpers.factories.peri_scribe.monitor.status.history(
        *tests.helpers.factories.peri_scribe.monitor.status.failed_run(),
    )
    groups = peri_scribe.monitor.status.exception_groups(
        history,
        peri_scribe.monitor.status.evidence(history),
        tests.helpers.factories.peri_scribe.monitor.status.NOW,
    )
    assert len(groups) == 1
    assert groups[0].occurrences == 1
    assert groups[0].path == "reports → prepare-fire-histories"
    assert groups[0].health == peri_scribe.monitor.status.Health.BAD


def test_exception_groups_count_retries_and_affected_runs() -> None:
    history = tests.helpers.factories.peri_scribe.monitor.status.history(
        *(
            tests.helpers.factories.peri_scribe.monitor.status.record(
                "Retrying",
                phase="fetch.query-features",
                exception="TimeoutError: timed out",
                run_id=identifier,
            )
            for identifier in ("first", "first", "second")
        ),
        tests.helpers.factories.peri_scribe.monitor.status.finished(
            "fetch",
            run_id="second",
        ),
    )
    groups = peri_scribe.monitor.status.exception_groups(
        history,
        peri_scribe.monitor.status.evidence(history),
        tests.helpers.factories.peri_scribe.monitor.status.NOW,
    )
    expected_occurrences = 3
    assert groups[0].occurrences == expected_occurrences
    assert groups[0].runs == {"first", "second"}
    assert groups[0].latest.run == "second"
    assert groups[0].outcome == "Recovered"


def test_exception_groups_window_excludes_old_and_future_errors() -> None:
    now = tests.helpers.factories.peri_scribe.monitor.status.NOW
    history = tests.helpers.factories.peri_scribe.monitor.status.history(
        *(
            tests.helpers.factories.peri_scribe.monitor.status.record(
                "Retry",
                exception="TimeoutError: timed out",
                when=when,
            )
            for when in (
                now - datetime.timedelta(hours=48, microseconds=1),
                now - datetime.timedelta(hours=48),
                now + datetime.timedelta(seconds=1),
            )
        ),
    )
    groups = peri_scribe.monitor.status.exception_groups(
        history,
        peri_scribe.monitor.status.evidence(history),
        now,
    )
    assert groups[0].occurrences == 1


def test_exception_groups_keep_sources_separate() -> None:
    history = tests.helpers.factories.peri_scribe.monitor.status.history(
        *(
            tests.helpers.factories.peri_scribe.monitor.status.record(
                "Retry",
                exception="TimeoutError: timed out",
                feed=feed,
            )
            for feed in ("alpha", "beta")
        ),
    )
    expected_count = 2
    assert (
        len(
            peri_scribe.monitor.status.exception_groups(
                history,
                peri_scribe.monitor.status.evidence(history),
                tests.helpers.factories.peri_scribe.monitor.status.NOW,
            ),
        )
        == expected_count
    )


def test_signature_normalizes_incidental_values_and_preserves_http_code() -> None:
    assert (
        peri_scribe.monitor.status.signature(
            (
                "Traceback...\nHTTPError: 429 request "
                "01234567-abcd-abcd-abcd-0123456789ab at 2026-09-16T08:00:00Z "
                "object 0xabc"
            ),
        )
        == "HTTPError: 429 request <id> at <time> object <address>"
    )
    assert peri_scribe.monitor.status.signature("") == "Unknown exception"


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
        in peri_scribe.monitor.status.coverage_metric(
            history,
            tests.helpers.factories.peri_scribe.monitor.status.NOW,
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
    metric = peri_scribe.monitor.status.coverage_metric(history, now)
    assert metric.health == peri_scribe.monitor.status.Health.BAD
    assert metric.text == "No log entries in the last 48 hours"


@pytest.mark.parametrize("future_first", [False, True])
def test_coverage_metric_accepts_recent_entries_alongside_future_progress(
    *,
    future_first: bool,
) -> None:
    now = tests.helpers.factories.peri_scribe.monitor.status.NOW
    records = (
        tests.helpers.factories.peri_scribe.monitor.status.record("Recent"),
        tests.helpers.factories.peri_scribe.monitor.status.record(
            "Future",
            when=now + datetime.timedelta(days=3),
        ),
    )
    history = tests.helpers.factories.peri_scribe.monitor.status.history(
        *(reversed(records) if future_first else records),
    )
    assert (
        peri_scribe.monitor.status.coverage_metric(history, now).health
        == peri_scribe.monitor.status.Health.GOOD
    )


def test_project_missing_outputs_remain_red_during_a_build() -> None:
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
    view = peri_scribe.monitor.status.project(
        history,
        peri_scribe.monitor.status.Files(
            kmz=output,
            report=output,
            pending=("kmz", "reports"),
        ),
        tests.helpers.factories.peri_scribe.monitor.status.NOW,
    )
    assert view.overview.health == peri_scribe.monitor.status.Health.BAD
    assert "kmz → build-kml" in view.metrics[2].text
    assert view.metrics[4].health == peri_scribe.monitor.status.Health.ACTIVE


def test_project_report_behind_latest_kmz_is_warning() -> None:
    now = tests.helpers.factories.peri_scribe.monitor.status.NOW
    history = tests.helpers.factories.peri_scribe.monitor.status.history(
        tests.helpers.factories.peri_scribe.monitor.status.finished(
            "reports",
            when=now - datetime.timedelta(minutes=1),
        ),
        tests.helpers.factories.peri_scribe.monitor.status.finished("kmz"),
    )
    view = peri_scribe.monitor.status.project(
        history,
        tests.helpers.factories.peri_scribe.monitor.status.files(),
        now,
    )
    assert view.metrics[1].health == peri_scribe.monitor.status.Health.WARNING
    assert "caught up" in view.metrics[1].text


@pytest.mark.parametrize("phase", ["", "reports", "reports.prepare-fire-histories"])
def test_project_report_catching_up_during_build_is_active(phase: str) -> None:
    view = peri_scribe.monitor.status.project(
        tests.helpers.factories.peri_scribe.monitor.status.report_build(phase=phase),
        tests.helpers.factories.peri_scribe.monitor.status.files(),
        tests.helpers.factories.peri_scribe.monitor.status.NOW,
    )
    assert view.metrics[1].health == peri_scribe.monitor.status.Health.ACTIVE
    assert "Report generation in progress" in view.metrics[1].text
    assert "caught up" not in view.metrics[1].text


def test_project_report_generation_does_not_require_attention() -> None:
    view = peri_scribe.monitor.status.project(
        tests.helpers.factories.peri_scribe.monitor.status.report_build(),
        tests.helpers.factories.peri_scribe.monitor.status.files(),
        tests.helpers.factories.peri_scribe.monitor.status.NOW,
    )
    assert view.overview.health == peri_scribe.monitor.status.Health.GOOD


@pytest.mark.parametrize(
    ("report_age", "health"),
    [
        (datetime.timedelta(hours=5), peri_scribe.monitor.status.Health.WARNING),
        (datetime.timedelta(hours=7), peri_scribe.monitor.status.Health.BAD),
    ],
)
def test_project_report_generation_preserves_freshness_alerts(
    report_age: datetime.timedelta,
    health: peri_scribe.monitor.status.Health,
) -> None:
    view = peri_scribe.monitor.status.project(
        tests.helpers.factories.peri_scribe.monitor.status.report_build(
            report_age=report_age,
        ),
        tests.helpers.factories.peri_scribe.monitor.status.files(),
        tests.helpers.factories.peri_scribe.monitor.status.NOW,
    )
    assert view.metrics[1].health == health


def test_project_report_generation_keeps_the_last_successful_report_age() -> None:
    now = tests.helpers.factories.peri_scribe.monitor.status.NOW
    view = peri_scribe.monitor.status.project(
        tests.helpers.factories.peri_scribe.monitor.status.report_build(),
        tests.helpers.factories.peri_scribe.monitor.status.files(),
        now,
    )
    report = view.metrics[1]
    assert report.target is not None
    assert report.target.when == now - datetime.timedelta(minutes=2)
    assert report.target.run == "run-1"


def test_project_report_generation_cannot_hide_a_missing_report() -> None:
    view = peri_scribe.monitor.status.project(
        tests.helpers.factories.peri_scribe.monitor.status.report_build(),
        dataclasses.replace(
            tests.helpers.factories.peri_scribe.monitor.status.files(),
            report=peri_scribe.monitor.status.Output(error="Missing", missing=True),
        ),
        tests.helpers.factories.peri_scribe.monitor.status.NOW,
    )
    assert view.metrics[1].health == peri_scribe.monitor.status.Health.BAD


def test_project_report_is_green_after_generation_succeeds() -> None:
    now = tests.helpers.factories.peri_scribe.monitor.status.NOW
    history = peri_scribe.monitor.history.append(
        tests.helpers.factories.peri_scribe.monitor.status.report_build(),
        (
            tests.helpers.factories.peri_scribe.monitor.status.finished(
                "reports",
                run_id="building",
            ),
        ),
        now,
    )
    view = peri_scribe.monitor.status.project(
        history,
        tests.helpers.factories.peri_scribe.monitor.status.files(),
        now,
    )
    assert view.metrics[1].health == peri_scribe.monitor.status.Health.GOOD


@pytest.mark.parametrize("status", ["completed", "failed"])
def test_project_unfinished_report_warns_when_its_run_ends(status: str) -> None:
    now = tests.helpers.factories.peri_scribe.monitor.status.NOW
    history = peri_scribe.monitor.history.append(
        tests.helpers.factories.peri_scribe.monitor.status.report_build(),
        (
            tests.helpers.factories.peri_scribe.monitor.status.record(
                "Finished command",
                run_id="building",
                status=status,
            ),
        ),
        now,
    )
    view = peri_scribe.monitor.status.project(
        history,
        tests.helpers.factories.peri_scribe.monitor.status.files(),
        now,
    )
    assert view.metrics[1].health == peri_scribe.monitor.status.Health.WARNING


def test_project_failed_report_phase_warns_before_command_completion() -> None:
    now = tests.helpers.factories.peri_scribe.monitor.status.NOW
    history = peri_scribe.monitor.history.append(
        tests.helpers.factories.peri_scribe.monitor.status.report_build(),
        (
            tests.helpers.factories.peri_scribe.monitor.status.record(
                "Finished phase",
                phase="reports",
                run_id="building",
                status="failed",
            ),
        ),
        now,
    )
    view = peri_scribe.monitor.status.project(
        history,
        tests.helpers.factories.peri_scribe.monitor.status.files(),
        now,
    )
    assert view.metrics[1].health == peri_scribe.monitor.status.Health.WARNING


@pytest.mark.parametrize(
    ("phase", "health"),
    [
        ("", peri_scribe.monitor.status.Health.WARNING),
        ("fetch", peri_scribe.monitor.status.Health.WARNING),
        ("reports", peri_scribe.monitor.status.Health.ACTIVE),
    ],
)
def test_project_only_report_work_in_a_later_run_explains_report_lag(
    phase: str,
    health: peri_scribe.monitor.status.Health,
) -> None:
    now = tests.helpers.factories.peri_scribe.monitor.status.NOW
    history = peri_scribe.monitor.history.append(
        tests.helpers.factories.peri_scribe.monitor.status.report_build(),
        (
            tests.helpers.factories.peri_scribe.monitor.status.record(
                "Finished command",
                run_id="building",
                status="completed",
            ),
            tests.helpers.factories.peri_scribe.monitor.status.record(
                "Starting command",
                run_id="later",
                command="run",
            ),
            tests.helpers.factories.peri_scribe.monitor.status.record(
                "Starting phase",
                phase=phase,
                run_id="later",
            ),
        ),
        now,
    )
    view = peri_scribe.monitor.status.project(
        history,
        tests.helpers.factories.peri_scribe.monitor.status.files(),
        now,
    )
    assert view.metrics[1].health == health


def test_project_fresh_complete_system_is_green() -> None:
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
    view = peri_scribe.monitor.status.project(
        history,
        tests.helpers.factories.peri_scribe.monitor.status.files(),
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
    metric = peri_scribe.monitor.status.activity_metric(
        history,
        tests.helpers.factories.peri_scribe.monitor.status.NOW,
    )
    assert metric.target is not None
    assert metric.target.run == "run-1"
    assert "fetch → query-features" in metric.text
    assert "lock" in peri_scribe.monitor.status.recent_metrics(history)[0].text


@pytest.mark.parametrize(
    ("files", "health"),
    [
        (
            peri_scribe.monitor.status.Files(
                kmz=peri_scribe.monitor.status.Output(),
                report=peri_scribe.monitor.status.Output(),
                pending=("reports",),
            ),
            peri_scribe.monitor.status.Health.WARNING,
        ),
        (
            peri_scribe.monitor.status.Files(
                kmz=peri_scribe.monitor.status.Output(),
                report=peri_scribe.monitor.status.Output(),
                error="broken state",
            ),
            peri_scribe.monitor.status.Health.WARNING,
        ),
    ],
)
def test_publication_metric_pending_or_unreadable_state_needs_attention(
    files: peri_scribe.monitor.status.Files,
    health: peri_scribe.monitor.status.Health,
) -> None:
    assert peri_scribe.monitor.status.publication_metric(files, ()).health == health


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
    view = peri_scribe.monitor.status.project(
        history,
        tests.helpers.factories.peri_scribe.monitor.status.files(),
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
    formatter = unittest.mock.Mock(wraps=peri_scribe.monitor.status.local_time)
    monkeypatch.setattr(peri_scribe.monitor.status, "local_time", formatter)
    metrics = peri_scribe.monitor.status.transition_metrics(
        peri_scribe.monitor.status.evidence(history),
        peri_scribe.monitor.status.Metric(
            label="Failure",
            text="None",
            health=peri_scribe.monitor.status.Health.GOOD,
        ),
    )
    expected = range(8) if same_time else range(19, 11, -1)
    assert [metric.target.run for metric in metrics if metric.target] == [
        str(index) for index in expected
    ]
    assert formatter.call_count == len(metrics)


def test_project_reuses_observations_without_freezing_future_event_visibility() -> None:
    now = tests.helpers.factories.peri_scribe.monitor.status.NOW
    history = tests.helpers.factories.peri_scribe.monitor.status.history(
        tests.helpers.factories.peri_scribe.monitor.status.finished(
            "kmz",
            when=now + datetime.timedelta(minutes=1),
        ),
    )
    observations = peri_scribe.monitor.status.evidence(history)
    for when in (now, now + datetime.timedelta(minutes=2)):
        assert peri_scribe.monitor.status.project(
            history,
            tests.helpers.factories.peri_scribe.monitor.status.files(),
            when,
            observations=observations,
        ) == peri_scribe.monitor.status.project(
            history,
            tests.helpers.factories.peri_scribe.monitor.status.files(),
            when,
        )


def test_exception_groups_keep_unresolved_failures_visible_after_another_retry() -> (
    None
):
    history = tests.helpers.factories.peri_scribe.monitor.status.history(
        tests.helpers.factories.peri_scribe.monitor.status.record(
            "Finished command",
            status="failed",
            exception="ValueError: broken",
            run_id="failed",
        ),
        tests.helpers.factories.peri_scribe.monitor.status.record(
            "Retry",
            exception="ValueError: broken",
            run_id="retry",
        ),
    )
    groups = peri_scribe.monitor.status.exception_groups(
        history,
        peri_scribe.monitor.status.evidence(history),
        tests.helpers.factories.peri_scribe.monitor.status.NOW,
    )
    assert groups[0].health == peri_scribe.monitor.status.Health.BAD
    assert groups[0].latest.run == "retry"


def test_recent_metrics_unfinished_run_is_uncertain() -> None:
    history = tests.helpers.factories.peri_scribe.monitor.status.history(
        tests.helpers.factories.peri_scribe.monitor.status.record(
            "Starting command",
            command="run",
        ),
    )
    run = dataclasses.replace(
        history.state.runs[0],
        status=peri_scribe.monitor.model.Status.STOPPED,
    )
    history = dataclasses.replace(
        history,
        state=dataclasses.replace(history.state, runs=(run,)),
    )
    assert (
        peri_scribe.monitor.status.recent_metrics(history)[0].health
        == peri_scribe.monitor.status.Health.WARNING
    )


def test_publication_metric_successful_build_without_gate_is_healthy() -> None:
    history = tests.helpers.factories.peri_scribe.monitor.status.history(
        tests.helpers.factories.peri_scribe.monitor.status.finished("kmz"),
    )
    metric = peri_scribe.monitor.status.publication_metric(
        tests.helpers.factories.peri_scribe.monitor.status.files(),
        peri_scribe.monitor.status.evidence(history),
    )
    assert metric.health == peri_scribe.monitor.status.Health.GOOD
    assert metric.target is not None
