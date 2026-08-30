"""Tests for peri_scribe.kml_plot_drawing."""

from __future__ import annotations

import datetime
import io

import matplotlib.dates
import pytest
from PIL import Image

import peri_scribe.kml_plot_data
import peri_scribe.kml_plot_drawing
import tests.kml_plot_helpers


def test_format_tick_uses_thousands_for_large_values() -> None:
    assert peri_scribe.kml_plot_drawing.format_tick(1234567.0, 0) == "1,234,567"


def test_format_tick_uses_one_decimal_for_medium_values() -> None:
    assert peri_scribe.kml_plot_drawing.format_tick(33.1, 0) == "33.1"


def test_format_tick_uses_two_decimals_for_small_values() -> None:
    assert peri_scribe.kml_plot_drawing.format_tick(0.5, 0) == "0.5"


def test_format_tick_drops_trailing_zero() -> None:
    assert peri_scribe.kml_plot_drawing.format_tick(33.0, 0) == "33"
    assert peri_scribe.kml_plot_drawing.format_tick(0.0, 0) == "0"


def test_x_axis_ticks_returns_empty_without_points() -> None:
    assert peri_scribe.kml_plot_drawing.x_axis_ticks(()) == ()


def test_observation_day_span_returns_first_and_last_days() -> None:
    series = (
        peri_scribe.kml_plot_data.PlotSeries(
            label="Area",
            points=(
                tests.kml_plot_helpers.series_point(1, 10.0),
                tests.kml_plot_helpers.series_point(3, 20.0),
            ),
        ),
    )
    assert peri_scribe.kml_plot_drawing.observation_day_span(series) == (
        datetime.date(2026, 8, 1),
        datetime.date(2026, 8, 3),
    )


def test_x_axis_ticks_uses_each_midnight_when_days_fit() -> None:
    series = (
        peri_scribe.kml_plot_data.PlotSeries(
            label="Area",
            points=(
                tests.kml_plot_helpers.series_point(1, 10.0),
                tests.kml_plot_helpers.series_point(3, 20.0),
            ),
        ),
    )
    assert peri_scribe.kml_plot_drawing.x_axis_ticks(series) == (
        tests.kml_plot_helpers.observation_time(1),
        tests.kml_plot_helpers.observation_time(2),
        tests.kml_plot_helpers.observation_time(3),
    )


def test_x_axis_ticks_thins_when_days_do_not_fit() -> None:
    series = (
        peri_scribe.kml_plot_data.PlotSeries(
            label="Area",
            points=(
                tests.kml_plot_helpers.series_point(1, 10.0),
                tests.kml_plot_helpers.series_point(20, 20.0),
            ),
        ),
    )
    assert peri_scribe.kml_plot_drawing.x_axis_ticks(series) == (
        tests.kml_plot_helpers.observation_time(1),
        tests.kml_plot_helpers.observation_time(5),
        tests.kml_plot_helpers.observation_time(9),
        tests.kml_plot_helpers.observation_time(13),
        tests.kml_plot_helpers.observation_time(17),
    )


def test_x_axis_ticks_does_not_force_the_last_day() -> None:
    series = (
        peri_scribe.kml_plot_data.PlotSeries(
            label="Cost to date",
            points=(
                tests.kml_plot_helpers.series_point(1, 10.0),
                tests.kml_plot_helpers.series_point(10, 20.0),
            ),
        ),
    )
    assert peri_scribe.kml_plot_drawing.x_axis_ticks(series) == (
        tests.kml_plot_helpers.observation_time(1),
        tests.kml_plot_helpers.observation_time(3),
        tests.kml_plot_helpers.observation_time(5),
        tests.kml_plot_helpers.observation_time(7),
        tests.kml_plot_helpers.observation_time(9),
    )


def test_draw_plot_returns_png_for_one_series() -> None:
    content = peri_scribe.kml_plot_drawing.draw_plot(
        peri_scribe.kml_plot_drawing.create_plot_renderer(),
        (
            peri_scribe.kml_plot_data.PlotSeries(
                label="Area",
                points=(
                    tests.kml_plot_helpers.series_point(1, 10.0),
                    tests.kml_plot_helpers.series_point(2, 20.0),
                ),
            ),
        ),
        y_axis_label="Thousands of acres",
    )
    assert content.startswith(tests.kml_plot_helpers.PNG_SIGNATURE)


def test_draw_plot_returns_palette_png_for_one_series() -> None:
    content = peri_scribe.kml_plot_drawing.draw_plot(
        peri_scribe.kml_plot_drawing.create_plot_renderer(),
        (
            peri_scribe.kml_plot_data.PlotSeries(
                label="Area",
                points=(
                    tests.kml_plot_helpers.series_point(1, 10.0),
                    tests.kml_plot_helpers.series_point(2, 20.0),
                ),
            ),
        ),
        y_axis_label="Thousands of acres",
    )
    assert content.startswith(tests.kml_plot_helpers.PNG_SIGNATURE)
    with Image.open(io.BytesIO(content)) as image:
        assert image.mode == "P"
        assert image.size == (
            round(
                peri_scribe.kml_plot_drawing.FIGURE_WIDTH_IN_INCHES
                * peri_scribe.kml_plot_drawing.IMAGE_DPI,
            ),
            round(
                peri_scribe.kml_plot_drawing.FIGURE_HEIGHT_IN_INCHES
                * peri_scribe.kml_plot_drawing.IMAGE_DPI,
            ),
        )


def test_draw_plot_returns_png_for_multiple_series() -> None:
    content = peri_scribe.kml_plot_drawing.draw_plot(
        peri_scribe.kml_plot_drawing.create_plot_renderer(),
        (
            peri_scribe.kml_plot_data.PlotSeries(
                label="Cost to date",
                points=(
                    tests.kml_plot_helpers.series_point(1, 10.0),
                    tests.kml_plot_helpers.series_point(2, 20.0),
                ),
            ),
            peri_scribe.kml_plot_data.PlotSeries(
                label="Estimated final cost",
                points=(
                    tests.kml_plot_helpers.series_point(1, 5.0),
                    tests.kml_plot_helpers.series_point(2, 15.0),
                ),
            ),
        ),
        y_axis_label="Millions of $",
    )
    assert content.startswith(tests.kml_plot_helpers.PNG_SIGNATURE)


def test_draw_plot_starts_y_axis_at_zero() -> None:
    renderer = peri_scribe.kml_plot_drawing.create_plot_renderer()
    peri_scribe.kml_plot_drawing.draw_plot(
        renderer,
        (
            peri_scribe.kml_plot_data.PlotSeries(
                label="Cost to date",
                points=(
                    tests.kml_plot_helpers.series_point(1, 14.58),
                    tests.kml_plot_helpers.series_point(2, 125.0),
                ),
            ),
        ),
        y_axis_label="Millions of $",
    )
    axes = renderer.figure.axes[0]
    assert axes.get_ylim()[0] == pytest.approx(0.0)


def test_draw_plot_leaves_x_axis_unlabeled() -> None:
    renderer = peri_scribe.kml_plot_drawing.create_plot_renderer()
    peri_scribe.kml_plot_drawing.draw_plot(
        renderer,
        (
            peri_scribe.kml_plot_data.PlotSeries(
                label="Area",
                points=(
                    tests.kml_plot_helpers.series_point(1, 10.0),
                    tests.kml_plot_helpers.series_point(2, 20.0),
                ),
            ),
        ),
        y_axis_label="Thousands of acres",
    )
    axes = renderer.figure.axes[0]
    assert axes.get_xlabel() == ""


def test_draw_plot_spans_x_axis_to_the_last_observation_day() -> None:
    renderer = peri_scribe.kml_plot_drawing.create_plot_renderer()
    peri_scribe.kml_plot_drawing.draw_plot(
        renderer,
        (
            peri_scribe.kml_plot_data.PlotSeries(
                label="Cost to date",
                points=(
                    tests.kml_plot_helpers.series_point(1, 10.0),
                    tests.kml_plot_helpers.series_point(10, 20.0),
                ),
            ),
        ),
        y_axis_label="Millions of $",
    )
    axes = renderer.figure.axes[0]
    assert axes.get_xlim() == pytest.approx(
        (
            matplotlib.dates.date2num(tests.kml_plot_helpers.observation_time(1)),
            matplotlib.dates.date2num(tests.kml_plot_helpers.observation_time(11)),
        ),
    )


def test_draw_plot_reuses_renderer_between_plots() -> None:
    renderer = peri_scribe.kml_plot_drawing.create_plot_renderer()
    series = (
        peri_scribe.kml_plot_data.PlotSeries(
            label="Area",
            points=(
                tests.kml_plot_helpers.series_point(1, 10.0),
                tests.kml_plot_helpers.series_point(2, 20.0),
            ),
        ),
    )
    first = peri_scribe.kml_plot_drawing.draw_plot(
        renderer,
        series,
        y_axis_label="Thousands of acres",
    )
    second = peri_scribe.kml_plot_drawing.draw_plot(
        renderer,
        series,
        y_axis_label="Thousands of acres",
    )
    assert first == second
    assert first.startswith(tests.kml_plot_helpers.PNG_SIGNATURE)
