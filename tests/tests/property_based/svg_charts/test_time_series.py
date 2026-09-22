"""Tests for svg_charts.time_series."""

from __future__ import annotations

import itertools

import hypothesis

import svg_charts.models
import svg_charts.time_series
import tests.helpers.strategies.svg_charts.time_series


# This test is slow, so limit examples to keep routine test runs fast.
@hypothesis.settings(max_examples=25)
@hypothesis.given(
    series=tests.helpers.strategies.svg_charts.time_series.plot_series(),
)
def test_plot_layout_contains_every_measurement(
    series: tuple[svg_charts.models.PlotSeries, ...],
) -> None:
    layout = svg_charts.time_series.plot_layout(series)
    assert 0 <= layout.plot_left < layout.plot_right <= layout.width
    assert 0 <= layout.plot_top < layout.plot_bottom <= layout.height
    tolerance = 1e-9
    for line in series:
        for point in line.points:
            assert (
                layout.plot_left - tolerance
                <= layout.x_of(point.observation_time)
                <= layout.plot_right + tolerance
            )
            assert (
                layout.plot_top - tolerance
                <= layout.y_of(point.value)
                <= layout.plot_bottom + tolerance
            )


@hypothesis.given(
    points=tests.helpers.strategies.svg_charts.time_series.chronological_points(),
)
def test_line_segments_preserves_every_edge_and_its_destination_style(
    points: tuple[svg_charts.models.SeriesPoint, ...],
) -> None:
    segments = svg_charts.time_series.line_segments(points)
    minimum_line_points = 2
    assert all(len(segment) >= minimum_line_points for segment, _dashed in segments)
    assert [
        (left, right, dashed)
        for segment, dashed in segments
        for left, right in itertools.pairwise(segment)
    ] == [(left, right, right.style) for left, right in itertools.pairwise(points)]
