from __future__ import annotations

import io
import json
import logging
import pathlib
import shutil
import typing

import geopandas
import structlog

import peri_scribe.models
import peri_scribe.output


if typing.TYPE_CHECKING:
    import pytest


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
    path = pathlib.Path("/data/2026/sources-complete")
    peri_scribe.output.remove_directory_tree(path)
    assert removed == [path]


def test_remove_directory_tree_leaves_missing_path_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    removed: list[pathlib.Path] = []
    monkeypatch.setattr(pathlib.Path, "is_dir", lambda _self: False)
    monkeypatch.setattr(shutil, "rmtree", removed.append)
    path = pathlib.Path("/data/2026/sources-complete")
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
