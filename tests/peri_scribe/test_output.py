from __future__ import annotations

import io
import json
import logging
import pathlib
import shutil
import typing

import geopandas
import matplotlib.axes
import matplotlib.figure
import matplotlib.image
import pytest
import seaborn as sns
import structlog

import peri_scribe.models
import peri_scribe.output


class RecordingFile:
    """In-memory file stand-in that keeps its contents after being closed."""

    def __init__(self) -> None:
        self.stream = io.StringIO()

    def write(self, text: str) -> int:
        return self.stream.write(text)

    def getvalue(self) -> str:
        return self.stream.getvalue()

    def __enter__(self) -> typing.Self:
        return self

    def __exit__(
        self,
        _exc_type: object,
        _exc_value: object,
        _traceback: object,
    ) -> None:
        return None


def stub_to_file(
    monkeypatch: pytest.MonkeyPatch,
) -> list[tuple[pathlib.Path, str, str, str]]:
    """Record GeoDataFrame.to_file calls.

    Args:
        monkeypatch: The monkeypatch fixture.

    Returns:
        The recorded (path, driver, layer, mode) calls.
    """
    calls: list[tuple[pathlib.Path, str, str, str]] = []
    monkeypatch.setattr(
        geopandas.GeoDataFrame,
        "to_file",
        lambda _self, path, driver, layer, mode: calls.append(
            (path, driver, layer, mode),
        ),
    )
    return calls


def test_write_geopackage_writes_every_layer(
    monkeypatch: pytest.MonkeyPatch,
    layer_data_factory: typing.Callable[[str], peri_scribe.models.LayerData],
) -> None:
    path = pathlib.Path("/out.gpkg")
    calls = stub_to_file(monkeypatch)
    monkeypatch.setattr(pathlib.Path, "exists", lambda _self: False)
    with structlog.testing.capture_logs() as captured:
        peri_scribe.output.write_geopackage(
            path,
            [
                layer_data_factory("first_layer"),
                layer_data_factory("second_layer"),
            ],
        )
    assert calls == [
        (path, "GPKG", "first_layer", "w"),
        (path, "GPKG", "second_layer", "a"),
    ]
    assert [event["event"] for event in captured] == [
        "Wrote layer",
        "Wrote layer",
    ]
    assert [event["layer"] for event in captured] == [
        "first_layer",
        "second_layer",
    ]


def test_write_geopackage_replaces_existing_file(
    monkeypatch: pytest.MonkeyPatch,
    layer_data_factory: typing.Callable[[str], peri_scribe.models.LayerData],
) -> None:
    path = pathlib.Path("/out.gpkg")
    unlinked: list[pathlib.Path] = []
    calls = stub_to_file(monkeypatch)
    monkeypatch.setattr(pathlib.Path, "exists", lambda _self: True)

    def fake_unlink(_self: pathlib.Path) -> None:
        unlinked.append(_self)

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


def test_configure_logging_filters_below_configured_level() -> None:
    with structlog.testing.capture_logs():
        peri_scribe.output.configure_logging("warning")
        logger = structlog.get_logger()
        assert not logger.is_enabled_for(logging.DEBUG)
        assert not logger.is_enabled_for(logging.INFO)
        assert logger.is_enabled_for(logging.WARNING)
        assert logger.is_enabled_for(logging.ERROR)


def test_configure_logging_debug_level_enables_every_level() -> None:
    with structlog.testing.capture_logs():
        peri_scribe.output.configure_logging("debug")
        logger = structlog.get_logger()
        assert logger.is_enabled_for(logging.DEBUG)
        assert logger.is_enabled_for(logging.CRITICAL)


def test_write_fire_index_writes_pretty_printed_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = pathlib.Path("/fires.json")
    document = peri_scribe.models.FireIndex.model_validate({
        "version": "2026-08-17",
        "fires": [
            {
                "name": "Park Fire",
                "status": "active",
                "paths": ["one.gpkg"],
            },
        ],
    })
    files: list[RecordingFile] = []

    def fake_open(
        _self: pathlib.Path,
        mode: str,
        encoding: str,
    ) -> RecordingFile:
        assert mode == "w"
        assert encoding == "utf-8"
        file = RecordingFile()
        files.append(file)
        return file

    monkeypatch.setattr(pathlib.Path, "open", fake_open)
    with structlog.testing.capture_logs() as captured:
        peri_scribe.output.write_fire_index(path, document)
    written = files[0].getvalue()
    assert json.loads(written) == document.model_dump()
    assert list(json.loads(written)) == ["version", "fires"]
    assert "\n    " in written
    assert captured[0]["event"] == "Wrote fire index"
    assert captured[0]["path"] == "fires.json"
    assert captured[0]["fires"] == 1


def test_write_fire_scores_writes_pretty_printed_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = pathlib.Path("/fire_scores.json")
    document = peri_scribe.models.FireScores.model_validate({
        "version": "2026-08-28",
        "fires": [
            {
                "name": "Park Fire",
                "identifier": "2026-x",
                "score": 12,
                "components": {
                    "size": 5,
                    "growth": 4,
                    "first_mapping": 0,
                    "buildings": 0,
                    "evacuation": 3,
                    "importance": 0,
                },
                "explanation": "Overlap with an evacuation zone.",
            },
        ],
    })
    files: list[RecordingFile] = []

    def fake_open(
        _self: pathlib.Path,
        mode: str,
        encoding: str,
    ) -> RecordingFile:
        assert mode == "w"
        assert encoding == "utf-8"
        file = RecordingFile()
        files.append(file)
        return file

    monkeypatch.setattr(pathlib.Path, "open", fake_open)
    with structlog.testing.capture_logs() as captured:
        peri_scribe.output.write_fire_scores(path, document)
    written = files[0].getvalue()
    assert json.loads(written) == document.model_dump()
    assert list(json.loads(written)) == ["version", "fires"]
    assert "\n    " in written
    assert captured[0]["event"] == "Wrote fire scores"
    assert captured[0]["path"] == "fire_scores.json"
    assert captured[0]["fires"] == 1


def test_write_fire_scores_ccdf_plots_complementary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = pathlib.Path("/fire_scores_ccdf.png")
    document = peri_scribe.models.FireScores.model_validate({
        "version": "2026-08-28",
        "fires": [
            {
                "name": "Park Fire",
                "identifier": "2026-x",
                "score": 12,
                "components": {
                    "size": 5,
                    "growth": 4,
                    "first_mapping": 0,
                    "buildings": 0,
                    "evacuation": 3,
                    "importance": 0,
                },
                "explanation": "Overlap with an evacuation zone.",
            },
        ],
    })
    ecdfplot_calls: list[tuple[list[int], object, dict[str, object]]] = []
    monkeypatch.setattr(
        sns,
        "ecdfplot",
        lambda data, ax, **keywords: ecdfplot_calls.append(
            (list(data), ax, keywords),
        ),
    )
    yscale_calls: list[str] = []
    monkeypatch.setattr(
        matplotlib.axes.Axes,
        "set_yscale",
        lambda _self, value: yscale_calls.append(value),
    )
    saved: list[pathlib.Path] = []
    monkeypatch.setattr(
        matplotlib.figure.Figure,
        "savefig",
        lambda _self, figure_path: saved.append(figure_path),
    )
    with structlog.testing.capture_logs() as captured:
        peri_scribe.output.write_fire_scores_ccdf(path, document)
    assert len(ecdfplot_calls) == 1
    data, _axes, keywords = ecdfplot_calls[0]
    assert data == [12]
    assert keywords == {"complementary": True}
    assert yscale_calls == ["log"]
    assert saved == [path]
    assert captured[0]["event"] == "Wrote fire scores ccdf"
    assert captured[0]["path"] == "fire_scores_ccdf.png"


def test_write_fire_scores_ccdf_renders_at_requested_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = pathlib.Path("/fire_scores_ccdf.png")
    document = peri_scribe.models.FireScores.model_validate({
        "version": "2026-08-28",
        "fires": [
            {
                "name": "Park Fire",
                "identifier": "2026-x",
                "score": 12,
                "components": {
                    "size": 5,
                    "growth": 4,
                    "first_mapping": 0,
                    "buildings": 0,
                    "evacuation": 3,
                    "importance": 0,
                },
                "explanation": "Overlap with an evacuation zone.",
            },
        ],
    })
    monkeypatch.setattr(
        sns,
        "ecdfplot",
        lambda *arguments, **_keywords: arguments,
    )
    buffers: list[io.BytesIO] = []
    real_savefig = matplotlib.figure.Figure.savefig

    def save_to_buffer(
        figure: matplotlib.figure.Figure,
        _path: pathlib.Path,
    ) -> None:
        buffer = io.BytesIO()
        buffers.append(buffer)
        real_savefig(figure, buffer)

    monkeypatch.setattr(matplotlib.figure.Figure, "savefig", save_to_buffer)
    peri_scribe.output.write_fire_scores_ccdf(path, document)
    assert len(buffers) == 1
    buffers[0].seek(0)
    rendered = matplotlib.image.imread(buffers[0])
    assert rendered.shape[:2] == (768, 1024)


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


def test_write_fire_scores_ccdf_labels_knees(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = pathlib.Path("/fire_scores_ccdf.png")
    scores = [10] * 4 + [50] * 2 + [100, 200, 300, 500]
    document = peri_scribe.models.FireScores.model_validate({
        "version": "2026-08-28",
        "fires": [
            {
                "name": f"Fire {index}",
                "score": score,
                "components": {
                    "size": 0,
                    "growth": 0,
                    "first_mapping": 0,
                    "buildings": 0,
                    "evacuation": 0,
                    "importance": 0,
                },
                "explanation": "No notable size, growth, threat, or "
                "official-importance signals.",
            }
            for index, score in enumerate(scores)
        ],
    })
    monkeypatch.setattr(
        sns,
        "ecdfplot",
        lambda *arguments, **_keywords: arguments,
    )
    monkeypatch.setattr(
        matplotlib.figure.Figure,
        "savefig",
        lambda _self, _figure_path: None,
    )
    annotations: list[tuple[float, float, str]] = []
    monkeypatch.setattr(
        matplotlib.axes.Axes,
        "annotate",
        lambda _self, text, xy, **_keywords: annotations.append(
            (xy[0], xy[1], text),
        ),
    )
    peri_scribe.output.write_fire_scores_ccdf(path, document)
    assert annotations == [
        (100, pytest.approx(0.3), "score 100\npercentile 70.0"),
        (300, pytest.approx(0.1), "score 300\npercentile 90.0"),
    ]


def test_write_fire_scores_ccdf_draws_plot_when_knees_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = pathlib.Path("/fire_scores_ccdf.png")
    document = peri_scribe.models.FireScores.model_validate({
        "version": "2026-08-28",
        "fires": [
            {
                "name": "Park Fire",
                "identifier": "2026-x",
                "score": 12,
                "components": {
                    "size": 5,
                    "growth": 4,
                    "first_mapping": 0,
                    "buildings": 0,
                    "evacuation": 3,
                    "importance": 0,
                },
                "explanation": "Overlap with an evacuation zone.",
            },
        ],
    })

    def failing_knees(_scores: list[int]) -> list[tuple[int, float]]:
        message = "knee failure"
        raise RuntimeError(message)

    monkeypatch.setattr(peri_scribe.output, "curve_knees", failing_knees)
    monkeypatch.setattr(
        sns,
        "ecdfplot",
        lambda *arguments, **_keywords: arguments,
    )
    saved: list[pathlib.Path] = []
    monkeypatch.setattr(
        matplotlib.figure.Figure,
        "savefig",
        lambda _self, figure_path: saved.append(figure_path),
    )
    with structlog.testing.capture_logs() as captured:
        peri_scribe.output.write_fire_scores_ccdf(path, document)
    assert saved == [path]
    assert captured[0]["event"] == "Skipped fire scores knee labels"
