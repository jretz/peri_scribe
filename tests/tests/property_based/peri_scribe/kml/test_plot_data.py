"""Tests for peri_scribe.kml.plot_data."""

from __future__ import annotations

import dataclasses
import typing

import hypothesis
import hypothesis.strategies
import pytest

import peri_scribe.kml.plot_data
import tests.helpers.factories.geography
import tests.helpers.strategies.peri_scribe.kml.plot_data
import tests.helpers.strategies.svg_charts.models


if typing.TYPE_CHECKING:
    import svg_charts.models


@hypothesis.given(
    history=tests.helpers.strategies.peri_scribe.kml.plot_data.containment_histories(),
)
def test_contained_perimeter_points_matches_latest_available_evidence(
    history: tests.helpers.strategies.peri_scribe.kml.plot_data.ContainmentHistory,
) -> None:
    expected_times = []
    expected_values = []
    for time in sorted(history.miles_by_time.keys() | history.percent_by_time.keys()):
        lengths = [when for when in history.miles_by_time if when <= time]
        percentages = [when for when in history.percent_by_time if when <= time]
        if lengths and percentages:
            expected_times.append(time)
            expected_values.append(
                history.miles_by_time[max(lengths)]
                * history.percent_by_time[max(percentages)]
                / 100,
            )
    actual = peri_scribe.kml.plot_data.contained_perimeter_points(
        tests.helpers.factories.geography.geo_frame({}, []),
        history.measurements,
        updates=history.updates,
    )
    assert [point.observation_time for point in actual] == expected_times
    assert [point.value for point in actual] == pytest.approx(
        expected_values,
        rel=1e-12,
        abs=1e-12,
    )


@hypothesis.given(
    points=tests.helpers.strategies.svg_charts.models.series_points(),
    divisor=hypothesis.strategies.floats(0.001, 1_000_000),
)
def test_scaled_points_preserves_observation_metadata(
    points: tuple[svg_charts.models.SeriesPoint, ...],
    divisor: float,
) -> None:
    scaled = peri_scribe.kml.plot_data.scaled_points(points, divisor)
    assert [dataclasses.replace(point, value=0) for point in scaled] == [
        dataclasses.replace(point, value=0) for point in points
    ]
