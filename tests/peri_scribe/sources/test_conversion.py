"""Tests for peri_scribe.sources.external_sources."""

from __future__ import annotations

import json
import pathlib
import tempfile

import geopandas
import geopandas.testing
import hypothesis
import hypothesis.strategies
import pandas as pd
import pytest
import shapely.geometry

import peri_scribe.models
import peri_scribe.sources.conversion
import tests.factories
import tests.geometry_strategies
import tests.peri_scribe.sources.conversion_helpers


# This test is slow, so limit examples to keep routine test runs fast.
@hypothesis.settings(max_examples=25)
@hypothesis.given(
    features=tests.peri_scribe.sources.conversion_helpers.feature_collections(),
    chunk_size=hypothesis.strategies.integers(1, 10),
)
def test_geojson_feature_chunks_preserves_features_across_chunk_boundaries(
    features: list[dict[str, object]],
    chunk_size: int,
) -> None:
    with tempfile.TemporaryDirectory() as temporary_directory:
        path = pathlib.Path(temporary_directory) / "features.geojson"
        path.write_text(
            json.dumps({"type": "FeatureCollection", "features": features}),
            encoding="utf-8",
        )
        chunks = list(
            peri_scribe.sources.conversion.geojson_feature_chunks(path, chunk_size),
        )
    assert all(0 < len(chunk) <= chunk_size for chunk in chunks)
    assert sum(len(chunk) for chunk in chunks) == len(features)
    if features:
        expected = geopandas.GeoDataFrame.from_features(
            features,
            crs=peri_scribe.models.WGS84_SPATIAL_REFERENCE_ID,
        )
        actual = pd.concat(chunks, ignore_index=True)
        assert isinstance(actual, geopandas.GeoDataFrame)
        pd.testing.assert_frame_equal(
            tests.peri_scribe.sources.conversion_helpers.comparable_attributes(actual),
            tests.peri_scribe.sources.conversion_helpers.comparable_attributes(
                expected,
            ),
            check_like=True,
        )
        geopandas.testing.assert_geoseries_equal(actual.geometry, expected.geometry)


@hypothesis.given(
    geometry=tests.geometry_strategies.footprints(),
    projected=...,
)
def test_centroid_dataframe_preserves_its_input(
    geometry: shapely.Polygon | shapely.MultiPolygon,
    *,
    projected: bool,
) -> None:
    frame = tests.factories.geo_frame({"name": ["River"]}, [geometry])
    if projected:
        frame = frame.to_crs(3857)
    original = frame.copy(deep=True)
    peri_scribe.sources.conversion.centroid_dataframe(frame)
    geopandas.testing.assert_geodataframe_equal(frame, original)


def test_centroid_dataframe_preserves_projected_polygon_input() -> None:
    polygon = shapely.Polygon([(0, 0), (0, 1), (1, 0)])
    frame = geopandas.GeoDataFrame(geometry=[polygon], crs=3857)
    result = peri_scribe.sources.conversion.centroid_dataframe(frame)
    assert frame.geometry.iloc[0].equals(polygon)
    assert result.geometry.iloc[0].equals(polygon.centroid)


def test_geojson_feature_chunks_streams_features_in_chunks(
    tmp_path: pathlib.Path,
) -> None:
    dataframe = tests.factories.geo_frame(
        {"OBJECTID": [1, 2, 3, 4, 5]},
        [shapely.geometry.Point(index, 0) for index in range(5)],
    )
    path = tmp_path / "features.geojson"
    dataframe.to_file(path, driver="GeoJSON")

    chunks = list(
        peri_scribe.sources.conversion.geojson_feature_chunks(path, chunk_size=2),
    )

    assert [len(chunk) for chunk in chunks] == [2, 2, 1]
    assert [chunk.iloc[0]["OBJECTID"] for chunk in chunks] == [1, 3, 5]
    assert all(
        chunk.crs.to_epsg() == peri_scribe.models.WGS84_SPATIAL_REFERENCE_ID
        for chunk in chunks
    )


def test_geojson_feature_chunks_keeps_missing_geometry(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "features.geojson"
    path.write_text(
        json.dumps({
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature", "properties": {"OBJECTID": 1}, "geometry": None},
            ],
        }),
    )

    chunks = list(
        peri_scribe.sources.conversion.geojson_feature_chunks(path, chunk_size=2),
    )

    assert len(chunks) == 1
    assert chunks[0].geometry.iloc[0] is None


def test_geojson_chunk_dataframe_unions_property_columns() -> None:
    frame = peri_scribe.sources.conversion.geojson_chunk_dataframe(
        [shapely.geometry.Point(0.0, 0.0), shapely.geometry.Point(1.0, 1.0)],
        [{"a": 1}, {"b": 2}],
    )

    assert list(frame.columns) == ["a", "b", "geometry"]
    assert frame.iloc[0]["a"] == pytest.approx(1)
    assert bool(pd.isna(frame.iloc[1]["a"]))


def test_geodata_chunks_reads_non_geojson_in_chunks(tmp_path: pathlib.Path) -> None:
    dataframe = tests.factories.geo_frame(
        {"a": [1, 2, 3]},
        [shapely.geometry.Point(index, 0) for index in range(3)],
    )
    path = tmp_path / "features.gpkg"
    dataframe.to_file(path, layer="features")

    chunks = list(peri_scribe.sources.conversion.geodata_chunks(path, chunk_size=2))

    assert [len(chunk) for chunk in chunks] == [2, 1]
    assert [chunk.iloc[0]["a"] for chunk in chunks] == [1, 3]


def test_convert_to_geopackage_streams_centroids_in_chunks(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(peri_scribe.sources.conversion, "CONVERSION_CHUNK_SIZE", 2)
    dataframe = tests.factories.geo_frame(
        {"OBJECTID": [1, 2, 3, 4, 5]},
        [
            shapely.geometry.box(index, index, index + 1, index + 1)
            for index in range(5)
        ],
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
    assert sorted(converted.geometry.x) == pytest.approx([0.5, 1.5, 2.5, 3.5, 4.5])


def test_convert_to_geopackage_keeps_attributes_across_chunks(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(peri_scribe.sources.conversion, "CONVERSION_CHUNK_SIZE", 2)
    dataframe = tests.factories.geo_frame(
        {"OBJECTID": [1, 2, 3]},
        [
            shapely.geometry.box(index, index, index + 1, index + 1)
            for index in range(3)
        ],
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
    geodata_path.write_text(json.dumps({"type": "FeatureCollection", "features": []}))
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
