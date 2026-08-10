import logging
import pathlib
import typing

import geopandas
import structlog

import peri_scribe.models
import peri_scribe.output


def test_write_geopackage_writes_every_layer(
    tmp_path: pathlib.Path,
    layer_data_factory: typing.Callable[[str], peri_scribe.models.LayerData],
) -> None:
    path = tmp_path / "out.gpkg"
    peri_scribe.output.write_geopackage(
        path,
        [
            layer_data_factory("first_layer"),
            layer_data_factory("second_layer"),
        ],
    )
    first = geopandas.read_file(path, layer="first_layer")
    second = geopandas.read_file(path, layer="second_layer")
    assert list(first["name"]) == ["a", "b"]
    assert list(second["name"]) == ["a", "b"]


def test_write_geopackage_replaces_existing_file(
    tmp_path: pathlib.Path,
    layer_data_factory: typing.Callable[[str], peri_scribe.models.LayerData],
) -> None:
    path = tmp_path / "out.gpkg"
    path.write_bytes(b"not a geopackage")
    with structlog.testing.capture_logs() as captured:
        peri_scribe.output.write_geopackage(
            path,
            [layer_data_factory("replacement_layer")],
        )
    assert "Replaced existing" in [event["event"] for event in captured]
    written = geopandas.read_file(path, layer="replacement_layer")
    assert list(written["name"]) == ["a", "b"]


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
