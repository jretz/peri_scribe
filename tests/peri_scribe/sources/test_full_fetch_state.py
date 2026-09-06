"""Tests for peri_scribe.sources.full_fetch_state."""

from __future__ import annotations

import datetime
import json
import pathlib
import typing

import pytest

import peri_scribe.sources.full_fetch_state


if typing.TYPE_CHECKING:
    import structlog.testing


SAMPLE_TIMESTAMP = datetime.datetime(2026, 9, 6, 18, 42, tzinfo=datetime.UTC)


def test_full_fetch_is_due_with_zero_interval() -> None:
    assert peri_scribe.sources.full_fetch_state.full_fetch_is_due(
        interval=datetime.timedelta(0),
        current_time=SAMPLE_TIMESTAMP,
        last_full_fetch=SAMPLE_TIMESTAMP,
    )


def test_full_fetch_is_due_without_a_recorded_full_fetch() -> None:
    assert peri_scribe.sources.full_fetch_state.full_fetch_is_due(
        interval=datetime.timedelta(hours=12),
        current_time=SAMPLE_TIMESTAMP,
        last_full_fetch=None,
    )


def test_full_fetch_is_due_when_interval_elapsed() -> None:
    assert peri_scribe.sources.full_fetch_state.full_fetch_is_due(
        interval=datetime.timedelta(hours=12),
        current_time=SAMPLE_TIMESTAMP,
        last_full_fetch=SAMPLE_TIMESTAMP - datetime.timedelta(hours=12),
    )


def test_full_fetch_is_not_due_when_interval_not_elapsed() -> None:
    assert not peri_scribe.sources.full_fetch_state.full_fetch_is_due(
        interval=datetime.timedelta(hours=12),
        current_time=SAMPLE_TIMESTAMP,
        last_full_fetch=SAMPLE_TIMESTAMP - datetime.timedelta(hours=11),
    )


def test_read_state_returns_none_when_missing(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "fetch_state.json"
    assert peri_scribe.sources.full_fetch_state.read_state(path) is None


def test_write_state_round_trip(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "fetch_state.json"
    peri_scribe.sources.full_fetch_state.write_state(
        path,
        last_full_fetch=SAMPLE_TIMESTAMP,
    )
    assert peri_scribe.sources.full_fetch_state.read_state(
        path,
    ) == peri_scribe.sources.full_fetch_state.FullFetchState(
        last_full_fetch=SAMPLE_TIMESTAMP,
    )


def test_write_state_stores_version_and_utc_timestamp(
    tmp_path: pathlib.Path,
) -> None:
    path = tmp_path / "sources" / "fetch_state.json"
    peri_scribe.sources.full_fetch_state.write_state(
        path,
        last_full_fetch=SAMPLE_TIMESTAMP,
    )
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "version": "2026-09-06",
        "last_full_fetch": "2026-09-06T18:42:00Z",
    }


def test_write_state_converts_other_timezones_to_utc(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "fetch_state.json"
    peri_scribe.sources.full_fetch_state.write_state(
        path,
        last_full_fetch=datetime.datetime(
            2026,
            9,
            6,
            20,
            42,
            tzinfo=datetime.timezone(datetime.timedelta(hours=2)),
        ),
    )
    content = json.loads(path.read_text(encoding="utf-8"))
    assert content["last_full_fetch"] == "2026-09-06T18:42:00Z"


def test_write_state_rejects_naive_timestamp(tmp_path: pathlib.Path) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        peri_scribe.sources.full_fetch_state.write_state(
            tmp_path / "fetch_state.json",
            last_full_fetch=datetime.datetime(2026, 9, 6, 18, 42),
        )


def test_read_state_rejects_malformed_json(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "fetch_state.json"
    path.write_text("not json", encoding="utf-8")
    with pytest.raises(ValueError, match="Malformed fetch state"):
        peri_scribe.sources.full_fetch_state.read_state(path)


def test_read_state_rejects_non_object_state(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "fetch_state.json"
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="Malformed fetch state"):
        peri_scribe.sources.full_fetch_state.read_state(path)


def test_read_state_rejects_unknown_version(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "fetch_state.json"
    path.write_text(
        json.dumps(
            {
                "version": "other",
                "last_full_fetch": "2026-09-06T18:42:00Z",
            },
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Malformed fetch state"):
        peri_scribe.sources.full_fetch_state.read_state(path)


def test_read_state_rejects_non_string_timestamp(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "fetch_state.json"
    path.write_text(
        json.dumps({"version": "2026-09-06", "last_full_fetch": 123}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Malformed fetch state"):
        peri_scribe.sources.full_fetch_state.read_state(path)


def test_read_state_rejects_unparseable_timestamp(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "fetch_state.json"
    path.write_text(
        json.dumps({"version": "2026-09-06", "last_full_fetch": "yesterday"}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Malformed fetch state"):
        peri_scribe.sources.full_fetch_state.read_state(path)


def test_read_state_rejects_naive_timestamp(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "fetch_state.json"
    path.write_text(
        json.dumps(
            {"version": "2026-09-06", "last_full_fetch": "2026-09-06T18:42:00"},
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Malformed fetch state"):
        peri_scribe.sources.full_fetch_state.read_state(path)


def test_read_state_rejects_unreadable_state(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "fetch_state.json"
    path.mkdir()
    with pytest.raises(ValueError, match="Malformed fetch state"):
        peri_scribe.sources.full_fetch_state.read_state(path)


def test_read_state_logs_malformed_state_error(
    tmp_path: pathlib.Path,
    log_output: structlog.testing.LogCapture,
) -> None:
    path = tmp_path / "fetch_state.json"
    path.write_text("not json", encoding="utf-8")
    with pytest.raises(ValueError, match="Malformed fetch state"):
        peri_scribe.sources.full_fetch_state.read_state(path)
    assert len(log_output.entries) == 1
    entry = log_output.entries[0]
    assert entry["event"] == "Malformed fetch state"
    assert entry["path"] == path
    assert "Expecting value" in entry["error"]
