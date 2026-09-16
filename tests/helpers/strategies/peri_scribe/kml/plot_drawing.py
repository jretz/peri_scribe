"""Generate plot drawing examples with constrained domains."""

from __future__ import annotations

import datetime

import hypothesis.strategies

import peri_scribe.kml.plot_data
import tests.helpers.strategies.peri_scribe.kml.plot_data


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
    return tests.helpers.strategies.peri_scribe.kml.plot_data.series_points().map(
        lambda points: tuple(sorted(points, key=lambda point: point.observation_time)),
    )
