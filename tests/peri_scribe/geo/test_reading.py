"""Tests for peri_scribe.geo.package."""

from __future__ import annotations

import pathlib
import typing

import geopandas
import shapely.geometry

import peri_scribe.geo.package
import peri_scribe.geo.reading
import peri_scribe.sources.feed_types
from tests.conftest import SAMPLE_FEED_NAME


if typing.TYPE_CHECKING:
    import pytest


def test_read_layer_reads_named_layer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame = geopandas.GeoDataFrame(
        {"fire_name": ["Bug"]},
        geometry=[shapely.geometry.Point(0, 0)],
        crs="EPSG:4326",
    )
    calls: list[tuple[pathlib.Path, str]] = []

    def read_file(read_path: pathlib.Path, *, layer: str) -> geopandas.GeoDataFrame:
        calls.append((read_path, layer))
        return frame

    monkeypatch.setattr(
        peri_scribe.geo.package.geopandas,
        "read_file",
        read_file,
    )
    path = pathlib.Path("/derived/full.gpkg")
    assert peri_scribe.geo.reading.read_layer(path, "perimeter_history") is frame
    assert calls == [(path, "perimeter_history")]


def test_read_layer_chunks_yields_bounded_chunks(
    tmp_path: pathlib.Path,
) -> None:
    dataframe = geopandas.GeoDataFrame(
        {"a": [1, 2, 3, 4, 5]},
        geometry=[shapely.geometry.Point(index, 0) for index in range(5)],
        crs="EPSG:4326",
    )
    path = tmp_path / "layer.gpkg"
    dataframe.to_file(path, layer="features")

    chunks = list(
        peri_scribe.geo.reading.read_layer_chunks(
            path,
            "features",
            chunk_size=2,
        ),
    )

    assert [len(chunk) for chunk in chunks] == [2, 2, 1]
    assert [chunk.iloc[0]["a"] for chunk in chunks] == [1, 3, 5]


def test_read_layer_chunks_reads_default_layer_without_name(
    tmp_path: pathlib.Path,
) -> None:
    dataframe = geopandas.GeoDataFrame(
        {"a": [1, 2, 3]},
        geometry=[shapely.geometry.Point(index, 0) for index in range(3)],
        crs="EPSG:4326",
    )
    path = tmp_path / "layer.gpkg"
    dataframe.to_file(path, layer="features")

    chunks = list(
        peri_scribe.geo.reading.read_layer_chunks(
            path,
            None,
            chunk_size=2,
        ),
    )

    assert [len(chunk) for chunk in chunks] == [2, 1]


def test_read_layer_chunks_yields_nothing_for_empty_layer(
    tmp_path: pathlib.Path,
) -> None:
    dataframe = geopandas.GeoDataFrame(geometry=[], crs="EPSG:4326")
    path = tmp_path / "layer.gpkg"
    dataframe.to_file(path, layer="features")

    chunks = list(
        peri_scribe.geo.reading.read_layer_chunks(
            path,
            "features",
            chunk_size=2,
        ),
    )

    assert chunks == []


def test_read_layer_dataframe_reads_feed_layer(
    monkeypatch: pytest.MonkeyPatch,
    feed: peri_scribe.sources.feed_types.Feed,
) -> None:
    sentinel = object()
    calls: list[tuple[pathlib.Path, str]] = []
    monkeypatch.setattr(
        peri_scribe.geo.package.geopandas,
        "read_file",
        lambda path, layer: calls.append((path, layer)) or sentinel,
    )
    path = pathlib.Path("/fires.gpkg")
    assert peri_scribe.geo.reading.read_layer_dataframe(path, feed) is sentinel
    assert calls == [(path, SAMPLE_FEED_NAME)]
