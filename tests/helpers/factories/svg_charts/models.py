"""Simple dates and observations for chart examples."""

from __future__ import annotations

import datetime

import svg_charts.models


def observation_time(day: int, hour: int = 0) -> datetime.datetime:
    """Return an aware UTC observation time on August *day*.

    Args:
        day: The day of the month.
        hour: The hour of the day.

    Returns:
        The observation time.
    """
    return datetime.datetime(2026, 8, day, hour, tzinfo=datetime.UTC)


def series_point(
    day: int,
    value: float,
    hour: int = 0,
) -> svg_charts.models.SeriesPoint:
    """Return a series point at *day* with *value*.

    Args:
        day: The day of the observation.
        value: The measurement.
        hour: The hour of the observation.

    Returns:
        The point.
    """
    return svg_charts.models.SeriesPoint(
        observation_time=observation_time(day, hour),
        value=value,
    )
