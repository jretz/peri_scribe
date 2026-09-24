"""Reuse SVG bytes without freezing current filenames or rendering callbacks."""

import dataclasses
import pathlib

import pandas as pd
import pytest

import peri_scribe.kml.plot_data
import peri_scribe.kml.plot_rendering
import spatial_data.product_cache
import svg_charts.models
import svg_charts.svg
import svg_charts.time_series
import tests.helpers.doubles.errors
import tests.helpers.doubles.peri_scribe.kml.plot_rendering
import tests.helpers.factories.peri_scribe.kml.plot_rendering


def test_render_plot_request_reuses_bytes_with_current_filename(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = tests.helpers.factories.peri_scribe.kml.plot_rendering.plot_request()
    database = tmp_path / "products.sqlite"
    with spatial_data.product_cache.scope(database, "test"):
        first = peri_scribe.kml.plot_rendering.render_plot_request(request)
    monkeypatch.setattr(
        svg_charts.time_series,
        "draw_plot",
        tests.helpers.doubles.errors.raising_stub(AssertionError("Repeated drawing")),
    )
    changed = dataclasses.replace(
        request,
        fire_index=3,
        filename_prefix="renamed",
        filename_suffix="current",
    )
    with spatial_data.product_cache.scope(database, "test"):
        second = peri_scribe.kml.plot_rendering.render_plot_request(changed)
    assert second.filename == "renamed-current.svg"
    assert second.content == first.content


@pytest.mark.parametrize(
    "change",
    ["value", "time", "style", "point_order", "label", "dashed", "color"],
)
def test_render_plot_request_invalidates_changed_series_inputs(
    tmp_path: pathlib.Path,
    change: str,
) -> None:
    request = tests.helpers.factories.peri_scribe.kml.plot_rendering.plot_request()
    series = request.series[0]
    point = series.points[1]
    if change == "value":
        series = dataclasses.replace(
            series,
            points=(series.points[0], dataclasses.replace(point, value=4.0)),
        )
    elif change == "time":
        series = dataclasses.replace(
            series,
            points=(
                series.points[0],
                dataclasses.replace(
                    point,
                    observation_time=pd.Timestamp(point.observation_time).as_unit("ns")
                    + pd.Timedelta(1, unit="ns"),
                ),
            ),
        )
    elif change == "style":
        series = dataclasses.replace(
            series,
            points=(
                series.points[0],
                dataclasses.replace(point, style=svg_charts.models.StrokeStyle.DASHED),
            ),
        )
    elif change == "point_order":
        series = dataclasses.replace(series, points=tuple(reversed(series.points)))
    elif change == "label":
        series = dataclasses.replace(series, label="Changed")
    elif change == "dashed":
        series = dataclasses.replace(series, dashed_label="Estimated")
    else:
        series = dataclasses.replace(series, color=svg_charts.models.SeriesColor.ORANGE)
    changed = dataclasses.replace(request, series=(series,))
    assert peri_scribe.kml.plot_rendering.plot_key(request) != (
        peri_scribe.kml.plot_rendering.plot_key(changed)
    )
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "test"):
        peri_scribe.kml.plot_rendering.render_plot_request(request)
        result = peri_scribe.kml.plot_rendering.render_plot_request(changed)
    assert result.content == svg_charts.time_series.draw_plot(
        changed.series,
        y_axis_label=changed.y_axis_label,
    )


def test_plot_key_includes_series_order_and_axis_label() -> None:
    request = tests.helpers.factories.peri_scribe.kml.plot_rendering.plot_request()
    second = dataclasses.replace(request.series[0], label="Second")
    original = dataclasses.replace(request, series=(*request.series, second))
    key = peri_scribe.kml.plot_rendering.plot_key(original)
    assert key != peri_scribe.kml.plot_rendering.plot_key(
        dataclasses.replace(original, series=tuple(reversed(original.series))),
    )
    assert key != peri_scribe.kml.plot_rendering.plot_key(
        dataclasses.replace(original, y_axis_label="Square miles"),
    )


@pytest.mark.parametrize("setting", ["layout", "font", "metrics", "locale", "timezone"])
def test_plot_key_includes_all_runtime_renderer_settings(
    monkeypatch: pytest.MonkeyPatch,
    setting: str,
) -> None:
    request = tests.helpers.factories.peri_scribe.kml.plot_rendering.plot_request()
    before = peri_scribe.kml.plot_rendering.plot_key(request)
    if setting == "layout":
        monkeypatch.setattr(svg_charts.time_series, "PAD_TOP", 40.0)
    elif setting == "font":
        monkeypatch.setattr(svg_charts.svg, "FONT_STACK", "Arial")
    elif setting == "metrics":
        monkeypatch.setitem(svg_charts.svg.HELVETICA_ADVANCES, "A", 123)
    elif setting == "locale":
        monkeypatch.setattr(
            peri_scribe.kml.plot_rendering.locale,
            "setlocale",
            lambda _kind: "changed",
        )
    else:
        monkeypatch.setenv("TZ", "UTC")
    assert before != peri_scribe.kml.plot_rendering.plot_key(request)


@pytest.mark.parametrize(
    "content",
    [
        b"invalid",
        b"<svg/>",
        b'<!DOCTYPE svg [<!ENTITY x "unsafe">]><svg>&x;</svg>',
    ],
)
def test_render_plot_request_replaces_malformed_svg_products(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    content: bytes,
) -> None:
    request = tests.helpers.factories.peri_scribe.kml.plot_rendering.plot_request()
    key = peri_scribe.kml.plot_rendering.plot_key(request)
    assert key is not None
    expected = svg_charts.time_series.draw_plot(
        request.series,
        y_axis_label=request.y_axis_label,
    )
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "test"):
        spatial_data.product_cache.put(
            peri_scribe.kml.plot_rendering.PLOT_NAMESPACE,
            key,
            content,
        )
        assert peri_scribe.kml.plot_rendering.render_plot_request(request).content == (
            expected
        )
        monkeypatch.setattr(
            svg_charts.time_series,
            "draw_plot",
            tests.helpers.doubles.errors.raising_stub(AssertionError("Unrepaired SVG")),
        )
        assert peri_scribe.kml.plot_rendering.render_plot_request(request).content == (
            expected
        )


def test_render_plot_request_unsupported_setting_preserves_uncached_rendering(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = tests.helpers.factories.peri_scribe.kml.plot_rendering.plot_request()
    expected = svg_charts.time_series.draw_plot(
        request.series,
        y_axis_label=request.y_axis_label,
    )
    monkeypatch.setattr(svg_charts.svg, "UNSUPPORTED", object(), raising=False)
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "test"):
        assert peri_scribe.kml.plot_rendering.render_plot_request(request).content == (
            expected
        )


def test_plot_image_bundles_preserves_callback_when_every_image_is_reused(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = tests.helpers.factories.peri_scribe.kml.plot_rendering.plot_request()
    plot = peri_scribe.kml.plot_data.FirePlot(
        filename_suffix=request.filename_suffix,
        y_axis_label=request.y_axis_label,
        series=request.series,
    )
    bundles = ((request.filename_prefix, (plot,)),)
    calls: list[str] = []
    callback = (
        tests.helpers.doubles.peri_scribe.kml.plot_rendering.make_pre_render_recorder(
            calls=calls,
        )
    )
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "test"):
        expected = peri_scribe.kml.plot_rendering.plot_image_bundles(bundles)
        monkeypatch.setattr(
            svg_charts.time_series,
            "draw_plot",
            tests.helpers.doubles.errors.raising_stub(
                AssertionError("Repeated drawing"),
            ),
        )
        actual = peri_scribe.kml.plot_rendering.plot_image_bundles(
            bundles,
            before_rendering=callback,
        )
    assert calls == ["before"]
    assert actual == expected
