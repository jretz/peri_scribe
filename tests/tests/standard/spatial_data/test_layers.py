"""Exercise reusable spatial layer operations."""

from __future__ import annotations

import pathlib
import typing

import geopandas
import shapely.geometry
import structlog

import spatial_data.layers
import tests.helpers.doubles.spatial_data.layers
import tests.helpers.factories.geography
import tests.helpers.factories.spatial_data.layers


if typing.TYPE_CHECKING:
    import pytest


def test_read_layer_reads_named_layer(monkeypatch: pytest.MonkeyPatch) -> None:
    frame = tests.helpers.factories.geography.geo_frame(
        {"station_name": ["Spring"]},
        [shapely.geometry.Point(0, 0)],
    )
    calls: list[tuple[pathlib.Path, str]] = []

    read_file = tests.helpers.doubles.spatial_data.layers.make_recording_layer_reader(
        calls=calls,
        frame=frame,
    )

    monkeypatch.setattr(spatial_data.layers.geopandas, "read_file", read_file)
    path = pathlib.Path("/derived/full.gpkg")
    assert spatial_data.layers.read_layer(path, "stations") is frame
    assert calls == [(path, "stations")]


def test_read_layer_chunks_yields_bounded_chunks(tmp_path: pathlib.Path) -> None:
    dataframe = tests.helpers.factories.geography.geo_frame(
        {"a": [1, 2, 3, 4, 5]},
        [shapely.geometry.Point(index, 0) for index in range(5)],
    )
    path = tmp_path / "layer.gpkg"
    dataframe.to_file(path, layer="features")

    chunks = list(
        spatial_data.layers.read_layer_chunks(path, "features", chunk_size=2),
    )

    assert [len(chunk) for chunk in chunks] == [2, 2, 1]
    assert [chunk.iloc[0]["a"] for chunk in chunks] == [1, 3, 5]


def test_read_layer_chunks_limits_rows_when_feature_ids_have_gaps(
    tmp_path: pathlib.Path,
) -> None:
    path = tmp_path / "layer.gpkg"
    tests.helpers.factories.spatial_data.layers.write_sparse_layer(path, [1, 3, 4])
    chunks = list(spatial_data.layers.read_layer_chunks(path, "features", 2))
    assert [chunk["value"].tolist() for chunk in chunks] == [[1, 3], [4]]


def test_read_layer_chunks_reads_default_layer_without_name(
    tmp_path: pathlib.Path,
) -> None:
    dataframe = tests.helpers.factories.geography.geo_frame(
        {"a": [1, 2, 3]},
        [shapely.geometry.Point(index, 0) for index in range(3)],
    )
    path = tmp_path / "layer.gpkg"
    dataframe.to_file(path, layer="features")

    chunks = list(spatial_data.layers.read_layer_chunks(path, None, chunk_size=2))

    assert [len(chunk) for chunk in chunks] == [2, 1]


def test_read_layer_chunks_yields_nothing_for_empty_layer(
    tmp_path: pathlib.Path,
) -> None:
    dataframe = geopandas.GeoDataFrame(geometry=[], crs="EPSG:4326")
    path = tmp_path / "layer.gpkg"
    dataframe.to_file(path, layer="features")

    chunks = list(
        spatial_data.layers.read_layer_chunks(path, "features", chunk_size=2),
    )

    assert chunks == []


def test_write_geopackage_writes_every_layer(
    monkeypatch: pytest.MonkeyPatch,
    layer_data_factory: typing.Callable[[str], spatial_data.layers.LayerData],
) -> None:
    path = pathlib.Path("/out.gpkg")
    calls = tests.helpers.doubles.spatial_data.layers.stub_to_file(monkeypatch)
    monkeypatch.setattr(pathlib.Path, "exists", lambda _self: False)
    with structlog.testing.capture_logs() as captured:
        spatial_data.layers.write_geopackage(
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
    layer_data_factory: typing.Callable[[str], spatial_data.layers.LayerData],
) -> None:
    path = pathlib.Path("/out.gpkg")
    unlinked: list[pathlib.Path] = []
    calls = tests.helpers.doubles.spatial_data.layers.stub_to_file(monkeypatch)
    monkeypatch.setattr(pathlib.Path, "exists", lambda _self: True)

    fake_unlink = tests.helpers.doubles.spatial_data.layers.make_unlink_recorder(
        unlinked=unlinked,
    )

    monkeypatch.setattr(pathlib.Path, "unlink", fake_unlink)
    with structlog.testing.capture_logs() as captured:
        spatial_data.layers.write_geopackage(
            path,
            [layer_data_factory("replacement_layer")],
        )
    assert "Replaced existing" in [event["event"] for event in captured]
    assert unlinked == [path]
    assert calls == [(path, "GPKG", "replacement_layer", "w")]
