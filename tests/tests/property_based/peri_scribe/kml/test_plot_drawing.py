"""Tests for peri_scribe.kml.plot_drawing."""

from __future__ import annotations

import itertools

import hypothesis

import peri_scribe.kml.plot_data
import peri_scribe.kml.plot_drawing
import tests.helpers.strategies.peri_scribe.kml.plot_drawing


# This test is slow, so limit examples to keep routine test runs fast.
@hypothesis.settings(max_examples=25)
@hypothesis.given(
    series=tests.helpers.strategies.peri_scribe.kml.plot_drawing.plot_series(),
)
def test_plot_layout_contains_every_measurement(
    series: tuple[peri_scribe.kml.plot_data.PlotSeries, ...],
) -> None:
    layout = peri_scribe.kml.plot_drawing.plot_layout(series)
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
    points=tests.helpers.strategies.peri_scribe.kml.plot_drawing.chronological_points(),
)
def test_line_segments_preserves_every_edge_and_its_destination_source(
    points: tuple[peri_scribe.kml.plot_data.SeriesPoint, ...],
) -> None:
    segments = peri_scribe.kml.plot_drawing.line_segments(points)
    minimum_line_points = 2
    assert all(len(segment) >= minimum_line_points for segment, _reported in segments)
    assert [
        (left, right, reported)
        for segment, reported in segments
        for left, right in itertools.pairwise(segment)
    ] == [(left, right, right.reported) for left, right in itertools.pairwise(points)]
