"""Provide data builders and stand-ins for plot drawing tests."""

from __future__ import annotations

import defusedxml.minidom

import peri_scribe.kml.plot_data
import tests.peri_scribe.kml.kml_plot_helpers


def one_series_plot() -> tuple[peri_scribe.kml.plot_data.PlotSeries, ...]:
    """Provide one growing area series for plot layout assertions.

    Returns:
        A single area series with two dated measurements.
    """
    return (
        peri_scribe.kml.plot_data.PlotSeries(
            label="Area",
            points=(
                tests.peri_scribe.kml.kml_plot_helpers.series_point(1, 10.0),
                tests.peri_scribe.kml.kml_plot_helpers.series_point(2, 20.0),
            ),
        ),
    )


def plot_legend(content: bytes) -> tuple[tuple[str, str, str], ...]:
    """Check legend meaning and styling through the rendered SVG contract.

    Args:
        content: A rendered chart containing a legend.

    Returns:
        Legend labels, stroke colors, and dash patterns in display order.
    """
    drawing = defusedxml.minidom.parseString(content)
    legend = next(
        group
        for group in drawing.getElementsByTagName("g")
        if group.getElementsByTagName("line") and group.getElementsByTagName("text")
    )
    return tuple(
        (
            label.firstChild.data,
            swatch.getAttribute("stroke"),
            swatch.getAttribute("stroke-dasharray"),
        )
        for label, swatch in zip(
            legend.getElementsByTagName("text"),
            legend.getElementsByTagName("line"),
            strict=True,
        )
    )
