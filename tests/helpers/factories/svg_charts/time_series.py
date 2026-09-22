"""Build inputs for plot drawing tests."""

from __future__ import annotations

import svg_charts.models
import tests.helpers.factories.svg_charts.models


def one_series_plot() -> tuple[svg_charts.models.PlotSeries, ...]:
    """Provide one growing area series for plot layout assertions.

    Returns:
        A single area series with two dated measurements.
    """
    return (
        svg_charts.models.PlotSeries(
            label="Area",
            points=(
                tests.helpers.factories.svg_charts.models.series_point(
                    1,
                    10.0,
                ),
                tests.helpers.factories.svg_charts.models.series_point(
                    2,
                    20.0,
                ),
            ),
        ),
    )
