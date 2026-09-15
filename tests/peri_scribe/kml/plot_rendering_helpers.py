"""Provide data builders and stand-ins for plot rendering tests."""

from __future__ import annotations

import datetime
import typing

import peri_scribe.kml.plot_data


def two_point_series() -> peri_scribe.kml.plot_data.PlotSeries:
    """Provide two dated area measurements for rendering tests.

    Returns:
        An area series with readings two days apart.
    """
    return peri_scribe.kml.plot_data.PlotSeries(
        label="Area",
        points=(
            peri_scribe.kml.plot_data.SeriesPoint(
                observation_time=datetime.datetime(2026, 7, 8, tzinfo=datetime.UTC),
                value=1.0,
            ),
            peri_scribe.kml.plot_data.SeriesPoint(
                observation_time=datetime.datetime(2026, 7, 10, tzinfo=datetime.UTC),
                value=2.0,
            ),
        ),
    )


def make_pre_render_recorder(*, calls: list[str]) -> typing.Callable[..., None]:
    """Create a callback to record when the pre-render callback runs.

    Args:
        calls: Shared list recording dependency calls for assertions.

    Returns:
        The callback bound to the supplied dependencies.
    """

    def record() -> None:
        """Record when the pre-render callback runs."""
        calls.append("before")

    return record
