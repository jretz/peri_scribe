"""Regression tests for invalid timestamps in source feeds."""

import pytest

import peri_scribe.sources.changes


@pytest.mark.parametrize(
    "value",
    [
        float("inf"),
        float("-inf"),
        10**1000,
        10**20,
        "0001-01-01T00:00:00+01:00",
        "9999-12-31T23:59:59-01:00",
    ],
    ids=[
        "infinity",
        "negative-infinity",
        "oversized-integer",
        "out-of-calendar",
        "utc-before-calendar",
        "utc-after-calendar",
    ],
)
def test_modified_datetime_from_rejects_unrepresentable_timestamps(
    value: object,
) -> None:
    assert peri_scribe.sources.changes.modified_datetime_from(value) is None
