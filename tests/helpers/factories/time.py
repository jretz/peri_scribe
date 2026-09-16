"""Build inputs for time tests."""

from __future__ import annotations

import datetime


def utc(
    year: int,
    month: int,
    day: int,
    hour: int,
    minute: int = 0,
    *,
    second: int = 0,
) -> datetime.datetime:
    """Return an aware UTC datetime.

    Args:
        year: The year.
        month: The month.
        day: The day.
        hour: The hour.
        minute: The minute.
        second: The second.

    Returns:
        The datetime.
    """
    return datetime.datetime(
        year,
        month,
        day,
        hour,
        minute,
        second,
        tzinfo=datetime.UTC,
    )
