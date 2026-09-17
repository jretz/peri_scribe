"""Status history survives bounded UI retention, restarts, and monthly compression."""

import compression.zstd
import contextlib
import datetime
import json
import pathlib
from typing import TYPE_CHECKING

import peri_scribe.monitor.history
import peri_scribe.monitor.model
import peri_scribe.monitor.status
import peri_scribe.monitor.storage
import tests.helpers.doubles.errors
import tests.helpers.factories.peri_scribe.monitor.events
import tests.helpers.factories.peri_scribe.monitor.status


if TYPE_CHECKING:
    import pytest


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


def test_append_retains_old_failure_and_successful_stage_landmarks() -> None:
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
    identifiers = {run.identifier for run in history.state.runs}
    assert {"failed", "output"} <= identifiers
    assert "0" not in identifiers


def test_append_exposes_undated_records() -> None:
    history = tests.helpers.factories.peri_scribe.monitor.status.history({
        "event": "broken line",
    })
    assert history.undated == 1
    assert history.since is None
    assert (
        peri_scribe.monitor.history.last_time(history.state.runs[0]).year
        == datetime.MINYEAR
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


def test_reader_restarts_with_compressed_history_and_follows_new_errors(
    tmp_path: pathlib.Path,
) -> None:
    directory = tmp_path / "logs"
    directory.mkdir()
    path = directory / "2026-08.jsonl.zst"
    with compression.zstd.open(path, "wt") as stream:
        for record in tests.helpers.factories.peri_scribe.monitor.status.failed_run(
            run_id="archive",
        ):
            stream.write(json.dumps(record) + "\n")
    with contextlib.closing(peri_scribe.monitor.history.Reader(directory)) as reader:
        history = reader.poll(tests.helpers.factories.peri_scribe.monitor.status.NOW)
        assert history.state.runs[0].identifier == "archive"
        tests.helpers.factories.peri_scribe.monitor.events.write_log(
            tmp_path,
            *tests.helpers.factories.peri_scribe.monitor.status.failed_run(
                run_id="live",
            ),
        )
        history = reader.poll(tests.helpers.factories.peri_scribe.monitor.status.NOW)
        assert {run.identifier for run in history.state.runs} == {"archive", "live"}
        assert (
            reader.poll(tests.helpers.factories.peri_scribe.monitor.status.NOW).state
            == history.state
        )


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
    (tmp_path / "2026-08.jsonl.zst").write_bytes(b"invalid")
    with contextlib.closing(peri_scribe.monitor.history.Reader(tmp_path)) as reader:
        assert reader.poll(
            tests.helpers.factories.peri_scribe.monitor.status.NOW,
        ).errors


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
