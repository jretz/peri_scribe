"""Build inputs for plot rendering tests."""

from __future__ import annotations

import datetime

import svg_charts.models


def two_point_series() -> svg_charts.models.PlotSeries:
    """Provide two dated area measurements for rendering tests.

    Returns:
        An area series with readings two days apart.
    """
    return svg_charts.models.PlotSeries(
        label="Area",
        points=(
            svg_charts.models.SeriesPoint(
                observation_time=datetime.datetime(2026, 7, 8, tzinfo=datetime.UTC),
                value=1.0,
            ),
            svg_charts.models.SeriesPoint(
                observation_time=datetime.datetime(2026, 7, 10, tzinfo=datetime.UTC),
                value=2.0,
            ),
        ),
    )
