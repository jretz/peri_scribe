"""Tests for peri_scribe.kml_plot_rendering."""

from __future__ import annotations

import os

import pytest

import peri_scribe.kml_plot_data
import peri_scribe.kml_plot_drawing
import peri_scribe.kml_plot_rendering
import tests.kml_plot_helpers


def test_plot_filename_joins_prefix_and_suffix() -> None:
    assert (
        peri_scribe.kml_plot_rendering.plot_filename("id-bug", "area")
        == "id-bug-area.png"
    )


def test_filename_prefix_uses_identifier() -> None:
    assert peri_scribe.kml_plot_rendering.filename_prefix(
        "2026-cabug-000001",
        "Bug",
    ) == ("2026-cabug-000001")


def test_filename_prefix_slugifies_name() -> None:
    assert (
        peri_scribe.kml_plot_rendering.filename_prefix(None, "Santa Rosa!")
        == "santa-rosa"
    )


def test_filename_prefix_falls_back_to_fire_for_empty_name() -> None:
    assert peri_scribe.kml_plot_rendering.filename_prefix(None, "!!!") == "fire"


def test_initialize_worker_creates_shared_renderer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(peri_scribe.kml_plot_rendering, "worker_renderers", [])
    monkeypatch.setattr(
        peri_scribe.kml_plot_rendering.os,
        "nice",
        lambda increment: increment,
    )
    peri_scribe.kml_plot_rendering.initialize_worker()
    image = peri_scribe.kml_plot_rendering.render_plot_request(
        peri_scribe.kml_plot_rendering.PlotRequest(
            fire_index=0,
            filename_prefix="id-bug",
            filename_suffix="area",
            y_axis_label="Thousands of acres",
            series=(
                peri_scribe.kml_plot_data.PlotSeries(
                    label="Area",
                    points=(
                        tests.kml_plot_helpers.series_point(1, 10.0),
                        tests.kml_plot_helpers.series_point(2, 20.0),
                    ),
                ),
            ),
        ),
    )
    assert image.filename == "id-bug-area.png"
    assert image.content.startswith(tests.kml_plot_helpers.PNG_SIGNATURE)


def test_initialize_worker_nices_the_worker_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    niceness_calls: list[int] = []
    monkeypatch.setattr(
        peri_scribe.kml_plot_rendering.os,
        "nice",
        lambda increment: niceness_calls.append(increment) or increment,
    )
    peri_scribe.kml_plot_rendering.initialize_worker()
    assert niceness_calls == [
        peri_scribe.kml_plot_rendering.WORKER_NICENESS_INCREMENT,
    ]


def test_initialize_worker_continues_when_niceness_is_denied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def deny_niceness(_increment: int) -> int:
        message = "Operation not permitted"
        raise PermissionError(message)

    monkeypatch.setattr(peri_scribe.kml_plot_rendering, "worker_renderers", [])
    monkeypatch.setattr(peri_scribe.kml_plot_rendering.os, "nice", deny_niceness)
    peri_scribe.kml_plot_rendering.initialize_worker()
    assert len(peri_scribe.kml_plot_rendering.worker_renderers) == 1
    assert isinstance(
        peri_scribe.kml_plot_rendering.worker_renderers[0],
        peri_scribe.kml_plot_drawing.PlotRenderer,
    )


def test_render_plot_request_raises_without_initialized_renderer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(peri_scribe.kml_plot_rendering, "worker_renderers", [])
    with pytest.raises(RuntimeError):
        peri_scribe.kml_plot_rendering.render_plot_request(
            peri_scribe.kml_plot_rendering.PlotRequest(
                fire_index=0,
                filename_prefix="id-bug",
                filename_suffix="area",
                y_axis_label="Thousands of acres",
                series=(),
            ),
        )


def test_worker_count_for_caps_at_cores_and_tasks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cpu_count = 12
    monkeypatch.setattr(os, "cpu_count", lambda: cpu_count)
    assert peri_scribe.kml_plot_rendering.worker_count_for(100) == cpu_count
    task_count = 2
    assert peri_scribe.kml_plot_rendering.worker_count_for(task_count) == task_count
    monkeypatch.setattr(os, "cpu_count", lambda: 1)
    assert peri_scribe.kml_plot_rendering.worker_count_for(5) == 1


def test_plot_image_bundles_renders_each_fire_in_parallel() -> None:
    area_plot = peri_scribe.kml_plot_data.FirePlot(
        filename_suffix="area",
        series=(
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
    perimeter_plot = peri_scribe.kml_plot_data.FirePlot(
        filename_suffix="perimeter",
        series=(
            peri_scribe.kml_plot_data.PlotSeries(
                label="Exterior perimeter",
                points=(
                    tests.kml_plot_helpers.series_point(1, 5.0),
                    tests.kml_plot_helpers.series_point(2, 8.0),
                ),
            ),
            peri_scribe.kml_plot_data.PlotSeries(
                label="Contained perimeter",
                points=(
                    tests.kml_plot_helpers.series_point(1, 2.0),
                    tests.kml_plot_helpers.series_point(2, 3.0),
                ),
            ),
        ),
        y_axis_label="Miles",
    )
    single_observation_plot = peri_scribe.kml_plot_data.FirePlot(
        filename_suffix="cost",
        series=(
            peri_scribe.kml_plot_data.PlotSeries(
                label="Cost to date",
                points=(tests.kml_plot_helpers.series_point(1, 1000.0),),
            ),
        ),
        y_axis_label="Millions of $",
    )
    bundles = peri_scribe.kml_plot_rendering.plot_image_bundles(
        (
            ("id-bug", (area_plot, perimeter_plot, single_observation_plot)),
            ("id-alta", (area_plot,)),
        ),
    )
    assert [image.filename for image in bundles[0]] == [
        "id-bug-area.png",
        "id-bug-perimeter.png",
    ]
    assert [image.filename for image in bundles[1]] == ["id-alta-area.png"]
    for bundle in bundles:
        for image in bundle:
            assert image.content.startswith(tests.kml_plot_helpers.PNG_SIGNATURE)


def test_plot_image_bundles_returns_empty_bundles_without_requests() -> None:
    single_observation_plot = peri_scribe.kml_plot_data.FirePlot(
        filename_suffix="area",
        series=(
            peri_scribe.kml_plot_data.PlotSeries(
                label="Area",
                points=(tests.kml_plot_helpers.series_point(1, 10.0),),
            ),
        ),
        y_axis_label="Thousands of acres",
    )
    assert peri_scribe.kml_plot_rendering.plot_image_bundles(
        (("id-bug", (single_observation_plot,)),),
    ) == ((),)


def test_plot_image_bundles_returns_empty_for_no_fires() -> None:
    assert peri_scribe.kml_plot_rendering.plot_image_bundles(()) == ()
