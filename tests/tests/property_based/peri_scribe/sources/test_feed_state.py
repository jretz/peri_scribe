"""Tests for peri_scribe.sources.feed_state."""

from __future__ import annotations

import contextlib
import sqlite3

import hypothesis
import shapely

import peri_scribe.sources.feed_state
import tests.helpers.factories.peri_scribe.sources.feed_state
import tests.helpers.strategies.peri_scribe.sources.feed_state


@hypothesis.given(
    value=tests.helpers.strategies.peri_scribe.sources.feed_state.sql_values(),
)
def test_sql_literal_round_trips_through_a_sql_parser(
    *,
    value: str | float | bool,
) -> None:
    literal = peri_scribe.sources.feed_state.sql_literal(value)
    with contextlib.closing(sqlite3.connect(":memory:")) as database:
        assert database.execute("SELECT " + literal).fetchone() == (value,)


@hypothesis.given(
    batches=tests.helpers.strategies.peri_scribe.sources.feed_state.feature_batches(),
)
def test_latest_features_by_object_id_matches_last_observation_model(
    batches: list[list[tuple[int, str]]],
) -> None:
    frames = tests.helpers.factories.peri_scribe.sources.feed_state.feature_frames(
        batches,
    )
    expected = dict(entry for batch in batches for entry in batch)
    actual = peri_scribe.sources.feed_state.latest_features_by_object_id(frames)
    assert actual is not None
    assert len(actual) == len(expected)
    assert dict(zip(actual.OBJECTID, actual.value, strict=True)) == expected
    for identifier, geometry in zip(actual.OBJECTID, actual.geometry, strict=True):
        assert geometry == shapely.Point(identifier, len(expected[identifier]))
