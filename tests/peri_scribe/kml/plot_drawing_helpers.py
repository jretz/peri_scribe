"""Provide data builders and stand-ins for plot drawing tests."""

from __future__ import annotations

import datetime

import defusedxml.minidom
import hypothesis.strategies

import peri_scribe.kml.plot_data
import tests.peri_scribe.kml.kml_plot_helpers
import tests.peri_scribe.kml.plot_data_helpers


@hypothesis.strategies.composite
def plot_series(
    draw: hypothesis.strategies.DrawFn,
) -> tuple[peri_scribe.kml.plot_data.PlotSeries, ...]:
    """Exercise chart bounds across a season, time zones, and measurement scales.

    Args:
        draw: The current example's strategy sampler.

    Returns:
        Nonempty series ranging from fractional plotted units to large measurements.
    """
    value = hypothesis.strategies.one_of(
        hypothesis.strategies.just(0.0),
        hypothesis.strategies.floats(1e-6, 1e9, allow_nan=False, allow_infinity=False),
    )
    histories = draw(
        hypothesis.strategies.lists(
            hypothesis.strategies.lists(
                hypothesis.strategies.tuples(
                    hypothesis.strategies.integers(0, 365 * 24 * 60),
                    value,
                ),
                min_size=1,
                max_size=10,
            ),
            min_size=1,
            max_size=3,
        ),
    )
    zone = draw(hypothesis.strategies.timezones())
    base = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    return tuple(
        peri_scribe.kml.plot_data.PlotSeries(
            label=f"Series {index}",
            points=tuple(
                peri_scribe.kml.plot_data.SeriesPoint(
                    observation_time=(
                        base + datetime.timedelta(minutes=minute)
                    ).astimezone(zone),
                    value=measurement,
                )
                for minute, measurement in history
            ),
        )
        for index, history in enumerate(histories)
    )


def chronological_points() -> hypothesis.strategies.SearchStrategy[
    tuple[peri_scribe.kml.plot_data.SeriesPoint, ...]
]:
    """Exercise source-style runs of arbitrary length across chronological measurements.

    Returns:
        A time-ordered series with mapped and reported provenance on its points.
    """
    return tests.peri_scribe.kml.plot_data_helpers.series_points().map(
        lambda points: tuple(sorted(points, key=lambda point: point.observation_time)),
    )


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
