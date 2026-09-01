"""Tests for peri_scribe.sources.buildings.

The tests use synthetic in-memory archives and temporary databases; they never touch
the network or the real buildings dataset.
"""

from __future__ import annotations

import dataclasses
import io
import itertools
import json
import pathlib
import sqlite3
import struct
import tempfile
import typing
import zipfile

import numpy as np
import pytest
import shapely.geometry

import peri_scribe.exceptions
import peri_scribe.sources.buildings
import peri_scribe.sources.external_sources
import tests.peri_scribe.sources.external_source_helpers


# The encoded coordinate values the quantization tests expect.
QUANTIZED_ONE_POINT_FIVE_DEGREES = 150_000
QUANTIZED_NEGATIVE_HALF_DEGREE = -50_000
QUANTIZED_FORTY_POINT_TWENTY_FIVE_DEGREES = 4_025_000
QUANTIZED_NEGATIVE_NINETY_DEGREES = -9_000_000
QUANTIZED_HALF_DEGREE = 50_000


def write_database(points: np.ndarray, path: pathlib.Path) -> None:
    """Build a compact buildings database at *path* holding *points*.

    The points are appended to temporary partition files and processed through the
    production database build, so the resulting file is a real compact database.

    Args:
        points: The ``(n, 2)`` longitude/latitude pairs in degrees.
        path: The database path to write.
    """
    with tempfile.TemporaryDirectory() as temporary_directory:
        partition_directory = pathlib.Path(temporary_directory)
        with peri_scribe.sources.buildings.PartitionFiles(
            partition_directory,
        ) as partition_files:
            peri_scribe.sources.buildings.append_centroids_to_partitions(
                points,
                partition_files,
            )
        peri_scribe.sources.buildings.build_tiles_database(
            partition_directory,
            path,
        )


def zip_bytes(members: dict[str, bytes]) -> bytes:
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


def feature_collection_bytes(rings: list[list[list[float]]]) -> bytes:
    """Return the bytes of a GeoJSON FeatureCollection holding *rings*.

    Args:
        rings: Each feature's polygon ring coordinates.

    Returns:
        The FeatureCollection's bytes.
    """
    features = [
        {
            "type": "Feature",
            "properties": {},
            "geometry": {"type": "Polygon", "coordinates": [ring]},
        }
        for ring in rings
    ]
    body = json.dumps(
        {"type": "FeatureCollection", "features": features},
        separators=(",", ":"),
    )
    return body.encode("utf-8")


def square_ring(
    center_x: float,
    center_y: float,
    half: float = 0.5,
) -> list[list[float]]:
    """Return the ring of a square centered at (*center_x*, *center_y*).

    Args:
        center_x: The center longitude.
        center_y: The center latitude.
        half: Half the square's side length.

    Returns:
        The ring's coordinates.
    """
    return [
        [center_x - half, center_y - half],
        [center_x + half, center_y - half],
        [center_x + half, center_y + half],
        [center_x - half, center_y + half],
        [center_x - half, center_y - half],
    ]


def buildings_fetch_page() -> str:
    """Return a repository page with a download link for every state.

    Returns:
        The page's HTML.
    """
    links = {
        state: f"https://example.com/{state.replace(' ', '')}.geojson.zip"
        for state in peri_scribe.sources.external_sources.BUILDINGS_STATES
    }
    return tests.peri_scribe.sources.external_source_helpers.buildings_page_html(links)


def test_encode_longitude_scales_and_rounds() -> None:
    assert (
        peri_scribe.sources.buildings.encode_longitude(1.5)
        == QUANTIZED_ONE_POINT_FIVE_DEGREES
    )
    assert (
        peri_scribe.sources.buildings.encode_longitude(-0.5)
        == QUANTIZED_NEGATIVE_HALF_DEGREE
    )
    assert peri_scribe.sources.buildings.encode_longitude(0.000004) == 0


def test_encode_latitude_scales_and_rounds() -> None:
    assert (
        peri_scribe.sources.buildings.encode_latitude(40.25)
        == QUANTIZED_FORTY_POINT_TWENTY_FIVE_DEGREES
    )
    assert (
        peri_scribe.sources.buildings.encode_latitude(-90.0)
        == QUANTIZED_NEGATIVE_NINETY_DEGREES
    )


def test_quantize_centroids_matches_scalar_encoding() -> None:
    centroids = np.asarray([[1.5, -2.5], [0.000004, 40.25]], dtype=float)
    encoded = peri_scribe.sources.buildings.quantize_centroids(centroids)
    assert encoded.tolist() == [
        [
            peri_scribe.sources.buildings.encode_longitude(longitude),
            peri_scribe.sources.buildings.encode_latitude(latitude),
        ]
        for longitude, latitude in centroids
    ]


def test_tile_id_maps_encoded_coordinates() -> None:
    assert peri_scribe.sources.buildings.tile_id(0, 0) == 180 * 720 + 360
    assert peri_scribe.sources.buildings.tile_id(-18_000_000, -9_000_000) == 0
    assert peri_scribe.sources.buildings.tile_id(10_050_000, 4_025_000) == (
        260 * 720 + 561
    )


def test_tile_ids_matches_scalar_tile_id() -> None:
    encoded = np.asarray(
        [[0, 0], [10_050_000, 4_025_000], [-18_000_000, -9_000_000]],
        dtype="<i4",
    )
    identifiers = peri_scribe.sources.buildings.tile_ids(encoded)
    assert identifiers.tolist() == list(
        itertools.starmap(
            peri_scribe.sources.buildings.tile_id,
            encoded,
        ),
    )


def test_tile_id_puts_boundary_points_in_upper_tile() -> None:
    # 0.5° is exactly representable, so its encoded coordinate lands on the boundary
    # between tile columns 360 and 361 and rows 180 and 181; the floor division puts
    # the point in the upper tile.
    assert peri_scribe.sources.buildings.encode_longitude(0.5) == QUANTIZED_HALF_DEGREE
    assert (
        peri_scribe.sources.buildings.tile_id(
            QUANTIZED_HALF_DEGREE,
            QUANTIZED_HALF_DEGREE,
        )
        == 181 * 720 + 361
    )


def test_encode_record_is_eight_little_endian_bytes() -> None:
    record = peri_scribe.sources.buildings.encode_record(1.5, -2.5)
    assert record == struct.pack("<ii", 150_000, -250_000)
    assert len(record) == peri_scribe.sources.buildings.RECORD_SIZE_BYTES


def test_partition_id_is_tile_id_modulo_partition_count() -> None:
    identifier = peri_scribe.sources.buildings.tile_id(0, 0)
    assert peri_scribe.sources.buildings.partition_id(identifier) == identifier % 16


def test_partition_ids_matches_scalar_partition_id() -> None:
    identifiers = np.asarray([129_960, 187_761], dtype="<i4")
    partitions = peri_scribe.sources.buildings.partition_ids(identifiers)
    assert partitions.tolist() == [
        peri_scribe.sources.buildings.partition_id(identifier)
        for identifier in identifiers
    ]


def test_append_centroids_to_partitions_routes_by_partition(
    tmp_path: pathlib.Path,
) -> None:
    points = np.asarray([[0.2, 0.2], [0.3, 0.3]], dtype=float)
    with peri_scribe.sources.buildings.PartitionFiles(tmp_path) as partition_files:
        peri_scribe.sources.buildings.append_centroids_to_partitions(
            points,
            partition_files,
        )
    for partition in range(16):
        records = (tmp_path / f"partition-{partition:02d}.bin").read_bytes()
        if partition == 129_960 % 16:
            assert records == (
                struct.pack("<ii", 20_000, 20_000) + struct.pack("<ii", 30_000, 30_000)
            )
        else:
            assert records == b""


def test_append_centroids_to_partitions_separates_partitions(
    tmp_path: pathlib.Path,
) -> None:
    points = np.asarray([[0.2, 0.2], [100.5, 40.25]], dtype=float)
    with peri_scribe.sources.buildings.PartitionFiles(tmp_path) as partition_files:
        peri_scribe.sources.buildings.append_centroids_to_partitions(
            points,
            partition_files,
        )
    first_partition = peri_scribe.sources.buildings.partition_id(
        peri_scribe.sources.buildings.tile_id(20_000, 20_000),
    )
    second_partition = peri_scribe.sources.buildings.partition_id(
        peri_scribe.sources.buildings.tile_id(10_050_000, 4_025_000),
    )
    assert first_partition != second_partition
    assert (tmp_path / f"partition-{first_partition:02d}.bin").read_bytes() == (
        struct.pack("<ii", 20_000, 20_000)
    )
    assert (tmp_path / f"partition-{second_partition:02d}.bin").read_bytes() == (
        struct.pack("<ii", 10_050_000, 4_025_000)
    )


def test_compress_tile_points_sorts_raw_records() -> None:
    points = np.asarray([[1, 2], [0, 0], [-1, 3]], dtype="<i4")
    payload = peri_scribe.sources.buildings.compress_tile_points(points)
    decoded = peri_scribe.sources.buildings.decode_payload(payload)
    # The raw 8-byte representation sorts lexicographically by byte, which is not
    # numeric order: (0, 0) < (1, 2) < (-1, 3).
    assert decoded.tolist() == [[0, 0], [1, 2], [-1, 3]]


def test_process_partition_writes_one_row_per_tile(
    tmp_path: pathlib.Path,
) -> None:
    points = np.asarray(
        [[0.2, 0.2], [0.3, 0.3], [100.5, 40.25]],
        dtype=float,
    )
    with peri_scribe.sources.buildings.PartitionFiles(tmp_path) as partition_files:
        peri_scribe.sources.buildings.append_centroids_to_partitions(
            points,
            partition_files,
        )
    output = tmp_path / "buildings.sqlite"
    total = peri_scribe.sources.buildings.build_tiles_database(tmp_path, output)
    assert total == len(points)
    connection = sqlite3.connect(output)
    try:
        rows = connection.execute(
            "SELECT tile_id, building_count FROM tiles ORDER BY tile_id",
        ).fetchall()
    finally:
        connection.close()
    assert rows == [(129_960, 2), (187_761, 1)]


def test_is_valid_database_accepts_written_database(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "buildings.sqlite"
    write_database(np.asarray([[0.2, 0.2]], dtype=float), path)
    assert peri_scribe.sources.buildings.is_valid_database(path)


def test_is_valid_database_rejects_missing_file(tmp_path: pathlib.Path) -> None:
    assert not peri_scribe.sources.buildings.is_valid_database(
        tmp_path / "missing.sqlite",
    )


def test_is_valid_database_rejects_non_database_file(
    tmp_path: pathlib.Path,
) -> None:
    path = tmp_path / "junk.sqlite"
    path.write_bytes(b"not a database")
    assert not peri_scribe.sources.buildings.is_valid_database(path)


def test_is_valid_database_rejects_unopenable_path(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(_path: object) -> typing.Never:
        message = "boom"
        raise OSError(message)

    path = tmp_path / "buildings.sqlite"
    path.write_bytes(b"")
    monkeypatch.setattr(
        peri_scribe.sources.buildings.sqlite3,
        "connect",
        fail,
    )
    assert not peri_scribe.sources.buildings.is_valid_database(path)


def test_is_valid_database_rejects_wrong_metadata(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "buildings.sqlite"
    write_database(np.asarray([[0.2, 0.2]], dtype=float), path)
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "UPDATE metadata SET value = ? WHERE key = 'version'",
            ("2025-01-01",),
        )
        connection.commit()
    finally:
        connection.close()
    assert not peri_scribe.sources.buildings.is_valid_database(path)


def test_is_valid_database_rejects_wrong_schema(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "buildings.sqlite"
    write_database(np.asarray([[0.2, 0.2]], dtype=float), path)
    connection = sqlite3.connect(path)
    try:
        connection.execute("DROP TABLE tiles")
        connection.commit()
    finally:
        connection.close()
    assert not peri_scribe.sources.buildings.is_valid_database(path)


def test_decode_payload_round_trips_encoded_points(tmp_path: pathlib.Path) -> None:
    points = np.asarray([[0.2, 0.2], [0.3, 0.3], [100.5, 40.25]], dtype=float)
    path = tmp_path / "buildings.sqlite"
    write_database(points, path)
    connection = sqlite3.connect(path)
    try:
        rows = connection.execute(
            "SELECT tile_id, payload FROM tiles ORDER BY tile_id",
        ).fetchall()
    finally:
        connection.close()
    decoded = np.concatenate(
        [
            peri_scribe.sources.buildings.decode_payload(payload)
            for _identifier, payload in rows
        ],
    )
    expected = peri_scribe.sources.buildings.quantize_centroids(points)
    assert sorted(map(tuple, decoded)) == sorted(map(tuple, expected))


def test_tile_ids_for_box_selects_single_tile() -> None:
    assert peri_scribe.sources.buildings.tile_ids_for_box(
        (0.1, 0.1, 0.4, 0.4),
    ) == [129_960]


def test_tile_ids_for_box_spans_multiple_tiles() -> None:
    assert peri_scribe.sources.buildings.tile_ids_for_box(
        (0.1, 0.1, 0.6, 0.6),
    ) == [
        180 * 720 + 360,
        180 * 720 + 361,
        181 * 720 + 360,
        181 * 720 + 361,
    ]


def test_tile_ids_for_box_includes_boundary_tiles() -> None:
    # A box ending exactly at 0.5° includes tile column 361, where the boundary
    # point itself lives.
    assert (
        peri_scribe.sources.buildings.tile_ids_for_box(
            (0.4, 0.4, 0.5, 0.5),
        )[-1]
        == 181 * 720 + 361
    )


def test_points_within_box_filters_by_encoded_bounds() -> None:
    points = np.asarray([[0, 0], [1, 1], [-1, 1], [1, -1]], dtype="<i4")
    filtered = peri_scribe.sources.buildings.points_within_box(points, (0, 0, 1, 1))
    assert filtered.tolist() == [[0, 0], [1, 1]]


def test_building_counts_within_counts_points_across_tiles(
    tmp_path: pathlib.Path,
) -> None:
    points = np.asarray(
        [
            [0.2, 0.2],
            [0.3, 0.3],
            [100.5, 40.25],
            [101.0, 41.0],
        ],
        dtype=float,
    )
    path = tmp_path / "buildings.sqlite"
    write_database(points, path)
    counts = peri_scribe.sources.buildings.building_counts_within(
        [
            shapely.geometry.box(0.0, 0.0, 1.0, 1.0),
            shapely.geometry.box(100.0, 40.0, 101.5, 41.5),
        ],
        path,
    )
    assert counts == [2, 2]


def test_building_counts_within_includes_points_on_upper_boundary(
    tmp_path: pathlib.Path,
) -> None:
    points = np.asarray([[0.5, 0.5]], dtype=float)
    path = tmp_path / "buildings.sqlite"
    write_database(points, path)
    # The box filter and tile selection include a point exactly on the tile boundary,
    # but exact containment (like the legacy implementation) excludes a point on the
    # query geometry's boundary; a box strictly containing the point counts it.
    counts = peri_scribe.sources.buildings.building_counts_within(
        [shapely.geometry.box(0.4, 0.4, 0.5, 0.5)],
        path,
    )
    assert counts == [0]
    counts = peri_scribe.sources.buildings.building_counts_within(
        [shapely.geometry.box(0.4, 0.4, 0.51, 0.51)],
        path,
    )
    assert counts == [1]
    counts = peri_scribe.sources.buildings.building_counts_within(
        [shapely.geometry.box(0.4, 0.4, 0.5, 0.5)],
        path,
    )
    assert counts == [0]


def test_building_counts_within_tests_exact_containment(
    tmp_path: pathlib.Path,
) -> None:
    points = np.asarray([[0.2, 0.1], [0.1, 0.2]], dtype=float)
    path = tmp_path / "buildings.sqlite"
    write_database(points, path)
    triangle = shapely.geometry.Polygon([(0, 0), (1, 0), (1, 1)])
    counts = peri_scribe.sources.buildings.building_counts_within([triangle], path)
    assert counts == [1]


def test_building_counts_within_counts_point_for_each_containing_geometry(
    tmp_path: pathlib.Path,
) -> None:
    points = np.asarray([[0.5, 0.5]], dtype=float)
    path = tmp_path / "buildings.sqlite"
    write_database(points, path)
    counts = peri_scribe.sources.buildings.building_counts_within(
        [
            shapely.geometry.box(0.0, 0.0, 1.0, 1.0),
            shapely.geometry.box(0.25, 0.25, 0.75, 0.75),
        ],
        path,
    )
    assert counts == [1, 1]


def test_building_counts_within_returns_zero_without_geometry(
    tmp_path: pathlib.Path,
) -> None:
    path = tmp_path / "buildings.sqlite"
    write_database(np.asarray([[0.2, 0.2]], dtype=float), path)
    counts = peri_scribe.sources.buildings.building_counts_within(
        [None, shapely.geometry.Polygon()],
        path,
    )
    assert counts == [0, 0]


def test_building_counts_within_skips_geometries_without_candidates(
    tmp_path: pathlib.Path,
) -> None:
    path = tmp_path / "buildings.sqlite"
    write_database(np.asarray([[0.2, 0.2]], dtype=float), path)
    counts = peri_scribe.sources.buildings.building_counts_within(
        [shapely.geometry.box(200.0, 200.0, 201.0, 201.0)],
        path,
    )
    assert counts == [0]


def test_building_counts_within_returns_zero_without_database(
    tmp_path: pathlib.Path,
) -> None:
    counts = peri_scribe.sources.buildings.building_counts_within(
        [shapely.geometry.box(0.0, 0.0, 1.0, 1.0)],
        tmp_path / "missing.sqlite",
    )
    assert counts == [0]


def test_fetch_buildings_database_streams_states_into_database(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = dataclasses.replace(
        peri_scribe.sources.external_sources.BUILDINGS_SOURCE,
        states=("California", "Texas"),
    )
    page = buildings_fetch_page()
    links = {
        state: f"https://example.com/{state.replace(' ', '')}.geojson.zip"
        for state in peri_scribe.sources.external_sources.BUILDINGS_STATES
    }
    archives = {
        "California.geojson.zip": zip_bytes(
            {
                "California.geojson": feature_collection_bytes(
                    [square_ring(0.0, 0.0)],
                ),
            },
        ),
        "Texas.geojson.zip": zip_bytes(
            {
                "Texas.geojson": feature_collection_bytes(
                    [square_ring(100.5, 40.25)],
                ),
                "readme.txt": b"hi",
            },
        ),
    }
    urls: list[str] = []

    def get(
        url: str,
        **_kwargs: object,
    ) -> tests.peri_scribe.sources.external_source_helpers.FakeResponse:
        urls.append(url)
        if url == peri_scribe.sources.external_sources.BUILDINGS_SOURCE.url:
            return tests.peri_scribe.sources.external_source_helpers.FakeResponse(
                page.encode("utf-8"),
            )
        return tests.peri_scribe.sources.external_source_helpers.FakeResponse(
            archives[url.rsplit("/", 1)[-1]],
        )

    monkeypatch.setattr(
        peri_scribe.sources.buildings.requests,
        "get",
        get,
    )

    result = peri_scribe.sources.external_sources.fetch_external_source(
        source,
        tmp_path,
    )
    output = tmp_path / "sources" / "buildings.sqlite"
    assert result == (output,)
    assert urls == [
        peri_scribe.sources.external_sources.BUILDINGS_SOURCE.url,
        links["California"],
        links["Texas"],
    ]
    assert peri_scribe.sources.buildings.is_valid_database(output)
    sources = tmp_path / "sources"
    assert sorted(path.name for path in sources.iterdir()) == ["buildings.sqlite"]
    connection = sqlite3.connect(output)
    try:
        tile_rows = connection.execute(
            "SELECT COUNT(*) FROM tiles",
        ).fetchone()[0]
        total = connection.execute(
            "SELECT COALESCE(SUM(building_count), 0) FROM tiles",
        ).fetchone()[0]
    finally:
        connection.close()
    assert tile_rows == len(source.states)
    assert total == len(source.states)
    counts = peri_scribe.sources.buildings.building_counts_within(
        [
            shapely.geometry.box(99.0, 39.0, 102.0, 42.0),
            shapely.geometry.box(-1.0, -1.0, 1.0, 1.0),
        ],
        output,
    )
    assert counts == [1, 1]


def test_fetch_buildings_database_skips_valid_existing_database(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "sources" / "buildings.sqlite"
    output.parent.mkdir(parents=True)
    write_database(np.asarray([[0.2, 0.2]], dtype=float), output)
    original = output.read_bytes()
    monkeypatch.setattr(
        peri_scribe.sources.buildings.requests,
        "get",
        lambda *_arguments, **_keywords: pytest.fail("no downloads expected"),
    )

    result = peri_scribe.sources.external_sources.fetch_external_source(
        peri_scribe.sources.external_sources.BUILDINGS_SOURCE,
        tmp_path,
    )

    assert result == (output,)
    assert output.read_bytes() == original


def test_fetch_buildings_database_preserves_existing_file_when_download_fails(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "sources" / "buildings.sqlite"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"existing contents")
    monkeypatch.setattr(
        peri_scribe.sources.buildings.requests,
        "get",
        lambda _url, **_kwargs: (
            tests.peri_scribe.sources.external_source_helpers.FakeResponse(
                b"<html><body><p>hi</p></body></html>",
            )
        ),
    )
    with pytest.raises(
        peri_scribe.exceptions.ExternalDataError,
        match="No download links found",
    ):
        peri_scribe.sources.external_sources.fetch_external_source(
            dataclasses.replace(
                peri_scribe.sources.external_sources.BUILDINGS_SOURCE,
                states=("California",),
            ),
            tmp_path,
        )
    assert output.read_bytes() == b"existing contents"


def test_fetch_buildings_database_preserves_existing_file_when_archive_fails(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "sources" / "buildings.sqlite"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"existing contents")

    def fail(_url: str, **_kwargs: object) -> typing.Never:
        message = "boom"
        raise peri_scribe.sources.buildings.requests.exceptions.RequestException(
            message,
        )

    monkeypatch.setattr(
        peri_scribe.sources.buildings.requests,
        "get",
        fail,
    )
    with pytest.raises(
        peri_scribe.exceptions.ExternalDataError,
        match="Failed to download",
    ):
        peri_scribe.sources.external_sources.fetch_external_source(
            dataclasses.replace(
                peri_scribe.sources.external_sources.BUILDINGS_SOURCE,
                states=("California",),
                state_urls=None,
                url="https://example.com/legacy/{state}.geojson.zip",
            ),
            tmp_path,
        )
    assert output.read_bytes() == b"existing contents"


def test_fetch_buildings_database_raises_when_archive_is_not_a_zip(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = dataclasses.replace(
        peri_scribe.sources.external_sources.BUILDINGS_SOURCE,
        states=("California",),
        state_urls=None,
        url="https://example.com/legacy/{state}.geojson.zip",
    )
    monkeypatch.setattr(
        peri_scribe.sources.buildings.requests,
        "get",
        lambda _url, **_kwargs: (
            tests.peri_scribe.sources.external_source_helpers.FakeResponse(b"not a zip")
        ),
    )
    with pytest.raises(
        peri_scribe.exceptions.ExternalDataError,
        match="is not a zip file",
    ):
        peri_scribe.sources.external_sources.fetch_external_source(source, tmp_path)
    assert not (tmp_path / "sources" / "buildings.sqlite").exists()


def test_fetch_buildings_database_raises_when_geojson_is_unreadable(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = dataclasses.replace(
        peri_scribe.sources.external_sources.BUILDINGS_SOURCE,
        states=("California",),
        state_urls=None,
        url="https://example.com/legacy/{state}.geojson.zip",
    )
    archive = zip_bytes({"California.geojson": b"not valid geojson {{{ "})
    monkeypatch.setattr(
        peri_scribe.sources.buildings.requests,
        "get",
        lambda _url, **_kwargs: (
            tests.peri_scribe.sources.external_source_helpers.FakeResponse(archive)
        ),
    )
    with pytest.raises(
        peri_scribe.exceptions.ExternalDataError,
        match="Failed to read the streamed GeoJSON",
    ):
        peri_scribe.sources.external_sources.fetch_external_source(source, tmp_path)
    assert not (tmp_path / "sources" / "buildings.sqlite").exists()


def test_fetch_buildings_database_raises_when_generated_database_is_invalid(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = dataclasses.replace(
        peri_scribe.sources.external_sources.BUILDINGS_SOURCE,
        states=("California",),
        state_urls=None,
        url="https://example.com/legacy/{state}.geojson.zip",
    )
    archive = zip_bytes(
        {
            "California.geojson": feature_collection_bytes(
                [square_ring(0.0, 0.0)],
            ),
        },
    )
    monkeypatch.setattr(
        peri_scribe.sources.buildings.requests,
        "get",
        lambda _url, **_kwargs: (
            tests.peri_scribe.sources.external_source_helpers.FakeResponse(archive)
        ),
    )
    monkeypatch.setattr(
        peri_scribe.sources.buildings,
        "is_valid_database",
        lambda _path: False,
    )
    with pytest.raises(
        peri_scribe.exceptions.ExternalDataError,
        match="generated buildings database is invalid",
    ):
        peri_scribe.sources.external_sources.fetch_external_source(source, tmp_path)
    assert not (tmp_path / "sources" / "buildings.sqlite").exists()


def test_fetch_buildings_database_raises_when_archive_has_no_geojson(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = dataclasses.replace(
        peri_scribe.sources.external_sources.BUILDINGS_SOURCE,
        states=("California",),
        state_urls=None,
        url="https://example.com/legacy/{state}.geojson.zip",
    )
    archive = zip_bytes({"readme.txt": b"hi"})
    monkeypatch.setattr(
        peri_scribe.sources.buildings.requests,
        "get",
        lambda _url, **_kwargs: (
            tests.peri_scribe.sources.external_source_helpers.FakeResponse(archive)
        ),
    )
    with pytest.raises(
        peri_scribe.exceptions.ExternalDataError,
        match="No GeoJSON data found",
    ):
        peri_scribe.sources.external_sources.fetch_external_source(source, tmp_path)
    assert not (tmp_path / "sources" / "buildings.sqlite").exists()
