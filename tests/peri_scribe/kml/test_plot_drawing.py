"""Tests for peri_scribe.kml.plot_drawing."""

from __future__ import annotations

import datetime

import defusedxml.minidom
import pytest

import peri_scribe.kml.plot_data
import peri_scribe.kml.plot_drawing
import tests.peri_scribe.kml.kml_plot_helpers


def test_format_tick_uses_thousands_for_large_values() -> None:
    assert peri_scribe.kml.plot_drawing.format_tick(1234567.0) == "1,234,567"


def test_format_tick_uses_one_decimal_for_medium_values() -> None:
    assert peri_scribe.kml.plot_drawing.format_tick(33.1) == "33.1"


def test_format_tick_uses_two_decimals_for_small_values() -> None:
    assert peri_scribe.kml.plot_drawing.format_tick(0.5) == "0.5"


def test_format_tick_drops_trailing_zero() -> None:
    assert peri_scribe.kml.plot_drawing.format_tick(33.0) == "33"
    assert peri_scribe.kml.plot_drawing.format_tick(0.0) == "0"


def test_x_axis_ticks_returns_empty_without_points() -> None:
    assert peri_scribe.kml.plot_drawing.x_axis_ticks(()) == ()


def test_observation_day_span_returns_first_and_last_days() -> None:
    series = (
        peri_scribe.kml.plot_data.PlotSeries(
            label="Area",
            points=(
                tests.peri_scribe.kml.kml_plot_helpers.series_point(1, 10.0),
                tests.peri_scribe.kml.kml_plot_helpers.series_point(3, 20.0),
            ),
        ),
    )
    assert peri_scribe.kml.plot_drawing.observation_day_span(series) == (
        datetime.date(2026, 8, 1),
        datetime.date(2026, 8, 3),
    )


def test_x_axis_ticks_uses_each_midnight_when_days_fit() -> None:
    series = (
        peri_scribe.kml.plot_data.PlotSeries(
            label="Area",
            points=(
                tests.peri_scribe.kml.kml_plot_helpers.series_point(1, 10.0),
                tests.peri_scribe.kml.kml_plot_helpers.series_point(3, 20.0),
            ),
        ),
    )
    assert peri_scribe.kml.plot_drawing.x_axis_ticks(series) == (
        tests.peri_scribe.kml.kml_plot_helpers.observation_time(1),
        tests.peri_scribe.kml.kml_plot_helpers.observation_time(2),
        tests.peri_scribe.kml.kml_plot_helpers.observation_time(3),
    )


def test_x_axis_ticks_thins_when_days_do_not_fit() -> None:
    series = (
        peri_scribe.kml.plot_data.PlotSeries(
            label="Area",
            points=(
                tests.peri_scribe.kml.kml_plot_helpers.series_point(1, 10.0),
                tests.peri_scribe.kml.kml_plot_helpers.series_point(20, 20.0),
            ),
        ),
    )
    assert peri_scribe.kml.plot_drawing.x_axis_ticks(series) == (
        tests.peri_scribe.kml.kml_plot_helpers.observation_time(1),
        tests.peri_scribe.kml.kml_plot_helpers.observation_time(5),
        tests.peri_scribe.kml.kml_plot_helpers.observation_time(9),
        tests.peri_scribe.kml.kml_plot_helpers.observation_time(13),
        tests.peri_scribe.kml.kml_plot_helpers.observation_time(17),
    )


def test_x_axis_ticks_does_not_force_the_last_day() -> None:
    series = (
        peri_scribe.kml.plot_data.PlotSeries(
            label="Cost to date",
            points=(
                tests.peri_scribe.kml.kml_plot_helpers.series_point(1, 10.0),
                tests.peri_scribe.kml.kml_plot_helpers.series_point(10, 20.0),
            ),
        ),
    )
    assert peri_scribe.kml.plot_drawing.x_axis_ticks(series) == (
        tests.peri_scribe.kml.kml_plot_helpers.observation_time(1),
        tests.peri_scribe.kml.kml_plot_helpers.observation_time(3),
        tests.peri_scribe.kml.kml_plot_helpers.observation_time(5),
        tests.peri_scribe.kml.kml_plot_helpers.observation_time(7),
        tests.peri_scribe.kml.kml_plot_helpers.observation_time(9),
    )


def one_series_plot() -> tuple[peri_scribe.kml.plot_data.PlotSeries, ...]:
    return (
        peri_scribe.kml.plot_data.PlotSeries(
            label="Area",
            points=(
                tests.peri_scribe.kml.kml_plot_helpers.series_point(1, 10.0),
                tests.peri_scribe.kml.kml_plot_helpers.series_point(2, 20.0),
            ),
        ),
    )


def test_draw_plot_returns_well_formed_svg_for_one_series() -> None:
    content = peri_scribe.kml.plot_drawing.draw_plot(
        one_series_plot(),
        y_axis_label="Thousands of acres",
    )
    assert content.startswith(b"<svg")
    defusedxml.minidom.parseString(content)
    assert b"<path" in content


def test_draw_plot_uses_the_configured_chart_size() -> None:
    content = peri_scribe.kml.plot_drawing.draw_plot(one_series_plot())
    width = int(peri_scribe.kml.plot_drawing.CHART_WIDTH.magnitude)
    height = int(peri_scribe.kml.plot_drawing.CHART_HEIGHT.magnitude)
    assert f'width="{width}" height="{height}"'.encode() in content


def test_draw_plot_labels_every_series_in_the_legend() -> None:
    content = peri_scribe.kml.plot_drawing.draw_plot(
        (
            *one_series_plot(),
            peri_scribe.kml.plot_data.PlotSeries(
                label="Contained perimeter",
                points=(
                    tests.peri_scribe.kml.kml_plot_helpers.series_point(1, 5.0),
                    tests.peri_scribe.kml.kml_plot_helpers.series_point(2, 15.0),
                ),
            ),
        ),
        y_axis_label="Miles",
    )
    assert b">Area<" in content
    assert b">Contained perimeter<" in content


def test_draw_plot_escapes_the_axis_label() -> None:
    content = peri_scribe.kml.plot_drawing.draw_plot(
        one_series_plot(),
        y_axis_label='Millions of $ & "<cost>"',
    )
    defusedxml.minidom.parseString(content)
    assert b"&amp;" in content
    assert b"&lt;cost&gt;" in content


def test_draw_plot_is_deterministic() -> None:
    first = peri_scribe.kml.plot_drawing.draw_plot(
        one_series_plot(),
        y_axis_label="Thousands of acres",
    )
    second = peri_scribe.kml.plot_drawing.draw_plot(
        one_series_plot(),
        y_axis_label="Thousands of acres",
    )
    assert first == second


def test_nice_step_handles_an_empty_span() -> None:
    assert peri_scribe.kml.plot_drawing.nice_step(0.0) == pytest.approx(1.0)


def test_y_axis_ticks_covers_a_peak_of_zero() -> None:
    flat = (
        peri_scribe.kml.plot_data.PlotSeries(
            label="Area",
            points=(
                tests.peri_scribe.kml.kml_plot_helpers.series_point(1, 0.0),
                tests.peri_scribe.kml.kml_plot_helpers.series_point(2, 0.0),
            ),
        ),
    )
    assert peri_scribe.kml.plot_drawing.y_axis_ticks(flat) == (1.0, (0.0, 1.0))


def test_plot_layout_spans_the_x_axis_past_the_last_observation() -> None:
    first_observed_day = 1
    last_observed_day = 10
    series = (
        peri_scribe.kml.plot_data.PlotSeries(
            label="Cost to date",
            points=(
                tests.peri_scribe.kml.kml_plot_helpers.series_point(
                    first_observed_day,
                    10.0,
                ),
                tests.peri_scribe.kml.kml_plot_helpers.series_point(
                    last_observed_day,
                    20.0,
                ),
            ),
        ),
    )
    layout = peri_scribe.kml.plot_drawing.plot_layout(series)
    assert (
        layout.first_day
        == tests.peri_scribe.kml.kml_plot_helpers.observation_time(
            first_observed_day,
        ).date()
    )
    # One whole day past the last observation, so the final tick clears the right edge.
    assert layout.day_span == last_observed_day - first_observed_day + 1
    assert (
        layout.x_of(
            tests.peri_scribe.kml.kml_plot_helpers.observation_time(
                last_observed_day,
            ),
        )
        < layout.plot_right
    )


def test_plot_layout_keeps_the_chart_inside_the_canvas() -> None:
    layout = peri_scribe.kml.plot_drawing.plot_layout(one_series_plot())
    assert 0 < layout.plot_left < layout.plot_right < layout.width
    assert 0 < layout.plot_top < layout.plot_bottom < layout.height
