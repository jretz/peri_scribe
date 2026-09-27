"""Regression tests for unusable numeric and timestamp feed values."""

import datetime

import pytest

import peri_scribe.geo.parsing


@pytest.mark.parametrize(
    "value",
    ["NaN", "Infinity", "-Infinity", "1e9999", float("inf"), -(10**1000)],
    ids=[
        "nan-text",
        "infinity-text",
        "negative-infinity",
        "overflow-text",
        "infinity-float",
        "oversized-integer",
    ],
)
def test_numeric_value_rejects_nonfinite_and_overflowing_numbers(value: object) -> None:
    assert peri_scribe.geo.parsing.numeric_value(value) is None


@pytest.mark.parametrize(
    "value",
    [
        "0001-01-01T00:00:00+01:00",
        "9999-12-31T23:59:59-01:00",
        datetime.datetime.min.replace(
            tzinfo=datetime.timezone(datetime.timedelta(hours=1)),
        ),
        datetime.datetime.max.replace(
            tzinfo=datetime.timezone(datetime.timedelta(hours=-1)),
        ),
    ],
)
def test_observation_time_from_rejects_unrepresentable_utc_instants(
    value: object,
) -> None:
    assert peri_scribe.geo.parsing.observation_time_from(value) is None
