"""Isolate plot data tests with explicit fixtures."""

from __future__ import annotations

import datetime

import pytest

import peri_scribe.kml.plot_data


@pytest.fixture
def intraday_series() -> tuple[peri_scribe.kml.plot_data.PlotSeries, ...]:
    """Expose date truncation through distinct, equally spaced readings within one day.

    Returns:
        One area series with morning, midday, and evening observations.
    """
    return (
        peri_scribe.kml.plot_data.PlotSeries(
            label="Area",
            points=tuple(
                peri_scribe.kml.plot_data.SeriesPoint(
                    observation_time=datetime.datetime(
                        2026,
                        9,
                        3,
                        hour,
                        tzinfo=datetime.UTC,
                    ),
                    value=value,
                )
                for hour, value in ((6, 100.0), (12, 500.0), (18, 200.0))
            ),
        ),
    )
