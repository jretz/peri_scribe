"""Tests for peri_scribe.kml.plot_drawing."""

from __future__ import annotations

import dataclasses
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


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0.00005, "0.00005"), (0.0075, "0.0075"), (0.000125, "0.000125")],
)
def test_format_tick_preserves_small_measurements(value: float, expected: str) -> None:
    assert peri_scribe.kml.plot_drawing.format_tick(value) == expected


@pytest.mark.parametrize("peak", [0.000001, 0.00005, 0.0025, 0.0076, 0.0125])
def test_draw_plot_gives_small_ticks_distinct_accurate_labels(peak: float) -> None:
    series = peri_scribe.kml.plot_data.PlotSeries(
        label="Cost to date",
        points=(
            tests.peri_scribe.kml.kml_plot_helpers.series_point(1, 0.0),
            tests.peri_scribe.kml.kml_plot_helpers.series_point(2, peak),
        ),
    )
    drawing = defusedxml.minidom.parseString(
        peri_scribe.kml.plot_drawing.draw_plot((series,)),
    )
    group = next(
        node
        for node in drawing.getElementsByTagName("g")
        if node.getAttribute("text-anchor") == "end"
    )
    labels = [node.firstChild.data for node in group.getElementsByTagName("text")]
    assert len(labels) == len(set(labels))
    _, ticks = peri_scribe.kml.plot_drawing.y_axis_ticks((series,))
    assert [float(label) for label in labels] == pytest.approx(ticks)


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


@pytest.mark.parametrize(
    ("reported", "expected"),
    [
        ((False, False), [("Mapped area", "")]),
        ((True, True), [("Reported Area", "5 3")]),
        (
            (False, False, True, True, False),
            [("Mapped area", ""), ("Reported Area", "5 3")],
        ),
        (
            (True, True, False, False),
            [("Mapped area", ""), ("Reported Area", "5 3")],
        ),
        ((False, True), [("Reported Area", "5 3")]),
        ((True, False), [("Mapped area", "")]),
    ],
)
def test_draw_plot_legend_identifies_visible_area_sources(
    reported: tuple[bool, ...],
    expected: list[tuple[str, str]],
) -> None:
    series = peri_scribe.kml.plot_data.PlotSeries(
        label="Mapped area",
        reported_label="Reported Area",
        points=tuple(
            dataclasses.replace(
                tests.peri_scribe.kml.kml_plot_helpers.series_point(day, float(day)),
                reported=is_reported,
            )
            for day, is_reported in enumerate(reported, start=1)
        ),
    )
    content = peri_scribe.kml.plot_drawing.draw_plot((series,))
    legend = plot_legend(content)
    assert [(label, dash) for label, _color, dash in legend] == expected
    assert {color for _label, color, _dash in legend} == {"#4c72b0"}


@pytest.mark.parametrize("point_count", [0, 1])
@pytest.mark.parametrize(
    ("visible_label", "missing_label"),
    [
        ("Exterior perimeter", "Contained perimeter"),
        ("Contained perimeter", "Exterior perimeter"),
        ("Cost to date", "Estimated final cost"),
        ("Estimated final cost", "Cost to date"),
    ],
)
def test_draw_plot_legend_omits_series_without_lines(
    visible_label: str,
    missing_label: str,
    point_count: int,
) -> None:
    points = one_series_plot()[0].points
    content = peri_scribe.kml.plot_drawing.draw_plot((
        peri_scribe.kml.plot_data.PlotSeries(
            label=missing_label,
            points=points[:point_count],
        ),
        peri_scribe.kml.plot_data.PlotSeries(label=visible_label, points=points),
    ))
    legend = plot_legend(content)
    assert [label for label, _color, _dash in legend] == [visible_label]
    drawing = defusedxml.minidom.parseString(content)
    assert len(drawing.getElementsByTagName("path")) == 1
    assert legend[0][1] == (
        drawing.getElementsByTagName("path")[0].getAttribute("stroke")
    )


def test_draw_plot_legend_includes_zero_valued_personnel() -> None:
    series = peri_scribe.kml.plot_data.PlotSeries(
        label="Personnel",
        points=tuple(
            tests.peri_scribe.kml.kml_plot_helpers.series_point(day, 0.0)
            for day in (1, 2)
        ),
    )
    legend = plot_legend(peri_scribe.kml.plot_drawing.draw_plot((series,)))
    assert [label for label, _color, _dash in legend] == ["Personnel"]


def test_draw_plot_omits_legend_for_isolated_observation() -> None:
    series = peri_scribe.kml.plot_data.PlotSeries(
        label="Personnel",
        points=one_series_plot()[0].points[:1],
    )
    content = peri_scribe.kml.plot_drawing.draw_plot((series,))
    assert b">Personnel<" not in content
    assert b"<path" not in content


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


@pytest.fixture
def intraday_series() -> tuple[peri_scribe.kml.plot_data.PlotSeries, ...]:
    """Expose date truncation through distinct, equally spaced readings within one day.

    Returns:
        One area series with morning, midday, and evening observations.
    """
    return (
        peri_scribe.kml.plot_data.PlotSeries(
            label="Area",
            points=tuple(
                peri_scribe.kml.plot_data.SeriesPoint(
                    observation_time=datetime.datetime(
                        2026,
                        9,
                        3,
                        hour,
                        tzinfo=datetime.UTC,
                    ),
                    value=value,
                )
                for hour, value in ((6, 100.0), (12, 500.0), (18, 200.0))
            ),
        ),
    )


def test_draw_plot_separates_intraday_readings(
    intraday_series: tuple[peri_scribe.kml.plot_data.PlotSeries, ...],
) -> None:
    drawing = defusedxml.minidom.parseString(
        peri_scribe.kml.plot_drawing.draw_plot(intraday_series),
    )
    commands = drawing.getElementsByTagName("path")[0].getAttribute("d").split()
    positions = [float(value) for value in commands[1::3]]
    layout = peri_scribe.kml.plot_drawing.plot_layout(intraday_series)
    assert layout.plot_left < positions[0] < positions[1] < positions[2]
    assert positions[2] < layout.plot_right
    assert positions[1] == pytest.approx(
        (positions[0] + positions[2]) / 2,
        abs=0.1,
    )


def test_plot_layout_x_of_keeps_elapsed_time_across_midnight(
    intraday_series: tuple[peri_scribe.kml.plot_data.PlotSeries, ...],
) -> None:
    layout = peri_scribe.kml.plot_drawing.plot_layout(intraday_series)
    midnight = datetime.datetime(2026, 9, 4, tzinfo=datetime.UTC)
    before = midnight - datetime.timedelta(hours=3)
    after = midnight + datetime.timedelta(hours=3)
    assert layout.x_of(midnight) - layout.x_of(before) == pytest.approx(
        layout.x_of(after) - layout.x_of(midnight),
    )


def test_plot_layout_uses_utc_days_for_offset_timestamps() -> None:
    observation = datetime.datetime.fromisoformat("2026-09-03T23:00:00-07:00")
    series = peri_scribe.kml.plot_data.PlotSeries(
        label="Area",
        points=(
            peri_scribe.kml.plot_data.SeriesPoint(
                observation_time=observation,
                value=100.0,
            ),
        ),
    )
    layout = peri_scribe.kml.plot_drawing.plot_layout((series,))
    assert layout.first_day == datetime.date(2026, 9, 4)
    assert layout.x_of(observation) == layout.x_of(
        observation.astimezone(datetime.UTC),
    )
    assert layout.x_of(observation) == pytest.approx(
        layout.plot_left + layout.plot_width / 4,
    )


def test_line_segments_keeps_source_switch_connected() -> None:
    first = tests.peri_scribe.kml.kml_plot_helpers.series_point(1, 100)
    second = tests.peri_scribe.kml.kml_plot_helpers.series_point(2, 100)
    report = dataclasses.replace(
        tests.peri_scribe.kml.kml_plot_helpers.series_point(3, 150),
        reported=True,
    )
    mapped = tests.peri_scribe.kml.kml_plot_helpers.series_point(4, 160)
    assert peri_scribe.kml.plot_drawing.line_segments((
        first,
        second,
        report,
        mapped,
    )) == [
        ((first, second), False),
        ((second, report), True),
        ((report, mapped), False),
    ]
    assert peri_scribe.kml.plot_drawing.line_segments(()) == []


def test_draw_plot_dashes_reported_area_segments() -> None:
    first = tests.peri_scribe.kml.kml_plot_helpers.series_point(1, 100)
    report = dataclasses.replace(
        tests.peri_scribe.kml.kml_plot_helpers.series_point(3, 150),
        reported=True,
    )
    series = peri_scribe.kml.plot_data.PlotSeries(label="Area", points=(first, report))
    drawing = peri_scribe.kml.plot_drawing.draw_plot((series,), y_axis_label="Acres")
    assert b'stroke-dasharray="5 3"' in drawing
