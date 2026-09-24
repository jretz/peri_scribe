"""Build inputs for plot rendering tests."""

from __future__ import annotations

import datetime

import peri_scribe.kml.plot_rendering
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


def plot_request() -> peri_scribe.kml.plot_rendering.PlotRequest:
    """Supply a complete renderable request with a stable current filename.

    Returns:
        A two-observation area chart request.
    """
    return peri_scribe.kml.plot_rendering.PlotRequest(
        fire_index=0,
        filename_prefix="id-bug",
        filename_suffix="area",
        y_axis_label="Acres",
        series=(two_point_series(),),
    )
