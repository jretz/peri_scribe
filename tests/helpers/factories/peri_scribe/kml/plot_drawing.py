"""Build inputs for plot drawing tests."""

from __future__ import annotations

import peri_scribe.kml.plot_data
import tests.helpers.factories.peri_scribe.kml.plot_histories


def one_series_plot() -> tuple[peri_scribe.kml.plot_data.PlotSeries, ...]:
    """Provide one growing area series for plot layout assertions.

    Returns:
        A single area series with two dated measurements.
    """
    return (
        peri_scribe.kml.plot_data.PlotSeries(
            label="Area",
            points=(
                tests.helpers.factories.peri_scribe.kml.plot_histories.series_point(
                    1,
                    10.0,
                ),
                tests.helpers.factories.peri_scribe.kml.plot_histories.series_point(
                    2,
                    20.0,
                ),
            ),
        ),
    )
