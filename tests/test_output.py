from __future__ import annotations

import logging
import pathlib
import typing

import geopandas
import structlog

import peri_scribe.models
import peri_scribe.output


if typing.TYPE_CHECKING:
    import pytest


def test_write_geopackage_writes_every_layer(
    monkeypatch: pytest.MonkeyPatch,
    layer_data_factory: typing.Callable[[str], peri_scribe.models.LayerData],
) -> None:
    path = pathlib.Path("/out.gpkg")
    calls: list[tuple[pathlib.Path, str, str, str]] = []
    monkeypatch.setattr(pathlib.Path, "exists", lambda _self: False)
    monkeypatch.setattr(
        geopandas.GeoDataFrame,
        "to_file",
        lambda _self, path, driver, layer, mode: calls.append(
            (path, driver, layer, mode),
        ),
    )
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
    calls: list[tuple[pathlib.Path, str, str, str]] = []
    monkeypatch.setattr(pathlib.Path, "exists", lambda _self: True)

    def fake_unlink(_self: pathlib.Path) -> None:
        unlinked.append(_self)

    monkeypatch.setattr(pathlib.Path, "unlink", fake_unlink)
    monkeypatch.setattr(
        geopandas.GeoDataFrame,
        "to_file",
        lambda _self, path, driver, layer, mode: calls.append(
            (path, driver, layer, mode),
        ),
    )
    with structlog.testing.capture_logs() as captured:
        peri_scribe.output.write_geopackage(
            path,
            [layer_data_factory("replacement_layer")],
        )
    assert "Replaced existing" in [event["event"] for event in captured]
    assert unlinked == [path]
    assert calls == [(path, "GPKG", "replacement_layer", "w")]


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
