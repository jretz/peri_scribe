"""Cached health agrees with fresh calculations at time and evidence boundaries."""

import dataclasses
import datetime

import pytest

import peri_scribe.monitor.history
import peri_scribe.monitor.projection
import peri_scribe.monitor.status
import tests.helpers.factories.peri_scribe.monitor.status


def test_refresh_reuses_status_until_a_displayed_age_changes() -> None:
    now = tests.helpers.factories.peri_scribe.monitor.status.NOW
    history = tests.helpers.factories.peri_scribe.monitor.status.history(
        tests.helpers.factories.peri_scribe.monitor.status.finished("kmz"),
    )
    files = tests.helpers.factories.peri_scribe.monitor.status.files()
    first = peri_scribe.monitor.projection.refresh(history, files, now)
    assert (
        peri_scribe.monitor.projection.refresh(
            history,
            files,
            now + datetime.timedelta(seconds=30),
            first,
        )
        is first
    )
    later = peri_scribe.monitor.projection.refresh(
        history,
        files,
        now + datetime.timedelta(minutes=1),
        first,
    )
    assert later.view != first.view
    assert later.view.transitions is first.view.transitions


@pytest.mark.parametrize(
    "offset",
    [0, 1, 60, 18000, 21600, 21600.000001, 86400, 172800, 172800.000001, 172820.000001],
)
def test_refresh_matches_fresh_status_across_age_and_expiry_boundaries(
    offset: float,
) -> None:
    now = tests.helpers.factories.peri_scribe.monitor.status.NOW
    history = tests.helpers.factories.peri_scribe.monitor.status.history(
        *tests.helpers.factories.peri_scribe.monitor.status.failed_run(),
        tests.helpers.factories.peri_scribe.monitor.status.finished(
            "reports",
            run_id="recovered",
            when=now + datetime.timedelta(seconds=20),
        ),
        tests.helpers.factories.peri_scribe.monitor.status.finished("kmz"),
    )
    files = tests.helpers.factories.peri_scribe.monitor.status.files()
    snapshot = peri_scribe.monitor.projection.refresh(history, files, now)
    later = now + datetime.timedelta(seconds=offset)
    actual = peri_scribe.monitor.projection.refresh(history, files, later, snapshot)
    assert actual.view == peri_scribe.monitor.status.project(history, files, later)


def test_refresh_tracks_failure_completion_age_separately_from_origin() -> None:
    now = tests.helpers.factories.peri_scribe.monitor.status.NOW
    records = tests.helpers.factories.peri_scribe.monitor.status.failed_run()
    history = tests.helpers.factories.peri_scribe.monitor.status.history(
        *records[:-1],
        {
            **records[-1],
            "timestamp": (now + datetime.timedelta(seconds=27)).isoformat(),
        },
    )
    files = tests.helpers.factories.peri_scribe.monitor.status.files()
    before = now + datetime.timedelta(seconds=80)
    after = now + datetime.timedelta(seconds=88)
    snapshot = peri_scribe.monitor.projection.refresh(history, files, before)
    actual = peri_scribe.monitor.projection.refresh(history, files, after, snapshot)
    assert actual.view == peri_scribe.monitor.status.project(history, files, after)


def test_refresh_tracks_active_elapsed_time_independently_of_last_progress() -> None:
    now = tests.helpers.factories.peri_scribe.monitor.status.NOW
    history = tests.helpers.factories.peri_scribe.monitor.status.history(
        tests.helpers.factories.peri_scribe.monitor.status.record(
            "Starting command",
            command="run",
            when=now - datetime.timedelta(seconds=50),
        ),
        tests.helpers.factories.peri_scribe.monitor.status.record("Working", when=now),
    )
    files = tests.helpers.factories.peri_scribe.monitor.status.files()
    first = peri_scribe.monitor.projection.refresh(history, files, now)
    later = now + datetime.timedelta(seconds=11)
    assert peri_scribe.monitor.projection.refresh(
        history,
        files,
        later,
        first,
    ).view == peri_scribe.monitor.status.project(history, files, later)


def test_refresh_invalidates_metadata_and_file_changes() -> None:
    now = tests.helpers.factories.peri_scribe.monitor.status.NOW
    history = tests.helpers.factories.peri_scribe.monitor.status.history()
    files = tests.helpers.factories.peri_scribe.monitor.status.files()
    snapshot = peri_scribe.monitor.projection.refresh(history, files, now)
    history = dataclasses.replace(
        history,
        errors=("Unreadable archive",),
        caught_up=False,
    )
    files = dataclasses.replace(files, pending=("reports",))
    assert peri_scribe.monitor.projection.refresh(
        history,
        files,
        now,
        snapshot,
    ).view == peri_scribe.monitor.status.project(history, files, now)


def test_refresh_invalidates_changed_evidence() -> None:
    now = tests.helpers.factories.peri_scribe.monitor.status.NOW
    history = tests.helpers.factories.peri_scribe.monitor.status.history()
    files = tests.helpers.factories.peri_scribe.monitor.status.files()
    snapshot = peri_scribe.monitor.projection.refresh(history, files, now)
    updated = tests.helpers.factories.peri_scribe.monitor.status.history(
        *tests.helpers.factories.peri_scribe.monitor.status.failed_run(),
    )
    assert peri_scribe.monitor.projection.refresh(
        updated,
        files,
        now,
        snapshot,
    ).view == peri_scribe.monitor.status.project(updated, files, now)


def test_refresh_invalidates_time_moving_backward() -> None:
    now = tests.helpers.factories.peri_scribe.monitor.status.NOW
    history = tests.helpers.factories.peri_scribe.monitor.status.history()
    files = tests.helpers.factories.peri_scribe.monitor.status.files()
    future = peri_scribe.monitor.projection.refresh(
        history,
        files,
        now + datetime.timedelta(days=1),
    )
    assert peri_scribe.monitor.projection.refresh(
        history,
        files,
        now,
        future,
    ).view == peri_scribe.monitor.status.project(history, files, now)


def test_refresh_empty_history_without_timestamps_has_no_clock_deadline() -> None:
    history = peri_scribe.monitor.history.History()
    output = peri_scribe.monitor.status.Output(error="Missing", missing=True)
    files = peri_scribe.monitor.status.Files(kmz=output, report=output)
    result = peri_scribe.monitor.projection.refresh(
        history,
        files,
        tests.helpers.factories.peri_scribe.monitor.status.NOW,
    )
    assert result.changes_at is None


def test_refresh_handles_far_future_diagnostic_timestamps() -> None:
    now = tests.helpers.factories.peri_scribe.monitor.status.NOW
    future = datetime.datetime.max.replace(tzinfo=datetime.UTC)
    history = tests.helpers.factories.peri_scribe.monitor.status.history(
        *tests.helpers.factories.peri_scribe.monitor.status.failed_run(when=future),
    )
    files = tests.helpers.factories.peri_scribe.monitor.status.files()
    snapshot = peri_scribe.monitor.projection.refresh(history, files, now)
    assert snapshot.view == peri_scribe.monitor.status.project(history, files, now)
    assert history.expires is None


@pytest.mark.parametrize(
    ("offset", "expected"),
    [
        (datetime.timedelta(), peri_scribe.monitor.status.Health.GOOD),
        (datetime.timedelta(days=2), peri_scribe.monitor.status.Health.GOOD),
        (
            datetime.timedelta(days=2, microseconds=1),
            peri_scribe.monitor.status.Health.BAD,
        ),
        (datetime.timedelta(days=3), peri_scribe.monitor.status.Health.GOOD),
        (datetime.timedelta(days=5), peri_scribe.monitor.status.Health.GOOD),
        (
            datetime.timedelta(days=5, microseconds=1),
            peri_scribe.monitor.status.Health.BAD,
        ),
    ],
)
def test_refresh_tracks_coverage_across_compacted_progress_and_future_entries(
    offset: datetime.timedelta,
    expected: peri_scribe.monitor.status.Health,
) -> None:
    now = tests.helpers.factories.peri_scribe.monitor.status.NOW
    history = tests.helpers.factories.peri_scribe.monitor.status.history(
        tests.helpers.factories.peri_scribe.monitor.status.record("Current progress"),
        tests.helpers.factories.peri_scribe.monitor.status.record(
            "Future progress",
            when=now + datetime.timedelta(days=3),
        ),
        tests.helpers.factories.peri_scribe.monitor.status.record(
            "Later progress",
            when=now + datetime.timedelta(days=10),
        ),
    )
    output = peri_scribe.monitor.status.Output(error="Missing", missing=True)
    files = peri_scribe.monitor.status.Files(kmz=output, report=output)
    snapshot = peri_scribe.monitor.projection.refresh(
        history,
        files,
        now + offset - datetime.timedelta(microseconds=1),
    )
    result = peri_scribe.monitor.projection.refresh(
        history,
        files,
        now + offset,
        snapshot,
    )
    assert result.view.coverage.health == expected
