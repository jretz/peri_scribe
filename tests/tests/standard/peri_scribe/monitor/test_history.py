"""Status history survives bounded UI retention, restarts, and monthly compression."""

import compression.zstd
import concurrent.futures
import contextlib
import datetime
import json
import pathlib
import threading
import unittest.mock

import pytest

import peri_scribe.monitor.history
import peri_scribe.monitor.model
import peri_scribe.monitor.status
import peri_scribe.monitor.storage
import peri_scribe.phases
import tests.helpers.doubles.errors
import tests.helpers.doubles.peri_scribe.monitor.history
import tests.helpers.factories.peri_scribe.monitor.events
import tests.helpers.factories.peri_scribe.monitor.history
import tests.helpers.factories.peri_scribe.monitor.status


def test_append_retains_every_recent_failed_run_beyond_interactive_limit() -> None:
    count = peri_scribe.monitor.model.MAXIMUM_RUNS + 5
    history = tests.helpers.factories.peri_scribe.monitor.status.history(
        *(
            record
            for number in range(count)
            for record in tests.helpers.factories.peri_scribe.monitor.status.failed_run(
                run_id=str(number),
            )
        ),
    )
    groups = peri_scribe.monitor.status.exception_groups(
        history,
        peri_scribe.monitor.status.evidence(history),
        tests.helpers.factories.peri_scribe.monitor.status.NOW,
    )
    assert groups[0].occurrences == count
    assert len(groups[0].runs) == count


def test_append_preserves_all_exceptions_beyond_event_limit() -> None:
    count = peri_scribe.monitor.model.MAXIMUM_EVENTS_PER_RUN + 1
    records = tuple(
        tests.helpers.factories.peri_scribe.monitor.status.record(
            "Retry",
            exception="TimeoutError: timed out",
        )
        for _ in range(count)
    )
    history = tests.helpers.factories.peri_scribe.monitor.status.history(*records)
    assert len(history.state.runs[0].events) == count


def test_append_discards_verbose_events_but_keeps_latest_progress() -> None:
    history = tests.helpers.factories.peri_scribe.monitor.status.history(
        *(
            tests.helpers.factories.peri_scribe.monitor.status.record(
                f"Progress {number}",
            )
            for number in range(20)
        ),
    )
    history = peri_scribe.monitor.history.append(
        history,
        (tests.helpers.factories.peri_scribe.monitor.status.record("Latest progress"),),
        tests.helpers.factories.peri_scribe.monitor.status.NOW,
    )
    assert [event.message for event in history.state.runs[0].events] == [
        "Latest progress",
    ]


def test_append_discards_old_failure_and_successful_stage_landmarks() -> None:
    now = tests.helpers.factories.peri_scribe.monitor.status.NOW
    old = now - datetime.timedelta(days=30)
    history = tests.helpers.factories.peri_scribe.monitor.status.history(
        *tests.helpers.factories.peri_scribe.monitor.status.failed_run(when=old),
        tests.helpers.factories.peri_scribe.monitor.status.finished(
            "kmz",
            when=old,
            run_id="output",
        ),
        *(
            tests.helpers.factories.peri_scribe.monitor.status.record(
                "Finished command",
                when=old + datetime.timedelta(hours=number),
                run_id=str(number),
                command="run",
                status="completed",
            )
            for number in range(40)
        ),
    )
    assert not history.state.runs


def test_append_retains_runs_at_the_inclusive_cutoff() -> None:
    now = tests.helpers.factories.peri_scribe.monitor.status.NOW
    cutoff = now - peri_scribe.monitor.history.WINDOW
    history = tests.helpers.factories.peri_scribe.monitor.status.history(
        tests.helpers.factories.peri_scribe.monitor.status.finished(
            "kmz",
            when=cutoff - datetime.timedelta(microseconds=1),
            run_id="expired",
        ),
        tests.helpers.factories.peri_scribe.monitor.status.finished(
            "kmz",
            when=cutoff,
            run_id="boundary",
        ),
    )
    assert [run.identifier for run in history.state.runs] == ["boundary"]


def test_append_expires_history_without_new_records() -> None:
    now = tests.helpers.factories.peri_scribe.monitor.status.NOW
    history = tests.helpers.factories.peri_scribe.monitor.status.history(
        *tests.helpers.factories.peri_scribe.monitor.status.failed_run(),
    )
    at_cutoff = peri_scribe.monitor.history.append(
        history,
        (),
        now + peri_scribe.monitor.history.WINDOW,
    )
    assert at_cutoff is history
    expired = peri_scribe.monitor.history.append(
        at_cutoff,
        (),
        now + peri_scribe.monitor.history.WINDOW + datetime.timedelta(seconds=1),
    )
    assert not expired.state.runs
    assert history.state.runs


def test_append_exposes_undated_records() -> None:
    history = tests.helpers.factories.peri_scribe.monitor.status.history({
        "event": "broken line",
    })
    assert history.undated == 1
    assert not history.coverage
    assert (
        peri_scribe.monitor.history.last_time(history.state.runs[0]).year
        == datetime.MINYEAR
    )


def test_append_preserves_coverage_when_progress_is_undated() -> None:
    now = tests.helpers.factories.peri_scribe.monitor.status.NOW
    history = tests.helpers.factories.peri_scribe.monitor.status.history(
        tests.helpers.factories.peri_scribe.monitor.status.record("Progress"),
    )
    history = peri_scribe.monitor.history.append(
        history,
        ({"event": "Undated progress", "run_id": "run-1"},),
        now,
    )
    assert (
        peri_scribe.monitor.status.coverage_metric(history, now).health
        == peri_scribe.monitor.status.Health.WARNING
    )


def test_append_recovers_coverage_after_future_progress() -> None:
    now = tests.helpers.factories.peri_scribe.monitor.status.NOW
    history = tests.helpers.factories.peri_scribe.monitor.status.history(
        tests.helpers.factories.peri_scribe.monitor.status.record(
            "Future progress",
            when=now + datetime.timedelta(days=3),
        ),
    )
    history = peri_scribe.monitor.history.append(
        history,
        (tests.helpers.factories.peri_scribe.monitor.status.record("Current"),),
        now,
    )
    assert (
        peri_scribe.monitor.status.coverage_metric(history, now).health
        == peri_scribe.monitor.status.Health.GOOD
    )


def test_append_merges_coverage_for_frequent_progress() -> None:
    now = tests.helpers.factories.peri_scribe.monitor.status.NOW
    history = tests.helpers.factories.peri_scribe.monitor.status.history(
        *(
            tests.helpers.factories.peri_scribe.monitor.status.record(
                "Progress",
                when=now - datetime.timedelta(minutes=number),
            )
            for number in range(120)
        ),
    )
    assert history.coverage == (
        peri_scribe.monitor.history.Coverage(
            start=now - datetime.timedelta(minutes=119),
            end=now + peri_scribe.monitor.history.WINDOW,
        ),
    )


def test_append_expires_coverage_before_future_records() -> None:
    now = tests.helpers.factories.peri_scribe.monitor.status.NOW
    future = now + datetime.timedelta(days=10)
    history = tests.helpers.factories.peri_scribe.monitor.status.history(
        tests.helpers.factories.peri_scribe.monitor.status.record("Current"),
        tests.helpers.factories.peri_scribe.monitor.status.record(
            "Future",
            when=future,
        ),
    )
    expired = peri_scribe.monitor.history.append(
        history,
        (),
        now + peri_scribe.monitor.history.WINDOW + datetime.timedelta(microseconds=1),
    )
    assert expired.coverage == (
        peri_scribe.monitor.history.Coverage(
            start=future,
            end=future + peri_scribe.monitor.history.WINDOW,
        ),
    )


def test_reader_full_startup_counts_before_tail_limit(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tests.helpers.factories.peri_scribe.monitor.events.write_log(
        tmp_path,
        *tests.helpers.factories.peri_scribe.monitor.status.failed_run(),
    )
    monkeypatch.setattr(peri_scribe.monitor.storage, "MAXIMUM_READ_BYTES", 90)
    with contextlib.closing(
        peri_scribe.monitor.history.Reader(tmp_path / "logs"),
    ) as reader:
        history = reader.poll(tests.helpers.factories.peri_scribe.monitor.status.NOW)
        assert not history.caught_up
        while not history.caught_up:
            history = reader.poll(
                tests.helpers.factories.peri_scribe.monitor.status.NOW,
            )
        groups = peri_scribe.monitor.status.exception_groups(
            history,
            peri_scribe.monitor.status.evidence(history),
            tests.helpers.factories.peri_scribe.monitor.status.NOW,
        )
        assert groups[0].occurrences == 1
        assert (
            reader.poll(tests.helpers.factories.peri_scribe.monitor.status.NOW).state
            == history.state
        )


def test_reader_catch_up_publishes_all_batches_together(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = tests.helpers.factories.peri_scribe.monitor.status.failed_run()
    path = tests.helpers.factories.peri_scribe.monitor.events.write_log(
        tmp_path,
        *records,
    )
    monkeypatch.setattr(peri_scribe.monitor.storage, "MAXIMUM_READ_BYTES", 90)
    with contextlib.closing(peri_scribe.monitor.history.Reader(path.parent)) as reader:
        history = reader.catch_up(
            tests.helpers.factories.peri_scribe.monitor.status.NOW,
        )
    assert history.caught_up
    assert [dict(event.fields) for event in history.state.runs[0].events] == list(
        records,
    )


def test_reader_catch_up_stops_on_errors(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    poll = unittest.mock.Mock(
        return_value=peri_scribe.monitor.storage.Batch(
            caught_up=False,
            errors=("Unreadable log",),
        ),
    )
    with contextlib.closing(peri_scribe.monitor.history.Reader(tmp_path)) as reader:
        monkeypatch.setattr(reader.follower, "poll", poll)
        history = reader.catch_up(
            tests.helpers.factories.peri_scribe.monitor.status.NOW,
        )
    assert history.errors == ("Unreadable log",)
    poll.assert_called_once()


def test_reader_catch_up_does_not_reopen_after_close(tmp_path: pathlib.Path) -> None:
    reader = peri_scribe.monitor.history.Reader(tmp_path)
    reader.close()
    assert (
        reader.catch_up(tests.helpers.factories.peri_scribe.monitor.status.NOW)
        is reader.history
    )


def test_reader_close_interrupts_catch_up_after_the_active_batch(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reader = peri_scribe.monitor.history.Reader(tmp_path)
    started = threading.Event()
    release = threading.Event()
    poll = unittest.mock.Mock(
        side_effect=tests.helpers.doubles.peri_scribe.monitor.history.BlockedPoll(
            started=started,
            release=release,
        ),
    )
    monkeypatch.setattr(reader.follower, "poll", poll)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        reading = executor.submit(
            reader.catch_up,
            tests.helpers.factories.peri_scribe.monitor.status.NOW,
        )
        try:
            assert started.wait(timeout=5)
            closing = executor.submit(reader.close)
            assert reader.stopped.wait(timeout=5)
            assert not closing.done()
        finally:
            release.set()
        closing.result(timeout=5)
        assert not reading.result(timeout=5).caught_up
    poll.assert_called_once()


def test_reader_poll_stops_archive_processing_on_shutdown(
    tmp_path: pathlib.Path,
) -> None:
    path = tmp_path / "2026-09.jsonl.zst"
    with compression.zstd.open(path, "wt") as stream:
        stream.write(
            json.dumps(
                tests.helpers.factories.peri_scribe.monitor.status.record(
                    "Recent",
                ),
            )
            + "\n",
        )
    with contextlib.closing(peri_scribe.monitor.history.Reader(tmp_path)) as reader:
        reader.stopped.set()
        assert not reader.poll(
            tests.helpers.factories.peri_scribe.monitor.status.NOW,
        ).state.runs


def test_reader_skips_old_records_before_processing_the_recent_window(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = tests.helpers.factories.peri_scribe.monitor.status.NOW
    tests.helpers.factories.peri_scribe.monitor.events.write_log(
        tmp_path,
        *(
            tests.helpers.factories.peri_scribe.monitor.status.record(
                "Old progress",
                when=now - datetime.timedelta(days=3),
                run_id="old",
            )
            for _ in range(1000)
        ),
        tests.helpers.factories.peri_scribe.monitor.status.record(
            "Recent progress",
            run_id="recent",
        ),
    )
    monkeypatch.setattr(peri_scribe.monitor.storage, "MAXIMUM_READ_BYTES", 1024)
    with contextlib.closing(
        peri_scribe.monitor.history.Reader(tmp_path / "logs"),
    ) as reader:
        history = reader.poll(now)
    assert history.caught_up
    assert [run.identifier for run in history.state.runs] == ["recent"]
    assert history.state.sequence == 1


@pytest.mark.parametrize("compressed", [False, True])
@pytest.mark.parametrize(
    ("now", "elapsed_hours"),
    [
        (datetime.datetime(2026, 9, 16, 12, tzinfo=datetime.UTC), 49),
        (datetime.datetime(2026, 9, 1, 12, tzinfo=datetime.UTC), 49),
        (datetime.datetime(2026, 9, 3, 12, tzinfo=datetime.UTC), 72),
    ],
)
def test_reader_restores_active_run_context_before_the_recent_window(
    tmp_path: pathlib.Path,
    now: datetime.datetime,
    elapsed_hours: int,
    *,
    compressed: bool,
) -> None:
    started = now - datetime.timedelta(hours=elapsed_hours)
    path = (peri_scribe.phases.Segment(phase="fetch"),)
    records = tests.helpers.factories.peri_scribe.monitor.history.active_run_records(
        started,
        now,
    )
    opener = compression.zstd.open if compressed else pathlib.Path.open
    for when, record in zip((started, started, now), records, strict=True):
        filename = when.strftime("%Y-%m.jsonl") + (".zst" if compressed else "")
        with opener(tmp_path / filename, "at", encoding="utf-8") as stream:
            stream.write(json.dumps(record) + "\n")
    with contextlib.closing(peri_scribe.monitor.history.Reader(tmp_path)) as reader:
        history = reader.catch_up(now)
    assert len(history.state.runs) == 1
    run = history.state.runs[0]
    assert run.command == "run"
    assert run.status == peri_scribe.monitor.model.Status.ACTIVE
    assert run.open_path == path
    assert [
        event.timestamp for event in run.events if event.message == "Starting command"
    ] == [started]
    activity = peri_scribe.monitor.status.activity_metric(history, now)
    assert activity.health == peri_scribe.monitor.status.Health.ACTIVE
    assert activity.target is not None
    assert activity.target.event.timestamp == now


def test_context_records_stops_after_shutdown() -> None:
    now = tests.helpers.factories.peri_scribe.monitor.status.NOW
    records = tests.helpers.factories.peri_scribe.monitor.history.active_run_records(
        now - datetime.timedelta(hours=49),
        now,
    )
    stopped = threading.Event()
    stopped.set()
    assert not tuple(
        peri_scribe.monitor.history.context_records(
            records,
            {"run-1": now - peri_scribe.monitor.history.WINDOW},
            stopped,
        ),
    )


def test_reader_context_recovery_does_not_duplicate_previously_loaded_boundary(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = tests.helpers.factories.peri_scribe.monitor.status.NOW
    started = now - datetime.timedelta(hours=49)
    boundary = now - peri_scribe.monitor.history.WINDOW + datetime.timedelta(seconds=1)
    records = (
        *tests.helpers.factories.peri_scribe.monitor.history.active_run_records(
            started,
            now,
        )[:2],
        tests.helpers.factories.peri_scribe.monitor.status.finished(
            "fetch",
            when=boundary,
        ),
        tests.helpers.factories.peri_scribe.monitor.status.record(
            "Starting phase",
            phase="kmz",
            when=now,
        ),
        tests.helpers.factories.peri_scribe.monitor.status.record(
            "Building output",
            phase="kmz",
            when=now,
        ),
    )
    path = tests.helpers.factories.peri_scribe.monitor.events.write_log(
        tmp_path,
        *records,
    )
    monkeypatch.setattr(
        peri_scribe.monitor.storage,
        "MAXIMUM_READ_BYTES",
        len(json.dumps(records[2]).encode()) + 1,
    )
    with contextlib.closing(peri_scribe.monitor.history.Reader(path.parent)) as reader:
        first = reader.poll(now)
        assert not first.caught_up
        assert [dict(event.fields) for event in first.state.runs[0].events] == [
            records[2],
        ]
        history = reader.catch_up(now + datetime.timedelta(seconds=2))
    assert [dict(event.fields) for event in history.state.runs[0].events] == list(
        records,
    )


def test_reader_does_not_duplicate_restored_context_after_polling_or_rotation(
    tmp_path: pathlib.Path,
) -> None:
    now = tests.helpers.factories.peri_scribe.monitor.status.NOW
    records = tests.helpers.factories.peri_scribe.monitor.history.active_run_records(
        now - datetime.timedelta(hours=49),
        now,
    )
    path = tests.helpers.factories.peri_scribe.monitor.events.write_log(
        tmp_path,
        *records,
    )
    with contextlib.closing(peri_scribe.monitor.history.Reader(path.parent)) as reader:
        history = reader.catch_up(now)
        assert [dict(event.fields) for event in history.state.runs[0].events] == list(
            records,
        )
        assert reader.poll(now).state == history.state
        with compression.zstd.open(path.with_suffix(".jsonl.zst"), "wt") as stream:
            stream.write(path.read_text())
        path.unlink()
        assert reader.poll(now).state == history.state


def test_reader_context_recovery_ignores_archives_before_the_command_started(
    tmp_path: pathlib.Path,
) -> None:
    now = tests.helpers.factories.peri_scribe.monitor.status.NOW
    records = tests.helpers.factories.peri_scribe.monitor.history.active_run_records(
        now - datetime.timedelta(hours=49),
        now,
    )
    path = tests.helpers.factories.peri_scribe.monitor.events.write_log(
        tmp_path,
        *records,
    )
    (path.parent / "2026-08.jsonl.zst").write_bytes(b"corrupt unrelated archive")
    with contextlib.closing(peri_scribe.monitor.history.Reader(path.parent)) as reader:
        history = reader.catch_up(now)
    assert history.state.runs[0].command == "run"
    assert not history.errors


def test_reader_reports_unreadable_context_without_repeating_the_error(
    tmp_path: pathlib.Path,
) -> None:
    now = tests.helpers.factories.peri_scribe.monitor.status.NOW
    records = tests.helpers.factories.peri_scribe.monitor.history.active_run_records(
        now - datetime.timedelta(hours=49),
        now,
    )
    path = tests.helpers.factories.peri_scribe.monitor.events.write_log(
        tmp_path,
        records[-1],
    )
    (path.parent / "2026-08.jsonl.zst").write_bytes(b"corrupt needed archive")
    with contextlib.closing(peri_scribe.monitor.history.Reader(path.parent)) as reader:
        history = reader.catch_up(now)
        assert len(history.errors) == 1
        assert "2026-08.jsonl.zst" in history.errors[0]
        assert reader.poll(now).errors == history.errors


@pytest.mark.parametrize("clock_only", [False, True])
def test_reader_restores_expired_run_context_when_recent_progress_resumes(
    tmp_path: pathlib.Path,
    *,
    clock_only: bool,
) -> None:
    now = tests.helpers.factories.peri_scribe.monitor.status.NOW
    started = now - datetime.timedelta(hours=49)
    records = tests.helpers.factories.peri_scribe.monitor.history.active_run_records(
        started,
        now,
    )
    path = tests.helpers.factories.peri_scribe.monitor.events.write_log(
        tmp_path,
        *records,
    )
    later = now + peri_scribe.monitor.history.WINDOW + datetime.timedelta(seconds=1)
    with contextlib.closing(peri_scribe.monitor.history.Reader(path.parent)) as reader:
        assert reader.catch_up(now).state.runs[0].command == "run"
        if clock_only:
            reader.history = peri_scribe.monitor.history.append(
                reader.history,
                (),
                later,
            )
            assert not reader.history.state.runs
        else:
            assert not reader.poll(later).state.runs
        progress = (
            tests.helpers.factories.peri_scribe.monitor.history.active_run_records(
                started,
                later,
            )[-1]
        )
        tests.helpers.factories.peri_scribe.monitor.events.write_log(tmp_path, progress)
        history = reader.catch_up(later)
    assert len(history.state.runs) == 1
    run = history.state.runs[0]
    assert run.command == "run"
    assert run.status == peri_scribe.monitor.model.Status.ACTIVE
    assert run.open_path == (peri_scribe.phases.Segment(phase="fetch"),)
    assert [dict(event.fields) for event in run.events] == [*records[:2], progress]


def test_reader_restarts_with_compressed_history_and_follows_new_errors(
    tmp_path: pathlib.Path,
) -> None:
    now = datetime.datetime(2026, 9, 1, 12, tzinfo=datetime.UTC)
    directory = tmp_path / "logs"
    directory.mkdir()
    path = directory / "2026-08.jsonl.zst"
    with compression.zstd.open(path, "wt") as stream:
        for record in (
            *tests.helpers.factories.peri_scribe.monitor.status.failed_run(
                run_id="old",
                when=now - datetime.timedelta(days=3),
            ),
            *tests.helpers.factories.peri_scribe.monitor.status.failed_run(
                run_id="archive",
                when=now - datetime.timedelta(days=1),
            ),
        ):
            stream.write(json.dumps(record) + "\n")
    with contextlib.closing(peri_scribe.monitor.history.Reader(directory)) as reader:
        history = reader.poll(now)
        assert [run.identifier for run in history.state.runs] == ["archive"]
        tests.helpers.factories.peri_scribe.monitor.events.write_log(
            tmp_path,
            *tests.helpers.factories.peri_scribe.monitor.status.failed_run(
                run_id="live",
                when=now,
            ),
        )
        history = reader.poll(now)
        assert {run.identifier for run in history.state.runs} == {"archive", "live"}
        assert reader.poll(now).state == history.state


def test_reader_rotation_does_not_count_a_month_twice(tmp_path: pathlib.Path) -> None:
    path = tests.helpers.factories.peri_scribe.monitor.events.write_log(
        tmp_path,
        *tests.helpers.factories.peri_scribe.monitor.status.failed_run(),
    )
    with contextlib.closing(peri_scribe.monitor.history.Reader(path.parent)) as reader:
        reader.poll(tests.helpers.factories.peri_scribe.monitor.status.NOW)
        with compression.zstd.open(path.with_suffix(".jsonl.zst"), "wt") as stream:
            stream.write(path.read_text())
        path.unlink()
        history = reader.poll(tests.helpers.factories.peri_scribe.monitor.status.NOW)
        assert (
            peri_scribe.monitor.status.exception_groups(
                history,
                peri_scribe.monitor.status.evidence(history),
                tests.helpers.factories.peri_scribe.monitor.status.NOW,
            )[0].occurrences
            == 1
        )


def test_reader_reports_corrupt_archives(tmp_path: pathlib.Path) -> None:
    (tmp_path / "2026-09.jsonl.zst").write_bytes(b"invalid")
    with contextlib.closing(peri_scribe.monitor.history.Reader(tmp_path)) as reader:
        assert reader.poll(
            tests.helpers.factories.peri_scribe.monitor.status.NOW,
        ).errors


def test_reader_skips_archives_older_than_the_window(tmp_path: pathlib.Path) -> None:
    (tmp_path / "2026-08.jsonl.zst").write_bytes(b"invalid")
    with contextlib.closing(peri_scribe.monitor.history.Reader(tmp_path)) as reader:
        history = reader.poll(tests.helpers.factories.peri_scribe.monitor.status.NOW)
    assert not history.errors
    assert history.caught_up
    assert not history.state.runs


def test_records_from_ignores_partial_and_blank_lines(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "log.jsonl"
    path.write_text('\n{"event":"complete"}\n{"event":"partial"')
    assert tuple(peri_scribe.monitor.history.records_from(path)) == (
        {"event": "complete"},
    )


def test_record_batches_keeps_the_final_partial_batch() -> None:
    count = peri_scribe.monitor.history.BATCH_SIZE + 1
    assert (
        sum(
            len(batch)
            for batch in peri_scribe.monitor.history.record_batches(
                {"event": str(number)} for number in range(count)
            )
        )
        == count
    )


def test_log_paths_prefers_uncompressed_month_during_rotation(
    tmp_path: pathlib.Path,
) -> None:
    plain = tmp_path / "2026-09.jsonl"
    plain.touch()
    plain.with_suffix(".jsonl.zst").touch()
    assert peri_scribe.monitor.history.log_paths(tmp_path) == (plain,)


def test_load_run_loads_complete_archived_run_without_other_runs(
    tmp_path: pathlib.Path,
) -> None:
    path = tmp_path / "2026-08.jsonl.zst"
    records = (
        *tests.helpers.factories.peri_scribe.monitor.status.failed_run(
            run_id="archive",
        ),
        tests.helpers.factories.peri_scribe.monitor.status.record(
            "Unrelated",
            run_id="other",
        ),
    )
    with compression.zstd.open(path, "wt") as stream:
        for record in records:
            stream.write(json.dumps(record) + "\n")
    run = peri_scribe.monitor.history.load_run(tmp_path, "archive")
    assert [dict(event.fields) for event in run.events] == list(records[:-1])
    assert not peri_scribe.monitor.history.load_run(tmp_path, "missing").events


def test_reader_read_error_is_explicit(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tests.helpers.factories.peri_scribe.monitor.events.write_log(tmp_path)
    monkeypatch.setattr(
        peri_scribe.monitor.storage,
        "read_cursor",
        tests.helpers.doubles.errors.raising_stub(PermissionError("denied")),
    )
    with contextlib.closing(
        peri_scribe.monitor.history.Reader(tmp_path / "logs"),
    ) as reader:
        assert reader.poll(
            tests.helpers.factories.peri_scribe.monitor.status.NOW,
        ).errors == ("denied",)


def test_append_late_read_of_previous_month_cannot_replace_current_phase() -> None:
    now = tests.helpers.factories.peri_scribe.monitor.status.NOW
    history = tests.helpers.factories.peri_scribe.monitor.status.history(
        tests.helpers.factories.peri_scribe.monitor.status.record(
            "Starting phase",
            phase="kmz.build-kml",
        ),
    )
    history = peri_scribe.monitor.history.append(
        history,
        (
            tests.helpers.factories.peri_scribe.monitor.status.record(
                "Starting command",
                command="run",
                when=now - datetime.timedelta(hours=1),
            ),
        ),
        now,
    )
    assert history.state.runs[0].open_path[-1].phase == "build-kml"
    assert history.state.runs[0].events[-1].timestamp == now


def test_append_reuses_retention_until_the_first_run_expires(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = tests.helpers.factories.peri_scribe.monitor.status.NOW
    history = tests.helpers.factories.peri_scribe.monitor.status.history(
        tests.helpers.factories.peri_scribe.monitor.status.finished("kmz"),
    )
    retain = unittest.mock.Mock(wraps=peri_scribe.monitor.history.retain)
    monkeypatch.setattr(peri_scribe.monitor.history, "retain", retain)
    assert (
        peri_scribe.monitor.history.append(
            history,
            (),
            now + datetime.timedelta(hours=47),
        )
        is history
    )
    retain.assert_not_called()


def test_append_rechecks_retention_when_clock_moves_backward() -> None:
    now = tests.helpers.factories.peri_scribe.monitor.status.NOW
    history = tests.helpers.factories.peri_scribe.monitor.status.history(
        tests.helpers.factories.peri_scribe.monitor.status.finished("kmz"),
    )
    earlier = now - datetime.timedelta(minutes=1)
    updated = peri_scribe.monitor.history.append(history, (), earlier)
    assert updated.state is history.state
    assert updated.retained_at == earlier
