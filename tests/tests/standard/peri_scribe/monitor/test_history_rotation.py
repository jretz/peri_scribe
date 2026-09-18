"""Concurrent monthly rotation preserves context omitted by the recent-window seek."""

import contextlib
import datetime
import functools
import json
import pathlib

import pytest

import peri_scribe.monitor.history
import tests.helpers.doubles.peri_scribe.monitor.history_rotation
import tests.helpers.factories.peri_scribe.monitor.history


def test_reader_restores_context_rotated_after_discovery(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.datetime(2026, 10, 1, tzinfo=datetime.UTC)
    records = tests.helpers.factories.peri_scribe.monitor.history.active_run_records(
        now - datetime.timedelta(hours=49),
        now - datetime.timedelta(minutes=1),
    )
    path = tmp_path / "2026-09.jsonl"
    path.write_text("".join(json.dumps(record) + "\n" for record in records))
    monkeypatch.setattr(
        peri_scribe.monitor.history,
        "records_from",
        functools.partial(
            tests.helpers.doubles.peri_scribe.monitor.history_rotation.rotate_before_read,
            read_records=peri_scribe.monitor.history.records_from,
        ),
    )
    with contextlib.closing(peri_scribe.monitor.history.Reader(tmp_path)) as reader:
        history = reader.catch_up(now)
        assert not history.errors
        assert [dict(event.fields) for event in history.state.runs[0].events] == list(
            records,
        )
        assert reader.catch_up(now) == history


@pytest.mark.parametrize("filename", ["2026-09.jsonl", "2026-09.jsonl.zst"])
def test_records_from_reports_missing_monthly_logs(
    tmp_path: pathlib.Path,
    filename: str,
) -> None:
    with pytest.raises(FileNotFoundError):
        list(peri_scribe.monitor.history.records_from(tmp_path / filename))
