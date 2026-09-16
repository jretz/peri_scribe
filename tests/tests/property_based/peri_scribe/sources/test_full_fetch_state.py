"""Tests for peri_scribe.sources.full_fetch_state."""

from __future__ import annotations

import datetime
import pathlib
import tempfile

import hypothesis
import hypothesis.strategies

import peri_scribe.sources.full_fetch_state
import tests.helpers.strategies.peri_scribe.models


@hypothesis.given(
    instants=tests.helpers.strategies.peri_scribe.models.clock_change_instants(),
    interval_hours=hypothesis.strategies.integers(0, 4),
)
def test_full_fetch_is_due_uses_elapsed_time_across_clock_changes(
    instants: tuple[datetime.datetime, datetime.datetime],
    interval_hours: int,
) -> None:
    previous, current = instants
    interval = datetime.timedelta(hours=interval_hours)
    elapsed_seconds = current.timestamp() - previous.timestamp()
    assert peri_scribe.sources.full_fetch_state.full_fetch_is_due(
        interval=interval,
        current_time=current,
        last_full_fetch=previous,
    ) == (elapsed_seconds >= interval.total_seconds())


@hypothesis.given(
    timestamps=hypothesis.strategies.lists(
        hypothesis.strategies.datetimes(
            min_value=datetime.datetime(2000, 1, 1),
            max_value=datetime.datetime(2100, 1, 1),
            timezones=hypothesis.strategies.timezones(),
        ),
        min_size=1,
        max_size=4,
    ),
)
def test_write_state_round_trips_timestamps_across_repeated_writes(
    timestamps: list[datetime.datetime],
) -> None:
    with tempfile.TemporaryDirectory() as temporary_directory:
        path = pathlib.Path(temporary_directory) / "sources" / "fetch_state.json"
        for timestamp in timestamps:
            peri_scribe.sources.full_fetch_state.write_state(
                path,
                last_full_fetch=timestamp,
            )
            assert peri_scribe.sources.full_fetch_state.read_state(path) == (
                peri_scribe.sources.full_fetch_state.FullFetchState(
                    last_full_fetch=timestamp.astimezone(datetime.UTC),
                )
            )
