"""Tests for peri_scribe.sources.full_fetch_state."""

from __future__ import annotations

import datetime
import json
import pathlib
import typing
import zoneinfo

import pytest

import peri_scribe.sources.full_fetch_state
import tests.helpers.factories.peri_scribe.sources.full_fetch_state


if typing.TYPE_CHECKING:
    import structlog.testing


@pytest.mark.parametrize(
    ("previous", "current", "interval_hours", "due"),
    [
        (
            datetime.datetime(
                2026,
                3,
                8,
                1,
                tzinfo=zoneinfo.ZoneInfo("America/Los_Angeles"),
            ),
            datetime.datetime(
                2026,
                3,
                8,
                3,
                tzinfo=zoneinfo.ZoneInfo("America/Los_Angeles"),
            ),
            2,
            False,
        ),
        (
            datetime.datetime(
                2026,
                11,
                1,
                1,
                tzinfo=zoneinfo.ZoneInfo("America/Los_Angeles"),
            ),
            datetime.datetime(
                2026,
                11,
                1,
                1,
                fold=1,
                tzinfo=zoneinfo.ZoneInfo("America/Los_Angeles"),
            ),
            1,
            True,
        ),
    ],
)
def test_full_fetch_is_due_accounts_for_skipped_and_repeated_hours(
    previous: datetime.datetime,
    current: datetime.datetime,
    interval_hours: int,
    *,
    due: bool,
) -> None:
    assert (
        peri_scribe.sources.full_fetch_state.full_fetch_is_due(
            interval=datetime.timedelta(hours=interval_hours),
            current_time=current,
            last_full_fetch=previous,
        )
        is due
    )


def test_full_fetch_is_due_compares_naive_timestamps_without_a_local_timezone() -> None:
    assert peri_scribe.sources.full_fetch_state.full_fetch_is_due(
        interval=datetime.timedelta(hours=2),
        current_time=datetime.datetime(2026, 3, 8, 3),
        last_full_fetch=datetime.datetime(2026, 3, 8, 1),
    )


@pytest.mark.parametrize("current_is_aware", [True, False])
def test_full_fetch_is_due_rejects_mixed_naive_and_aware_timestamps(
    *,
    current_is_aware: bool,
) -> None:
    naive = datetime.datetime(2026, 3, 8, 1)
    aware = naive.replace(tzinfo=datetime.UTC)
    with pytest.raises(TypeError, match="offset-naive and offset-aware"):
        peri_scribe.sources.full_fetch_state.full_fetch_is_due(
            interval=datetime.timedelta(hours=1),
            current_time=aware if current_is_aware else naive,
            last_full_fetch=naive if current_is_aware else aware,
        )


def test_full_fetch_is_due_with_zero_interval() -> None:
    assert peri_scribe.sources.full_fetch_state.full_fetch_is_due(
        interval=datetime.timedelta(0),
        current_time=tests.helpers.factories.peri_scribe.sources.full_fetch_state.SAMPLE_TIMESTAMP,
        last_full_fetch=tests.helpers.factories.peri_scribe.sources.full_fetch_state.SAMPLE_TIMESTAMP,
    )


def test_full_fetch_is_due_without_a_recorded_full_fetch() -> None:
    assert peri_scribe.sources.full_fetch_state.full_fetch_is_due(
        interval=datetime.timedelta(hours=12),
        current_time=tests.helpers.factories.peri_scribe.sources.full_fetch_state.SAMPLE_TIMESTAMP,
        last_full_fetch=None,
    )


def test_full_fetch_is_due_when_interval_elapsed() -> None:
    assert peri_scribe.sources.full_fetch_state.full_fetch_is_due(
        interval=datetime.timedelta(hours=12),
        current_time=tests.helpers.factories.peri_scribe.sources.full_fetch_state.SAMPLE_TIMESTAMP,
        last_full_fetch=tests.helpers.factories.peri_scribe.sources.full_fetch_state.SAMPLE_TIMESTAMP
        - datetime.timedelta(hours=12),
    )


def test_full_fetch_is_not_due_when_interval_not_elapsed() -> None:
    assert not peri_scribe.sources.full_fetch_state.full_fetch_is_due(
        interval=datetime.timedelta(hours=12),
        current_time=tests.helpers.factories.peri_scribe.sources.full_fetch_state.SAMPLE_TIMESTAMP,
        last_full_fetch=tests.helpers.factories.peri_scribe.sources.full_fetch_state.SAMPLE_TIMESTAMP
        - datetime.timedelta(hours=11),
    )


def test_read_state_returns_none_when_missing(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "fetch_state.json"
    assert peri_scribe.sources.full_fetch_state.read_state(path) is None


def test_write_state_round_trip(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "fetch_state.json"
    peri_scribe.sources.full_fetch_state.write_state(
        path,
        last_full_fetch=tests.helpers.factories.peri_scribe.sources.full_fetch_state.SAMPLE_TIMESTAMP,
    )
    assert peri_scribe.sources.full_fetch_state.read_state(
        path,
    ) == peri_scribe.sources.full_fetch_state.FullFetchState(
        last_full_fetch=tests.helpers.factories.peri_scribe.sources.full_fetch_state.SAMPLE_TIMESTAMP,
    )


def test_write_state_stores_version_and_utc_timestamp(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "sources" / "fetch_state.json"
    peri_scribe.sources.full_fetch_state.write_state(
        path,
        last_full_fetch=tests.helpers.factories.peri_scribe.sources.full_fetch_state.SAMPLE_TIMESTAMP,
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
        json.dumps({"version": "other", "last_full_fetch": "2026-09-06T18:42:00Z"}),
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
        json.dumps({"version": "2026-09-06", "last_full_fetch": "2026-09-06T18:42:00"}),
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
    assert entry["path"] == str(path)
    assert "Expecting value" in entry["error"]
