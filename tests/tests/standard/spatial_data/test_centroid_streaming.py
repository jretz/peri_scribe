"""Tests for spatial_data.centroid_streaming."""

from __future__ import annotations

import json
import pathlib

import geopandas
import pytest

import spatial_data.centroid_streaming
import spatial_data.exceptions
import spatial_data.reference
import tests.helpers.factories.spatial_data.centroid_streaming
import tests.helpers.reference.spatial_data.centroid_streaming


def test_collect_geometry_chunk_returns_none_at_end() -> None:
    chunk = spatial_data.centroid_streaming.collect_geometry_chunk(
        iter([]),
        10,
        10,
    )
    assert chunk is None


def test_collect_geometry_chunk_collects_rings() -> None:
    chunk = spatial_data.centroid_streaming.collect_geometry_chunk(
        tests.helpers.factories.spatial_data.centroid_streaming.geometry_features([
            tests.helpers.factories.spatial_data.centroid_streaming.SQUARE,
            tests.helpers.factories.spatial_data.centroid_streaming.SQUARE_WITH_HOLE,
            tests.helpers.factories.spatial_data.centroid_streaming.MULTIPOLYGON,
        ]),
        10,
        100,
    )
    assert chunk is not None
    # 5 points for the square, 5 + 5 for the square with a hole, and 5 + 5 for the
    # multipolygon's two parts.
    assert chunk.coordinates.shape == (25, 2)
    assert chunk.ring_bounds.tolist() == [[0, 5], [5, 10], [10, 15], [15, 20], [20, 25]]
    # Each polygon's rings are one part; the multipolygon's two parts each hold one.
    assert chunk.ring_parts.tolist() == [0, 1, 1, 2, 3]
    assert chunk.part_counts.tolist() == [1, 1, 2]


def test_collect_geometry_chunk_stops_at_feature_limit() -> None:
    chunk = spatial_data.centroid_streaming.collect_geometry_chunk(
        tests.helpers.factories.spatial_data.centroid_streaming.geometry_features([
            tests.helpers.factories.spatial_data.centroid_streaming.SQUARE,
            tests.helpers.factories.spatial_data.centroid_streaming.SQUARE,
            tests.helpers.factories.spatial_data.centroid_streaming.SQUARE,
        ]),
        2,
        100,
    )
    assert chunk is not None
    assert chunk.part_counts.tolist() == [1, 1]


def test_collect_geometry_chunk_stops_at_vertex_limit() -> None:
    chunk = spatial_data.centroid_streaming.collect_geometry_chunk(
        tests.helpers.factories.spatial_data.centroid_streaming.geometry_features([
            tests.helpers.factories.spatial_data.centroid_streaming.SQUARE,
            tests.helpers.factories.spatial_data.centroid_streaming.SQUARE,
        ]),
        10,
        8,
    )
    assert chunk is not None
    # The vertex limit is checked after a feature is collected, so the chunk may exceed
    # it by one feature's vertices.
    assert chunk.part_counts.tolist() == [1, 1]
    assert chunk.coordinates.shape == (10, 2)


def test_collect_geometry_chunk_skips_non_polygon_geometry() -> None:
    point: dict[str, object] = {"type": "Point", "coordinates": [0, 0]}
    chunk = spatial_data.centroid_streaming.collect_geometry_chunk(
        tests.helpers.factories.spatial_data.centroid_streaming.geometry_features([
            point,
            tests.helpers.factories.spatial_data.centroid_streaming.SQUARE,
        ]),
        10,
        100,
    )
    assert chunk is not None
    assert chunk.part_counts.tolist() == [1]


def test_convert_geometry_chunks_appends_and_creates(tmp_path: pathlib.Path) -> None:
    output = tmp_path / "stream_chunks.gpkg"
    first_count = spatial_data.centroid_streaming.convert_geometry_chunks(
        tests.helpers.factories.spatial_data.centroid_streaming.geometry_features([
            tests.helpers.factories.spatial_data.centroid_streaming.SQUARE,
        ]),
        output,
        "buildings",
        first=True,
    )
    second_count = spatial_data.centroid_streaming.convert_geometry_chunks(
        tests.helpers.factories.spatial_data.centroid_streaming.geometry_features([
            tests.helpers.factories.spatial_data.centroid_streaming.SQUARE,
        ]),
        output,
        "buildings",
        first=False,
    )
    assert (first_count, second_count) == (1, 1)
    converted = geopandas.read_file(output, layer="buildings")
    assert len(converted) == first_count + second_count
    assert list(converted.columns) == ["geometry"]
    assert converted.crs.to_epsg() == spatial_data.reference.WGS84_SPATIAL_REFERENCE_ID


def test_convert_zip_stream_converts_geojson_member(tmp_path: pathlib.Path) -> None:
    output = tmp_path / "stream_zip.gpkg"
    features = [
        {
            "type": "Feature",
            "properties": {},
            "geometry": (
                tests.helpers.factories.spatial_data.centroid_streaming
            ).SQUARE,
        },
        {
            "type": "Feature",
            "properties": {},
            "geometry": (
                tests.helpers.factories.spatial_data.centroid_streaming
            ).SQUARE,
        },
    ]
    body = json.dumps(
        {"type": "FeatureCollection", "features": features},
        separators=(",", ":"),
    ).encode("utf-8")
    archive = tests.helpers.factories.spatial_data.centroid_streaming.archive_bytes({
        "California.geojson": body,
        "readme.txt": b"hi",
    })
    count = spatial_data.centroid_streaming.convert_zip_stream(
        (archive[i : i + 7] for i in range(0, len(archive), 7)),
        output,
        "buildings",
        first=True,
    )
    assert count == len(features)
    converted = geopandas.read_file(output, layer="buildings")
    assert list(converted.geometry.geom_type) == ["Point", "Point"]


def test_convert_zip_stream_raises_when_not_a_zip(tmp_path: pathlib.Path) -> None:
    with pytest.raises(
        spatial_data.exceptions.GeometryStreamError,
        match="not a zip file",
    ):
        spatial_data.centroid_streaming.convert_zip_stream(
            [b"not a zip"],
            tmp_path / "bad.gpkg",
            "buildings",
            first=True,
        )


def test_convert_zip_stream_raises_when_no_geojson_member(
    tmp_path: pathlib.Path,
) -> None:
    archive = tests.helpers.factories.spatial_data.centroid_streaming.archive_bytes({
        "readme.txt": b"hi",
    })
    with pytest.raises(
        spatial_data.exceptions.GeometryStreamError,
        match="No GeoJSON data found",
    ):
        spatial_data.centroid_streaming.convert_zip_stream(
            [archive],
            tmp_path / "empty.gpkg",
            "buildings",
            first=True,
        )


def test_convert_zip_stream_raises_when_geojson_unreadable(
    tmp_path: pathlib.Path,
) -> None:
    archive = tests.helpers.factories.spatial_data.centroid_streaming.archive_bytes({
        "California.geojson": b"not valid geojson {{{ ",
    })
    with pytest.raises(
        spatial_data.exceptions.GeometryStreamError,
        match="Failed to read the streamed GeoJSON",
    ):
        spatial_data.centroid_streaming.convert_zip_stream(
            [archive],
            tmp_path / "badjson.gpkg",
            "buildings",
            first=True,
        )


def test_convert_zip_stream_uses_reference_centroids(tmp_path: pathlib.Path) -> None:
    output = tmp_path / "stream_parity.gpkg"
    geometries = [
        tests.helpers.factories.spatial_data.centroid_streaming.SQUARE,
        tests.helpers.factories.spatial_data.centroid_streaming.SQUARE_WITH_HOLE,
        tests.helpers.factories.spatial_data.centroid_streaming.MULTIPOLYGON,
    ]
    body = json.dumps(
        {
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature", "properties": {}, "geometry": geometry}
                for geometry in geometries
            ],
        },
        separators=(",", ":"),
    ).encode("utf-8")
    spatial_data.centroid_streaming.convert_zip_stream(
        [
            tests.helpers.factories.spatial_data.centroid_streaming.archive_bytes({
                "state.geojson": body,
            }),
        ],
        output,
        "buildings",
        first=True,
    )
    converted = geopandas.read_file(output, layer="buildings")
    for geometry, point in zip(geometries, converted.geometry, strict=True):
        expected_x, expected_y = (
            tests.helpers.reference.spatial_data.centroid_streaming.reference_centroid(
                geometry,
            )
        )
        assert point.x == pytest.approx(expected_x, abs=1e-9)
        assert point.y == pytest.approx(expected_y, abs=1e-9)


def test_centroid_chunks_does_not_read_ahead(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(spatial_data.centroid_streaming, "FEATURE_CHUNK_SIZE", 1)
    geometries = iter([
        tests.helpers.factories.spatial_data.centroid_streaming.SQUARE,
        {"type": "Polygon", "coordinates": None},
    ])
    chunks = spatial_data.centroid_streaming.centroid_chunks(geometries)
    assert next(chunks).shape == (1, 2)
    with pytest.raises(TypeError):
        next(chunks)
