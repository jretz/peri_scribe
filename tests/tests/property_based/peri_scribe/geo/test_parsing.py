"""Tests for peri_scribe.geo.package."""

from __future__ import annotations

import datetime

import hypothesis
import hypothesis.strategies

import peri_scribe.geo.parsing


@hypothesis.given(value=hypothesis.infer)
def test_normalize_identifier_ignores_surrounding_braces(value: str) -> None:
    assert peri_scribe.geo.parsing.normalize_identifier(
        "{" + value + "}",
    ) == peri_scribe.geo.parsing.normalize_identifier(value)


@hypothesis.given(value=hypothesis.infer)
def test_normalize_identifier_is_idempotent(value: str | None) -> None:
    normalized = peri_scribe.geo.parsing.normalize_identifier(value)
    assert peri_scribe.geo.parsing.normalize_identifier(normalized) == normalized


@hypothesis.given(value=hypothesis.strategies.floats(allow_nan=False))
def test_numeric_value_round_trips_numeric_text(value: float) -> None:
    assert peri_scribe.geo.parsing.numeric_value(str(value)) == value


@hypothesis.given(
    value=hypothesis.strategies.datetimes(
        min_value=datetime.datetime(2000, 1, 1),
        max_value=datetime.datetime(2100, 1, 1),
        timezones=hypothesis.strategies.timezones(),
    ),
)
def test_observation_time_from_preserves_instants_across_iso_round_trips(
    value: datetime.datetime,
) -> None:
    assert peri_scribe.geo.parsing.observation_time_from(
        value.isoformat(),
    ) == value.astimezone(datetime.UTC)
