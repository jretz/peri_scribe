"""Tests for peri_scribe.sources.external_sources."""

from __future__ import annotations

import json
import pathlib

import geopandas
import pandas as pd
import pytest
import shapely.geometry

import peri_scribe.models
import peri_scribe.sources.conversion


def test_geojson_feature_chunks_streams_features_in_chunks(
    tmp_path: pathlib.Path,
) -> None:
    dataframe = geopandas.GeoDataFrame(
        {"OBJECTID": [1, 2, 3, 4, 5]},
        geometry=[shapely.geometry.Point(index, 0) for index in range(5)],
        crs="EPSG:4326",
    )
    path = tmp_path / "features.geojson"
    dataframe.to_file(path, driver="GeoJSON")

    chunks = list(
        peri_scribe.sources.conversion.geojson_feature_chunks(
            path,
            chunk_size=2,
        ),
    )

    assert [len(chunk) for chunk in chunks] == [2, 2, 1]
    assert [chunk.iloc[0]["OBJECTID"] for chunk in chunks] == [1, 3, 5]
    assert all(
        chunk.crs.to_epsg() == peri_scribe.models.WGS84_SPATIAL_REFERENCE_ID
        for chunk in chunks
    )


def test_geojson_feature_chunks_keeps_missing_geometry(
    tmp_path: pathlib.Path,
) -> None:
    path = tmp_path / "features.geojson"
    path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"OBJECTID": 1},
                        "geometry": None,
                    },
                ],
            },
        ),
    )

    chunks = list(
        peri_scribe.sources.conversion.geojson_feature_chunks(
            path,
            chunk_size=2,
        ),
    )

    assert len(chunks) == 1
    assert chunks[0].geometry.iloc[0] is None


def test_geojson_chunk_dataframe_unions_property_columns() -> None:
    frame = peri_scribe.sources.conversion.geojson_chunk_dataframe(
        [
            shapely.geometry.Point(0.0, 0.0),
            shapely.geometry.Point(1.0, 1.0),
        ],
        [{"a": 1}, {"b": 2}],
    )

    assert list(frame.columns) == ["a", "b", "geometry"]
    assert frame.iloc[0]["a"] == pytest.approx(1)
    assert bool(pd.isna(frame.iloc[1]["a"]))


def test_geodata_chunks_reads_non_geojson_in_chunks(
    tmp_path: pathlib.Path,
) -> None:
    dataframe = geopandas.GeoDataFrame(
        {"a": [1, 2, 3]},
        geometry=[shapely.geometry.Point(index, 0) for index in range(3)],
        crs="EPSG:4326",
    )
    path = tmp_path / "features.gpkg"
    dataframe.to_file(path, layer="features")

    chunks = list(
        peri_scribe.sources.conversion.geodata_chunks(
            path,
            chunk_size=2,
        ),
    )

    assert [len(chunk) for chunk in chunks] == [2, 1]
    assert [chunk.iloc[0]["a"] for chunk in chunks] == [1, 3]


def test_convert_to_geopackage_streams_centroids_in_chunks(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        peri_scribe.sources.conversion,
        "CONVERSION_CHUNK_SIZE",
        2,
    )
    dataframe = geopandas.GeoDataFrame(
        {"OBJECTID": [1, 2, 3, 4, 5]},
        geometry=[
            shapely.geometry.box(index, index, index + 1, index + 1)
            for index in range(5)
        ],
        crs="EPSG:4326",
    )
    geodata_path = tmp_path / "California.geojson"
    dataframe.to_file(geodata_path, driver="GeoJSON")
    output = tmp_path / "buildings.gpkg"

    peri_scribe.sources.conversion.convert_to_geopackage(
        geodata_path,
        output,
        "buildings",
        centroids=True,
        keep_attributes=False,
    )

    converted = geopandas.read_file(output, layer="buildings")
    assert list(converted.columns) == ["geometry"]
    assert list(converted.geometry.geom_type) == ["Point"] * 5
    assert sorted(converted.geometry.x) == pytest.approx(
        [0.5, 1.5, 2.5, 3.5, 4.5],
    )


def test_convert_to_geopackage_keeps_attributes_across_chunks(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        peri_scribe.sources.conversion,
        "CONVERSION_CHUNK_SIZE",
        2,
    )
    dataframe = geopandas.GeoDataFrame(
        {"OBJECTID": [1, 2, 3]},
        geometry=[
            shapely.geometry.box(index, index, index + 1, index + 1)
            for index in range(3)
        ],
        crs="EPSG:4326",
    )
    geodata_path = tmp_path / "California.geojson"
    dataframe.to_file(geodata_path, driver="GeoJSON")
    output = tmp_path / "out.gpkg"

    peri_scribe.sources.conversion.convert_to_geopackage(
        geodata_path,
        output,
        "out",
        centroids=False,
        keep_attributes=True,
    )

    converted = geopandas.read_file(output, layer="out")
    assert list(converted["OBJECTID"]) == [1, 2, 3]
    assert list(converted.geometry.geom_type) == ["Polygon"] * 3


def test_convert_to_geopackage_writes_empty_layer_for_empty_source(
    tmp_path: pathlib.Path,
) -> None:
    geodata_path = tmp_path / "empty.geojson"
    geodata_path.write_text(
        json.dumps({"type": "FeatureCollection", "features": []}),
    )
    output = tmp_path / "buildings.gpkg"

    peri_scribe.sources.conversion.convert_to_geopackage(
        geodata_path,
        output,
        "buildings",
        centroids=True,
        keep_attributes=False,
    )

    assert output.is_file()
    assert geopandas.read_file(output, layer="buildings").empty
