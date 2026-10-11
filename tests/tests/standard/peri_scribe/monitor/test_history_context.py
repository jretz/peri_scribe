"""Backward context search preserves nearby command evidence and streaming fallbacks."""

import compression.zstd
import datetime
import io
import json
import pathlib
import threading
import unittest.mock

import pytest

import peri_scribe.monitor.events
import peri_scribe.monitor.history
import tests.helpers.factories.peri_scribe.monitor.events
import tests.helpers.factories.peri_scribe.monitor.status


@pytest.mark.parametrize("block_size", [1, 2, 7, 64, 1024])
@pytest.mark.parametrize(
    "contents",
    [b"", b"\n", b"first\nlast\n", "first\n\n森林é\n".encode(), b"x" * 4096 + b"\ny\n"],
)
def test_reverse_lines_preserves_complete_records_across_blocks(
    contents: bytes,
    block_size: int,
) -> None:
    with io.BytesIO(contents + b"unfinished") as stream:
        assert list(
            peri_scribe.monitor.history.reverse_lines(
                stream,
                len(contents),
                threading.Event(),
                block_size=block_size,
            ),
        ) == [line for line in reversed(contents.split(b"\n")) if line.strip()]


def test_reverse_lines_stops_between_records() -> None:
    stopped = threading.Event()
    contents = b"first\nmiddle\nlast\n"
    with io.BytesIO(contents) as stream:
        records = peri_scribe.monitor.history.reverse_lines(
            stream,
            len(contents),
            stopped,
        )
        assert next(records) == b"last"
        stopped.set()
        assert tuple(records) == ()


def test_backward_context_stops_before_parsing_a_retrieved_record(
    tmp_path: pathlib.Path,
) -> None:
    now = tests.helpers.factories.peri_scribe.monitor.status.NOW
    path = tests.helpers.factories.peri_scribe.monitor.events.write_log(
        tmp_path,
        tests.helpers.factories.peri_scribe.monitor.status.record(
            "Starting command",
            when=now - datetime.timedelta(minutes=1),
        ),
        tests.helpers.factories.peri_scribe.monitor.status.record(
            "Starting phase",
            when=now - datetime.timedelta(seconds=30),
        ),
    )
    stopped = unittest.mock.Mock(spec=threading.Event)
    stopped.is_set.side_effect = (False, False, False, True)
    assert (
        peri_scribe.monitor.history.backward_context(
            path,
            {"run-1": now},
            stopped,
        )
        == ()
    )


def test_backward_context_stops_before_the_first_reverse_block(
    tmp_path: pathlib.Path,
) -> None:
    path = tmp_path / "2026-09.jsonl"
    path.write_bytes(b'{"timestamp":"2026-09-01"}\n')
    stopped = unittest.mock.Mock(spec=threading.Event)
    stopped.is_set.side_effect = (False, True, True, True)
    assert (
        peri_scribe.monitor.history.backward_context(
            path,
            {"run-1": tests.helpers.factories.peri_scribe.monitor.status.NOW},
            stopped,
        )
        == ()
    )


def test_backward_context_preserves_each_run_cutoff_and_file_order(
    tmp_path: pathlib.Path,
) -> None:
    now = tests.helpers.factories.peri_scribe.monitor.status.NOW
    descriptions = (
        ("Starting command", "first", 10),
        ("Starting command", "second", 9),
        ("Starting phase", "second", 7),
        ("Starting phase", "first", 6),
        ("Finished phase", "second", 5),
        ("Starting phase", "first", 4),
        ("Progress", "first", 3),
        ("Starting phase", "unselected", 2),
        ("Starting phase", "first", 0),
    )
    records = tuple(
        tests.helpers.factories.peri_scribe.monitor.status.record(
            event,
            run_id=identifier,
            when=now - datetime.timedelta(minutes=minutes),
        )
        for event, identifier, minutes in descriptions
    )
    path = tests.helpers.factories.peri_scribe.monitor.events.write_log(
        tmp_path,
        *records,
    )
    assert peri_scribe.monitor.history.backward_context(
        path,
        {"first": now, "second": now - datetime.timedelta(minutes=5)},
        threading.Event(),
    ) == tuple(records[index] for index in (0, 1, 2, 3, 5))


def test_backward_context_ignores_undated_context(tmp_path: pathlib.Path) -> None:
    now = tests.helpers.factories.peri_scribe.monitor.status.NOW
    start = tests.helpers.factories.peri_scribe.monitor.status.record(
        "Starting command",
        when=now - datetime.timedelta(minutes=1),
    )
    undated: dict[str, object] = {"run_id": "run-1", "event": "Starting phase"}
    phase = tests.helpers.factories.peri_scribe.monitor.status.record(
        "Starting phase",
        when=now - datetime.timedelta(seconds=30),
    )
    path = tests.helpers.factories.peri_scribe.monitor.events.write_log(
        tmp_path,
        start,
        undated,
        phase,
    )
    assert peri_scribe.monitor.history.backward_context(
        path,
        {"run-1": now},
        threading.Event(),
    ) == (start, phase)


def test_backward_context_preserves_repeated_exception_occurrences(
    tmp_path: pathlib.Path,
) -> None:
    now = tests.helpers.factories.peri_scribe.monitor.status.NOW
    start = tests.helpers.factories.peri_scribe.monitor.status.record(
        "Starting command",
        when=now - datetime.timedelta(minutes=2),
    )
    failure = tests.helpers.factories.peri_scribe.monitor.status.record(
        "Request failed",
        when=now - datetime.timedelta(minutes=1),
        exception="problem",
    )
    path = tests.helpers.factories.peri_scribe.monitor.events.write_log(
        tmp_path,
        start,
        failure,
        failure,
    )
    assert peri_scribe.monitor.history.backward_context(
        path,
        {"run-1": now},
        threading.Event(),
    ) == (start, failure, failure)


def test_backward_context_requests_streaming_when_a_start_is_missing(
    tmp_path: pathlib.Path,
) -> None:
    now = tests.helpers.factories.peri_scribe.monitor.status.NOW
    path = tests.helpers.factories.peri_scribe.monitor.events.write_log(
        tmp_path,
        tests.helpers.factories.peri_scribe.monitor.status.record(
            "Starting phase",
            when=now - datetime.timedelta(minutes=1),
        ),
    )
    assert (
        peri_scribe.monitor.history.backward_context(
            path,
            {"run-1": now},
            threading.Event(),
        )
        is None
    )


@pytest.mark.parametrize("mixed", [False, True])
def test_backward_context_requests_streaming_for_archived_components(
    tmp_path: pathlib.Path,
    *,
    mixed: bool,
) -> None:
    path = tmp_path / "2026-09.jsonl"
    archive = path.with_suffix(".jsonl.zst")
    archive.write_bytes(compression.zstd.compress(b"\n"))
    if mixed:
        path.write_bytes(b"\n")
    assert (
        peri_scribe.monitor.history.backward_context(
            path if mixed else archive,
            {"run-1": tests.helpers.factories.peri_scribe.monitor.status.NOW},
            threading.Event(),
        )
        is None
    )


@pytest.mark.parametrize("empty", [False, True])
def test_backward_context_does_not_open_files_without_pending_work(
    tmp_path: pathlib.Path,
    *,
    empty: bool,
) -> None:
    stopped = threading.Event()
    if not empty:
        stopped.set()
    assert (
        peri_scribe.monitor.history.backward_context(
            tmp_path / "absent.jsonl",
            {}
            if empty
            else {"run-1": tests.helpers.factories.peri_scribe.monitor.status.NOW},
            stopped,
        )
        == ()
    )


def test_backward_context_does_not_decode_the_unrelated_old_prefix(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = tests.helpers.factories.peri_scribe.monitor.status.NOW
    prefix = b'{"timestamp":"2026-09-01","event":"Old"}\n' * 10000
    start = tests.helpers.factories.peri_scribe.monitor.status.record(
        "Starting command",
        when=now - datetime.timedelta(minutes=1),
    )
    path = tmp_path / "2026-09.jsonl"
    path.write_bytes(prefix + json.dumps(start).encode() + b"\n")
    parser = unittest.mock.Mock(wraps=peri_scribe.monitor.events.parse_record)
    monkeypatch.setattr(peri_scribe.monitor.events, "parse_record", parser)
    assert peri_scribe.monitor.history.backward_context(
        path,
        {"run-1": now},
        threading.Event(),
    ) == (start,)
    assert parser.call_count == 1
