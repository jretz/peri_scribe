"""Tests for peri_scribe.kml.plot_rendering."""

from __future__ import annotations

import datetime

import peri_scribe.kml.plot_data
import peri_scribe.kml.plot_rendering
import tests.peri_scribe.kml.kml_plot_helpers


def test_plot_filename_joins_prefix_and_suffix() -> None:
    assert (
        peri_scribe.kml.plot_rendering.plot_filename("id-bug", "area")
        == "id-bug-area.svg"
    )


def test_filename_prefix_uses_identifier() -> None:
    assert peri_scribe.kml.plot_rendering.filename_prefix(
        "2026-cabug-000001",
        "Bug",
    ) == ("2026-cabug-000001")


def test_filename_prefix_slugifies_name() -> None:
    assert (
        peri_scribe.kml.plot_rendering.filename_prefix(None, "Santa Rosa!")
        == "santa-rosa"
    )


def test_filename_prefix_falls_back_to_fire_for_empty_name() -> None:
    assert peri_scribe.kml.plot_rendering.filename_prefix(None, "!!!") == "fire"


def test_plot_image_bundles_renders_each_fire_in_order() -> None:
    area_plot = peri_scribe.kml.plot_data.FirePlot(
        filename_suffix="area",
        series=(
            peri_scribe.kml.plot_data.PlotSeries(
                label="Area",
                points=(
                    tests.peri_scribe.kml.kml_plot_helpers.series_point(1, 10.0),
                    tests.peri_scribe.kml.kml_plot_helpers.series_point(2, 20.0),
                ),
            ),
        ),
        y_axis_label="Thousands of acres",
    )
    perimeter_plot = peri_scribe.kml.plot_data.FirePlot(
        filename_suffix="perimeter",
        series=(
            peri_scribe.kml.plot_data.PlotSeries(
                label="Exterior perimeter",
                points=(
                    tests.peri_scribe.kml.kml_plot_helpers.series_point(1, 5.0),
                    tests.peri_scribe.kml.kml_plot_helpers.series_point(2, 8.0),
                ),
            ),
            peri_scribe.kml.plot_data.PlotSeries(
                label="Contained perimeter",
                points=(
                    tests.peri_scribe.kml.kml_plot_helpers.series_point(1, 2.0),
                    tests.peri_scribe.kml.kml_plot_helpers.series_point(2, 3.0),
                ),
            ),
        ),
        y_axis_label="Miles",
    )
    single_observation_plot = peri_scribe.kml.plot_data.FirePlot(
        filename_suffix="cost",
        series=(
            peri_scribe.kml.plot_data.PlotSeries(
                label="Cost to date",
                points=(
                    tests.peri_scribe.kml.kml_plot_helpers.series_point(1, 1_000.0),
                ),
            ),
        ),
        y_axis_label="Millions of $",
    )
    bundles = peri_scribe.kml.plot_rendering.plot_image_bundles(
        (
            ("id-bug", (area_plot, perimeter_plot, single_observation_plot)),
            ("id-alta", (area_plot,)),
        ),
    )
    assert [image.filename for image in bundles[0]] == [
        "id-bug-area.svg",
        "id-bug-perimeter.svg",
    ]
    assert [image.filename for image in bundles[1]] == ["id-alta-area.svg"]
    for bundle in bundles:
        for image in bundle:
            assert image.content.startswith(b"<svg")


def test_plot_image_bundles_runs_before_rendering() -> None:
    plot = peri_scribe.kml.plot_data.FirePlot(
        filename_suffix="area",
        series=(
            peri_scribe.kml.plot_data.PlotSeries(
                label="Area",
                points=(
                    tests.peri_scribe.kml.kml_plot_helpers.series_point(1, 10.0),
                    tests.peri_scribe.kml.kml_plot_helpers.series_point(2, 20.0),
                ),
            ),
        ),
        y_axis_label="Thousands of acres",
    )
    calls: list[str] = []

    def record() -> None:
        calls.append("before")

    bundles = peri_scribe.kml.plot_rendering.plot_image_bundles(
        (("id-one", (plot,)),),
        before_rendering=record,
    )
    assert calls == ["before"]
    assert [image.filename for image in bundles[0]] == ["id-one-area.svg"]


def test_plot_image_bundles_returns_empty_bundles_without_requests() -> None:
    single_observation_plot = peri_scribe.kml.plot_data.FirePlot(
        filename_suffix="area",
        series=(
            peri_scribe.kml.plot_data.PlotSeries(
                label="Area",
                points=(tests.peri_scribe.kml.kml_plot_helpers.series_point(1, 10.0),),
            ),
        ),
        y_axis_label="Thousands of acres",
    )
    assert peri_scribe.kml.plot_rendering.plot_image_bundles(
        (("id-bug", (single_observation_plot,)),),
    ) == ((),)


def test_plot_image_bundles_returns_empty_for_no_fires() -> None:
    assert peri_scribe.kml.plot_rendering.plot_image_bundles(()) == ()


def two_point_series() -> peri_scribe.kml.plot_data.PlotSeries:
    return peri_scribe.kml.plot_data.PlotSeries(
        label="Area",
        points=(
            peri_scribe.kml.plot_data.SeriesPoint(
                observation_time=datetime.datetime(2026, 7, 8, tzinfo=datetime.UTC),
                value=1.0,
            ),
            peri_scribe.kml.plot_data.SeriesPoint(
                observation_time=datetime.datetime(2026, 7, 10, tzinfo=datetime.UTC),
                value=2.0,
            ),
        ),
    )


def test_render_plot_request_returns_the_rendered_svg() -> None:
    image = peri_scribe.kml.plot_rendering.render_plot_request(
        peri_scribe.kml.plot_rendering.PlotRequest(
            fire_index=0,
            filename_prefix="id-bug",
            filename_suffix="area",
            y_axis_label="Thousands of acres",
            series=(two_point_series(),),
        ),
    )
    assert image.filename == "id-bug-area.svg"
    assert image.content.startswith(b"<svg")


def test_plot_requests_indexes_each_plot_by_its_fire() -> None:
    plot = peri_scribe.kml.plot_data.FirePlot(
        filename_suffix="area",
        y_axis_label="Thousands of acres",
        series=(two_point_series(),),
    )
    requests = peri_scribe.kml.plot_rendering.plot_requests(
        (("id-one", (plot,)), ("id-two", (plot, plot))),
    )
    assert [request.fire_index for request in requests] == [0, 1, 1]
    assert [request.filename_prefix for request in requests] == [
        "id-one",
        "id-two",
        "id-two",
    ]


def test_plot_requests_skips_plots_without_enough_observations() -> None:
    one_point = peri_scribe.kml.plot_data.PlotSeries(
        label="Area",
        points=(
            peri_scribe.kml.plot_data.SeriesPoint(
                observation_time=datetime.datetime(2026, 7, 8, tzinfo=datetime.UTC),
                value=1.0,
            ),
        ),
    )
    plot = peri_scribe.kml.plot_data.FirePlot(
        filename_suffix="area",
        y_axis_label="Thousands of acres",
        series=(one_point,),
    )
    assert peri_scribe.kml.plot_rendering.plot_requests((("id-one", (plot,)),)) == []
