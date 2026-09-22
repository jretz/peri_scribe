"""Verify serialized documents, GeoPackages, and score distribution plots."""

from __future__ import annotations

import json
import pathlib
import shutil
import typing

import structlog

import peri_scribe.logging
import peri_scribe.models
import peri_scribe.output
import svg_charts.distribution
import tests.helpers.doubles.errors
import tests.helpers.doubles.peri_scribe.output
import tests.helpers.factories.peri_scribe.output


if typing.TYPE_CHECKING:
    import pytest


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
    width = int(svg_charts.distribution.CCDF_CHART_WIDTH.magnitude)
    height = int(svg_charts.distribution.CCDF_CHART_HEIGHT.magnitude)
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
        svg_charts.distribution,
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
        svg_charts.distribution,
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
