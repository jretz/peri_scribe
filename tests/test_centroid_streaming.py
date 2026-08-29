"""Tests for peri_scribe.centroid_streaming."""

from __future__ import annotations

import io
import json
import pathlib
import typing
import zipfile

import geopandas
import ijson
import pytest
import shapely.geometry

import peri_scribe.centroid_streaming
import peri_scribe.exceptions
import peri_scribe.models


def geometry_features(
    geometries: list[dict[str, object]],
) -> typing.Iterator[typing.Any]:
    """Return an ijson geometry iterator over *geometries*.

    Args:
        geometries: The GeoJSON geometry dicts to iterate.

    Returns:
        An iterator of ``features.item.geometry`` dicts.
    """
    features = [
        {"type": "Feature", "properties": {}, "geometry": geometry}
        for geometry in geometries
    ]
    body = json.dumps(
        {"type": "FeatureCollection", "features": features},
        separators=(",", ":"),
    ).encode("utf-8")
    return ijson.items(
        io.BytesIO(body),
        "features.item.geometry",
        use_float=True,
    )


def archive_bytes(members: dict[str, bytes]) -> bytes:
    """Return a zip archive holding *members*.

    Args:
        members: The member name to bytes mapping.

    Returns:
        The zip archive's bytes.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, body in members.items():
            archive.writestr(name, body)
    return buffer.getvalue()


def polygon(coordinates: list[object]) -> dict[str, object]:
    """Return a Polygon geometry dict with *coordinates*.

    Args:
        coordinates: The GeoJSON coordinates.

    Returns:
        The Polygon geometry dict.
    """
    return {"type": "Polygon", "coordinates": coordinates}


def reference_centroid(geometry: dict[str, object]) -> tuple[float, float]:
    """Return the reference (GEOS, projected) centroid of *geometry*.

    The geometry is projected to EPSG:3857, its centroid is computed, and the
    centroid is projected back to WGS84, mirroring the conversion's algorithm.

    Args:
        geometry: The GeoJSON geometry dict.

    Returns:
        The centroid's longitude and latitude.
    """
    projected = geopandas.GeoDataFrame(
        geometry=[shapely.geometry.shape(geometry)],
        crs="EPSG:4326",
    ).to_crs(3857)
    centroid = (
        geopandas
        .GeoDataFrame(
            geometry=projected.geometry.centroid,
            crs=3857,
        )
        .to_crs(4326)
        .geometry.iloc[0]
    )
    return centroid.x, centroid.y


SQUARE: dict[str, object] = polygon([[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]])
SQUARE_WITH_HOLE: dict[str, object] = polygon(
    [
        [[10, 10], [12, 10], [12, 12], [10, 12], [10, 10]],
        [[10.5, 10.5], [10.5, 11.5], [11.5, 11.5], [11.5, 10.5], [10.5, 10.5]],
    ],
)
MULTIPOLYGON: dict[str, object] = {
    "type": "MultiPolygon",
    "coordinates": [
        [[[20, 20], [21, 20], [21, 21], [20, 21], [20, 20]]],
        [[[22, 20], [23, 20], [23, 21], [22, 21], [22, 20]]],
    ],
}
CLOCKWISE_SQUARE: dict[str, object] = polygon(
    [[[40, 40], [40, 42], [42, 42], [42, 40], [40, 40]]],
)


def test_byte_stream_reads_across_chunk_boundaries() -> None:
    stream = peri_scribe.centroid_streaming.ByteStream([b"abcd", b"efgh"])
    assert stream.read(2) == b"ab"
    assert stream.read(5) == b"cdefg"
    assert stream.read(-1) == b"h"
    assert stream.read(1) == b""


def test_byte_stream_reads_all_remaining_with_pending_chunks() -> None:
    stream = peri_scribe.centroid_streaming.ByteStream([b"ab", b"cdef"])
    assert stream.read(-1) == b"abcdef"
    assert stream.read(1) == b""


def test_byte_stream_reads_from_empty_source() -> None:
    stream = peri_scribe.centroid_streaming.ByteStream([])
    assert stream.read() == b""


def test_collect_geometry_chunk_returns_none_at_end() -> None:
    chunk = peri_scribe.centroid_streaming.collect_geometry_chunk(
        iter([]),
        10,
        10,
    )
    assert chunk is None


def test_collect_geometry_chunk_collects_rings() -> None:
    chunk = peri_scribe.centroid_streaming.collect_geometry_chunk(
        geometry_features([SQUARE, SQUARE_WITH_HOLE, MULTIPOLYGON]),
        10,
        100,
    )
    assert chunk is not None
    # 5 points for the square, 5 + 5 for the square with a hole, and 5 + 5 for
    # the multipolygon's two parts.
    assert chunk.coordinates.shape == (25, 2)
    assert chunk.ring_bounds.tolist() == [
        [0, 5],
        [5, 10],
        [10, 15],
        [15, 20],
        [20, 25],
    ]
    # Each polygon's rings are one part; the multipolygon's two parts each hold one.
    assert chunk.ring_parts.tolist() == [0, 1, 1, 2, 3]
    assert chunk.part_counts.tolist() == [1, 1, 2]


def test_collect_geometry_chunk_stops_at_feature_limit() -> None:
    chunk = peri_scribe.centroid_streaming.collect_geometry_chunk(
        geometry_features([SQUARE, SQUARE, SQUARE]),
        2,
        100,
    )
    assert chunk is not None
    assert chunk.part_counts.tolist() == [1, 1]


def test_collect_geometry_chunk_stops_at_vertex_limit() -> None:
    chunk = peri_scribe.centroid_streaming.collect_geometry_chunk(
        geometry_features([SQUARE, SQUARE]),
        10,
        8,
    )
    assert chunk is not None
    # The vertex limit is checked after a feature is collected, so the chunk may
    # exceed it by one feature's vertices.
    assert chunk.part_counts.tolist() == [1, 1]
    assert chunk.coordinates.shape == (10, 2)


def test_collect_geometry_chunk_skips_non_polygon_geometry() -> None:
    point: dict[str, object] = {"type": "Point", "coordinates": [0, 0]}
    chunk = peri_scribe.centroid_streaming.collect_geometry_chunk(
        geometry_features([point, SQUARE]),
        10,
        100,
    )
    assert chunk is not None
    assert chunk.part_counts.tolist() == [1]


def test_polygon_centroids_match_reference() -> None:
    geometries = [SQUARE, SQUARE_WITH_HOLE, MULTIPOLYGON, CLOCKWISE_SQUARE]
    chunk = peri_scribe.centroid_streaming.collect_geometry_chunk(
        geometry_features(geometries),
        10,
        100,
    )
    assert chunk is not None
    centroids = peri_scribe.centroid_streaming.polygon_centroids(chunk)
    for centroid, geometry in zip(centroids, geometries, strict=True):
        expected_x, expected_y = reference_centroid(geometry)
        assert centroid[0] == pytest.approx(expected_x, abs=1e-9)
        assert centroid[1] == pytest.approx(expected_y, abs=1e-9)


def test_polygon_centroids_fall_back_to_mean_vertex_for_zero_area() -> None:
    degenerate: dict[str, object] = polygon(
        [[[30, 30], [31, 30], [32, 30], [30, 30]]],
    )
    chunk = peri_scribe.centroid_streaming.collect_geometry_chunk(
        geometry_features([degenerate]),
        10,
        100,
    )
    assert chunk is not None
    centroids = peri_scribe.centroid_streaming.polygon_centroids(chunk)
    # The zero-area ring's shoelace sums are zero, so the fallback mean vertex is
    # used: the mean of the four ring points.
    assert centroids[0] == pytest.approx([30.75, 30.0], abs=1e-6)


def test_convert_geometry_chunks_appends_and_creates(
    tmp_path: pathlib.Path,
) -> None:
    output = tmp_path / "stream_chunks.gpkg"
    first_count = peri_scribe.centroid_streaming.convert_geometry_chunks(
        geometry_features([SQUARE]),
        output,
        "buildings",
        first=True,
    )
    second_count = peri_scribe.centroid_streaming.convert_geometry_chunks(
        geometry_features([SQUARE]),
        output,
        "buildings",
        first=False,
    )
    assert (first_count, second_count) == (1, 1)
    converted = geopandas.read_file(output, layer="buildings")
    assert len(converted) == first_count + second_count
    assert list(converted.columns) == ["geometry"]
    assert converted.crs.to_epsg() == peri_scribe.models.WGS84_SPATIAL_REFERENCE_ID


def test_convert_zip_stream_converts_geojson_member(
    tmp_path: pathlib.Path,
) -> None:
    output = tmp_path / "stream_zip.gpkg"
    features = [
        {"type": "Feature", "properties": {}, "geometry": SQUARE},
        {"type": "Feature", "properties": {}, "geometry": SQUARE},
    ]
    body = json.dumps(
        {
            "type": "FeatureCollection",
            "features": features,
        },
        separators=(",", ":"),
    ).encode("utf-8")
    archive = archive_bytes({"California.geojson": body, "readme.txt": b"hi"})
    count = peri_scribe.centroid_streaming.convert_zip_stream(
        (archive[i : i + 7] for i in range(0, len(archive), 7)),
        output,
        "buildings",
        first=True,
    )
    assert count == len(features)
    converted = geopandas.read_file(output, layer="buildings")
    assert list(converted.geometry.geom_type) == ["Point", "Point"]


def test_convert_zip_stream_raises_when_not_a_zip(
    tmp_path: pathlib.Path,
) -> None:
    with pytest.raises(
        peri_scribe.exceptions.ExternalDataError,
        match="not a zip file",
    ):
        peri_scribe.centroid_streaming.convert_zip_stream(
            [b"not a zip"],
            tmp_path / "bad.gpkg",
            "buildings",
            first=True,
        )


def test_convert_zip_stream_raises_when_no_geojson_member(
    tmp_path: pathlib.Path,
) -> None:
    archive = archive_bytes({"readme.txt": b"hi"})
    with pytest.raises(
        peri_scribe.exceptions.ExternalDataError,
        match="No GeoJSON data found",
    ):
        peri_scribe.centroid_streaming.convert_zip_stream(
            [archive],
            tmp_path / "empty.gpkg",
            "buildings",
            first=True,
        )


def test_convert_zip_stream_raises_when_geojson_unreadable(
    tmp_path: pathlib.Path,
) -> None:
    archive = archive_bytes({"California.geojson": b"not valid geojson {{{ "})
    with pytest.raises(
        peri_scribe.exceptions.ExternalDataError,
        match="Failed to read the streamed GeoJSON",
    ):
        peri_scribe.centroid_streaming.convert_zip_stream(
            [archive],
            tmp_path / "badjson.gpkg",
            "buildings",
            first=True,
        )


def test_convert_zip_stream_uses_reference_centroids(
    tmp_path: pathlib.Path,
) -> None:
    output = tmp_path / "stream_parity.gpkg"
    geometries = [SQUARE, SQUARE_WITH_HOLE, MULTIPOLYGON]
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
    peri_scribe.centroid_streaming.convert_zip_stream(
        [archive_bytes({"state.geojson": body})],
        output,
        "buildings",
        first=True,
    )
    converted = geopandas.read_file(output, layer="buildings")
    for geometry, point in zip(geometries, converted.geometry, strict=True):
        expected_x, expected_y = reference_centroid(geometry)
        assert point.x == pytest.approx(expected_x, abs=1e-9)
        assert point.y == pytest.approx(expected_y, abs=1e-9)
