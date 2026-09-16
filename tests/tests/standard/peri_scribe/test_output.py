"""Verify serialized documents, GeoPackages, and score distribution plots."""

from __future__ import annotations

import json
import pathlib
import shutil
import typing

import pytest
import structlog

import peri_scribe.logging
import peri_scribe.models
import peri_scribe.output
import tests.helpers.doubles.errors
import tests.helpers.doubles.peri_scribe.output
import tests.helpers.factories.peri_scribe.output


def test_write_geopackage_writes_every_layer(
    monkeypatch: pytest.MonkeyPatch,
    layer_data_factory: typing.Callable[[str], peri_scribe.models.LayerData],
) -> None:
    path = pathlib.Path("/out.gpkg")
    calls = tests.helpers.doubles.peri_scribe.output.stub_to_file(monkeypatch)
    monkeypatch.setattr(pathlib.Path, "exists", lambda _self: False)
    with structlog.testing.capture_logs() as captured:
        peri_scribe.output.write_geopackage(
            path,
            [layer_data_factory("first_layer"), layer_data_factory("second_layer")],
        )
    assert calls == [
        (path, "GPKG", "first_layer", "w"),
        (path, "GPKG", "second_layer", "a"),
    ]
    assert [event["event"] for event in captured] == ["Wrote layer", "Wrote layer"]
    assert [event["layer"] for event in captured] == ["first_layer", "second_layer"]


def test_write_geopackage_replaces_existing_file(
    monkeypatch: pytest.MonkeyPatch,
    layer_data_factory: typing.Callable[[str], peri_scribe.models.LayerData],
) -> None:
    path = pathlib.Path("/out.gpkg")
    unlinked: list[pathlib.Path] = []
    calls = tests.helpers.doubles.peri_scribe.output.stub_to_file(monkeypatch)
    monkeypatch.setattr(pathlib.Path, "exists", lambda _self: True)

    fake_unlink = tests.helpers.doubles.peri_scribe.output.make_unlink_recorder(
        unlinked=unlinked,
    )

    monkeypatch.setattr(pathlib.Path, "unlink", fake_unlink)
    with structlog.testing.capture_logs() as captured:
        peri_scribe.output.write_geopackage(
            path,
            [layer_data_factory("replacement_layer")],
        )
    assert "Replaced existing" in [event["event"] for event in captured]
    assert unlinked == [path]
    assert calls == [(path, "GPKG", "replacement_layer", "w")]


def test_remove_directory_tree_removes_existing_directory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    removed: list[pathlib.Path] = []
    monkeypatch.setattr(pathlib.Path, "is_dir", lambda _self: True)
    monkeypatch.setattr(shutil, "rmtree", removed.append)
    path = pathlib.Path("/data/2026/validation")
    peri_scribe.output.remove_directory_tree(path)
    assert removed == [path]


def test_remove_directory_tree_leaves_missing_path_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    removed: list[pathlib.Path] = []
    monkeypatch.setattr(pathlib.Path, "is_dir", lambda _self: False)
    monkeypatch.setattr(shutil, "rmtree", removed.append)
    path = pathlib.Path("/data/2026/validation")
    peri_scribe.output.remove_directory_tree(path)
    assert removed == []


def test_write_document_writes_pretty_printed_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = pathlib.Path("/fires.json")
    document = peri_scribe.models.FireIndex.model_validate({
        "version": "2026-08-17",
        "fires": [{"name": "Park Fire", "status": "active", "paths": ["one.gpkg"]}],
    })
    files: list[tests.helpers.doubles.peri_scribe.output.RecordingFile] = []

    fake_open = tests.helpers.doubles.peri_scribe.output.make_recording_file_opener(
        files=files,
    )

    monkeypatch.setattr(pathlib.Path, "open", fake_open)
    with structlog.testing.capture_logs() as captured:
        peri_scribe.output.write_document(path, document)
    written = files[0].getvalue()
    assert json.loads(written) == document.model_dump()
    assert list(json.loads(written)) == ["version", "fires"]
    assert "\n    " in written
    assert captured[0]["event"] == "Wrote document"
    assert captured[0]["path"] == "fires.json"
    assert captured[0]["fires"] == 1


def test_curve_knees_finds_two_breakpoints() -> None:
    assert peri_scribe.output.curve_knees(
        [10] * 4 + [50] * 2 + [100, 200, 300, 500],
    ) == [(100, pytest.approx(0.3)), (300, pytest.approx(0.1))]


def test_curve_knees_returns_empty_without_a_bend() -> None:
    assert peri_scribe.output.curve_knees([]) == []
    assert peri_scribe.output.curve_knees([5, 5, 5]) == []
    assert peri_scribe.output.curve_knees([10, 20]) == []
    assert (
        peri_scribe.output.curve_knees(
            [10] * 20 + [50] * 5 + [100] * 3 + [200] * 2 + [500],
        )
        == []
    )


def test_curve_knees_selects_the_best_fit_among_multiple_candidates() -> None:
    assert peri_scribe.output.curve_knees(list(range(1, 11))) == [
        (6, pytest.approx(0.4)),
        (8, pytest.approx(0.2)),
    ]


def test_write_fire_scores_ccdf_writes_an_html_page(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "fire_scores_ccdf.html"
    with structlog.testing.capture_logs() as captured:
        peri_scribe.output.write_fire_scores_ccdf(
            path,
            tests.helpers.factories.peri_scribe.output.fire_scores_document([12]),
        )
    written = path.read_text(encoding="utf-8")
    assert written.startswith("<!DOCTYPE html>")
    assert "<svg" in written
    assert "src=" not in written
    assert captured[0]["event"] == "Wrote fire scores ccdf"
    assert captured[0]["path"] == "fire_scores_ccdf.html"


def test_ccdf_svg_uses_the_configured_chart_size() -> None:
    svg = peri_scribe.output.ccdf_svg(
        tests.helpers.factories.peri_scribe.output.fire_scores_document([12]),
    )
    width = int(peri_scribe.output.CCDF_CHART_WIDTH.magnitude)
    height = int(peri_scribe.output.CCDF_CHART_HEIGHT.magnitude)
    assert f'width="{width}"' in svg
    assert f'height="{height}"' in svg


def test_ccdf_svg_plots_the_complementary_share() -> None:
    svg = peri_scribe.output.ccdf_svg(
        tests.helpers.factories.peri_scribe.output.fire_scores_document([12, 12, 40]),
    )
    assert "<path" in svg
    assert "Complementary CDF" in svg
    assert ">Score<" in svg


def test_ccdf_svg_labels_the_curve_knees() -> None:
    svg = peri_scribe.output.ccdf_svg(
        tests.helpers.factories.peri_scribe.output.fire_scores_document(
            [10] * 4 + [50] * 2 + [100, 200, 300, 500],
        ),
    )
    assert "score 100" in svg
    assert "percentile 70.0" in svg
    assert "score 300" in svg
    assert "percentile 90.0" in svg


def test_ccdf_svg_still_draws_when_knees_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        peri_scribe.output,
        "curve_knees",
        tests.helpers.doubles.errors.raising_stub(RuntimeError("knee failure")),
    )
    with structlog.testing.capture_logs(
        processors=[structlog.processors.format_exc_info],
    ) as captured:
        svg = peri_scribe.output.ccdf_svg(
            tests.helpers.factories.peri_scribe.output.fire_scores_document([12]),
        )
    assert "<svg" in svg
    assert captured[0]["event"] == "Skipped fire scores knee labels"
    assert "RuntimeError: knee failure" in captured[0]["exception"]
    assert json.loads(json.dumps(captured)) == captured


def test_ccdf_svg_preserves_tracebacks_with_json_logging(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        peri_scribe.output,
        "curve_knees",
        tests.helpers.doubles.errors.raising_stub(RuntimeError("knee failure")),
    )
    peri_scribe.logging.configure_logging("info")
    structlog.configure(
        processors=[
            *structlog.get_config()["processors"][:-1],
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(default=None, allow_nan=False),
        ],
    )
    svg = peri_scribe.output.ccdf_svg(
        tests.helpers.factories.peri_scribe.output.fire_scores_document([12]),
    )
    captured = capsys.readouterr()
    entry = json.loads(captured.err)
    assert "<svg" in svg
    assert captured.out == ""
    assert entry["level"] == "error"
    assert entry["event"] == "Skipped fire scores knee labels"
    assert "Traceback (most recent call last)" in entry["exception"]
    assert "RuntimeError: knee failure" in entry["exception"]


def test_ccdf_svg_draws_an_empty_chart_without_scores() -> None:
    svg = peri_scribe.output.ccdf_svg(
        tests.helpers.factories.peri_scribe.output.fire_scores_document([]),
    )
    assert "<svg" in svg
    assert "<path" not in svg
