"""Exercise reusable spatial operations."""

from __future__ import annotations

import itertools
import pathlib
import sqlite3
import struct

import numpy as np
import pytest
import shapely.geometry

import spatial_data.point_store
import tests.helpers.doubles.errors
import tests.helpers.doubles.spatial_data.point_store
import tests.helpers.factories.spatial_data.point_store


def test_encode_longitude_scales_and_rounds() -> None:
    assert (
        spatial_data.point_store.encode_longitude(1.5)
        == (
            tests.helpers.factories.spatial_data.point_store
        ).QUANTIZED_ONE_POINT_FIVE_DEGREES
    )
    assert (
        spatial_data.point_store.encode_longitude(-0.5)
        == (
            tests.helpers.factories.spatial_data.point_store
        ).QUANTIZED_NEGATIVE_HALF_DEGREE
    )
    assert spatial_data.point_store.encode_longitude(0.000004) == 0


def test_encode_latitude_scales_and_rounds() -> None:
    assert (
        spatial_data.point_store.encode_latitude(40.25)
        == (
            tests.helpers.factories.spatial_data.point_store
        ).QUANTIZED_FORTY_POINT_TWENTY_FIVE_DEGREES
    )
    assert (
        spatial_data.point_store.encode_latitude(-90.0)
        == (
            tests.helpers.factories.spatial_data.point_store
        ).QUANTIZED_NEGATIVE_NINETY_DEGREES
    )


def test_quantize_centroids_matches_scalar_encoding() -> None:
    centroids = np.asarray([[1.5, -2.5], [0.000004, 40.25]], dtype=float)
    encoded = spatial_data.point_store.quantize_centroids(centroids)
    assert encoded.tolist() == [
        [
            spatial_data.point_store.encode_longitude(longitude),
            spatial_data.point_store.encode_latitude(latitude),
        ]
        for longitude, latitude in centroids
    ]


def test_tile_id_maps_encoded_coordinates() -> None:
    assert spatial_data.point_store.tile_id(0, 0) == 180 * 720 + 360
    assert spatial_data.point_store.tile_id(-18_000_000, -9_000_000) == 0
    assert spatial_data.point_store.tile_id(10_050_000, 4_025_000) == (260 * 720 + 561)


@pytest.mark.parametrize(
    ("longitude", "latitude", "expected"),
    [
        (18_000_000, 0, 180 * 720 + 719),
        (0, 9_000_000, 359 * 720 + 360),
        (18_000_000, 9_000_000, 359 * 720 + 719),
    ],
)
def test_tile_id_keeps_geographic_upper_endpoints_in_edge_tiles(
    longitude: int,
    latitude: int,
    expected: int,
) -> None:
    assert spatial_data.point_store.tile_id(longitude, latitude) == expected


def test_tile_ids_matches_scalar_tile_id() -> None:
    encoded = np.asarray(
        [[0, 0], [10_050_000, 4_025_000], [-18_000_000, -9_000_000]],
        dtype="<i4",
    )
    identifiers = spatial_data.point_store.tile_ids(encoded)
    assert identifiers.tolist() == list(
        itertools.starmap(spatial_data.point_store.tile_id, encoded),
    )


def test_tile_id_puts_boundary_points_in_upper_tile() -> None:
    # 0.5° is exactly representable, so its encoded coordinate lands on the boundary
    # between tile columns 360 and 361 and rows 180 and 181; the floor division puts the
    # point in the upper tile.
    assert (
        spatial_data.point_store.encode_longitude(0.5)
        == tests.helpers.factories.spatial_data.point_store.QUANTIZED_HALF_DEGREE
    )
    assert (
        spatial_data.point_store.tile_id(
            tests.helpers.factories.spatial_data.point_store.QUANTIZED_HALF_DEGREE,
            tests.helpers.factories.spatial_data.point_store.QUANTIZED_HALF_DEGREE,
        )
        == 181 * 720 + 361
    )


def test_append_centroids_to_partitions_routes_by_partition(
    tmp_path: pathlib.Path,
) -> None:
    points = np.asarray([[0.2, 0.2], [0.3, 0.3]], dtype=float)
    with spatial_data.point_store.PartitionFiles(tmp_path) as partition_files:
        spatial_data.point_store.append_centroids_to_partitions(
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
    with spatial_data.point_store.PartitionFiles(tmp_path) as partition_files:
        spatial_data.point_store.append_centroids_to_partitions(
            points,
            partition_files,
        )
    first_partition = spatial_data.point_store.tile_id(20_000, 20_000) % 16
    second_partition = spatial_data.point_store.tile_id(10_050_000, 4_025_000) % 16
    assert first_partition != second_partition
    assert (tmp_path / f"partition-{first_partition:02d}.bin").read_bytes() == (
        struct.pack("<ii", 20_000, 20_000)
    )
    assert (tmp_path / f"partition-{second_partition:02d}.bin").read_bytes() == (
        struct.pack("<ii", 10_050_000, 4_025_000)
    )


def test_compress_tile_points_sorts_raw_records() -> None:
    points = np.asarray([[1, 2], [0, 0], [-1, 3]], dtype="<i4")
    payload = spatial_data.point_store.compress_tile_points(points)
    decoded = spatial_data.point_store.decode_payload(payload)
    # The raw 8-byte representation sorts lexicographically by byte, which is not
    # numeric order: (0, 0) < (1, 2) < (-1, 3).
    assert decoded.tolist() == [[0, 0], [1, 2], [-1, 3]]


def test_compress_tile_points_keeps_original_record_order() -> None:
    points = np.asarray([[0, 1], [0, 0]], dtype="<i4")
    spatial_data.point_store.compress_tile_points(points)
    assert points.tolist() == [[0, 1], [0, 0]]


def test_process_partition_writes_one_row_per_tile(tmp_path: pathlib.Path) -> None:
    points = np.asarray([[0.2, 0.2], [0.3, 0.3], [100.5, 40.25]], dtype=float)
    with spatial_data.point_store.PartitionFiles(tmp_path) as partition_files:
        spatial_data.point_store.append_centroids_to_partitions(
            points,
            partition_files,
        )
    output = tmp_path / "points.sqlite"
    total = spatial_data.point_store.build_tiles_database(tmp_path, output)
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
    path = tmp_path / "points.sqlite"
    tests.helpers.factories.spatial_data.point_store.write_database(
        np.asarray([[0.2, 0.2]], dtype=float),
        path,
    )
    assert spatial_data.point_store.is_valid_database(path)


def test_is_valid_database_rejects_missing_file(tmp_path: pathlib.Path) -> None:
    assert not spatial_data.point_store.is_valid_database(
        tmp_path / "missing.sqlite",
    )


def test_is_valid_database_rejects_non_database_file(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "junk.sqlite"
    path.write_bytes(b"not a database")
    assert not spatial_data.point_store.is_valid_database(path)


def test_is_valid_database_rejects_outdated_tile_assignment(
    tmp_path: pathlib.Path,
) -> None:
    path = tmp_path / "points.sqlite"
    tests.helpers.factories.spatial_data.point_store.write_database(
        np.asarray([[0.0, 0.0]]),
        path,
    )
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "UPDATE metadata SET value = ? WHERE key = 'version'",
            ("2026-09-03",),
        )
        connection.commit()
    finally:
        connection.close()
    assert not spatial_data.point_store.is_valid_database(path)


def test_is_valid_database_rejects_unopenable_path(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fail = tests.helpers.doubles.errors.raising_stub(OSError("boom"))

    path = tmp_path / "points.sqlite"
    path.write_bytes(b"")
    monkeypatch.setattr(spatial_data.point_store.sqlite3, "connect", fail)
    assert not spatial_data.point_store.is_valid_database(path)


def test_is_valid_database_rejects_wrong_metadata(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "points.sqlite"
    tests.helpers.factories.spatial_data.point_store.write_database(
        np.asarray([[0.2, 0.2]], dtype=float),
        path,
    )
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "UPDATE metadata SET value = ? WHERE key = 'version'",
            ("2025-01-01",),
        )
        connection.commit()
    finally:
        connection.close()
    assert not spatial_data.point_store.is_valid_database(path)


def test_is_valid_database_rejects_wrong_schema(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "points.sqlite"
    tests.helpers.factories.spatial_data.point_store.write_database(
        np.asarray([[0.2, 0.2]], dtype=float),
        path,
    )
    connection = sqlite3.connect(path)
    try:
        connection.execute("DROP TABLE tiles")
        connection.commit()
    finally:
        connection.close()
    assert not spatial_data.point_store.is_valid_database(path)


def test_decode_payload_round_trips_encoded_points(tmp_path: pathlib.Path) -> None:
    points = np.asarray([[0.2, 0.2], [0.3, 0.3], [100.5, 40.25]], dtype=float)
    path = tmp_path / "points.sqlite"
    tests.helpers.factories.spatial_data.point_store.write_database(points, path)
    connection = sqlite3.connect(path)
    try:
        rows = connection.execute(
            "SELECT tile_id, payload FROM tiles ORDER BY tile_id",
        ).fetchall()
    finally:
        connection.close()
    decoded = np.concatenate([
        spatial_data.point_store.decode_payload(payload)
        for _identifier, payload in rows
    ])
    expected = spatial_data.point_store.quantize_centroids(points)
    assert sorted(map(tuple, decoded)) == sorted(map(tuple, expected))


def test_tile_ids_for_box_selects_single_tile() -> None:
    assert spatial_data.point_store.tile_ids_for_box((0.1, 0.1, 0.4, 0.4)) == [
        129_960,
    ]


def test_tile_ids_for_box_spans_multiple_tiles() -> None:
    assert spatial_data.point_store.tile_ids_for_box((0.1, 0.1, 0.6, 0.6)) == [
        180 * 720 + 360,
        180 * 720 + 361,
        181 * 720 + 360,
        181 * 720 + 361,
    ]


def test_tile_ids_for_box_includes_boundary_tiles() -> None:
    # A box ending exactly at 0.5° includes tile column 361, where the boundary point
    # itself lives.
    assert (
        spatial_data.point_store.tile_ids_for_box((0.4, 0.4, 0.5, 0.5))[-1]
        == 181 * 720 + 361
    )


@pytest.mark.parametrize(
    ("box", "expected"),
    [
        ((180.0, 0.0, 180.0, 0.0), [180 * 720 + 719]),
        ((0.0, 90.0, 0.0, 90.0), [359 * 720 + 360]),
        ((180.0, 90.0, 180.0, 90.0), [359 * 720 + 719]),
        ((180.1, 0.0, 180.2, 0.1), []),
        ((-180.2, 0.0, -180.1, 0.1), []),
        ((0.0, 90.1, 0.1, 90.2), []),
        ((0.0, -90.2, 0.1, -90.1), []),
    ],
)
def test_tile_ids_for_box_respects_geographic_domain_edges(
    box: tuple[float, float, float, float],
    expected: list[int],
) -> None:
    assert spatial_data.point_store.tile_ids_for_box(box) == expected


def test_points_within_box_filters_by_encoded_bounds() -> None:
    points = np.asarray([[0, 0], [1, 1], [-1, 1], [1, -1]], dtype="<i4")
    filtered = spatial_data.point_store.points_within_box(points, (0, 0, 1, 1))
    assert filtered.tolist() == [[0, 0], [1, 1]]


def test_point_counts_within_counts_points_across_tiles(
    tmp_path: pathlib.Path,
) -> None:
    points = np.asarray(
        [[0.2, 0.2], [0.3, 0.3], [100.5, 40.25], [101.0, 41.0]],
        dtype=float,
    )
    path = tmp_path / "points.sqlite"
    tests.helpers.factories.spatial_data.point_store.write_database(points, path)
    counts = spatial_data.point_store.point_counts_within(
        [
            shapely.geometry.box(0.0, 0.0, 1.0, 1.0),
            shapely.geometry.box(100.0, 40.0, 101.5, 41.5),
        ],
        path,
    )
    assert counts == [2, 2]


def test_point_counts_within_finds_points_quantized_onto_geographic_edges(
    tmp_path: pathlib.Path,
) -> None:
    path = tmp_path / "points.sqlite"
    tests.helpers.factories.spatial_data.point_store.write_database(
        np.asarray([[179.999999, 0], [0, 89.999999]]),
        path,
    )
    queries = [shapely.box(179.9, -0.1, 180.1, 0.1), shapely.box(-0.1, 89.9, 0.1, 90.1)]
    assert spatial_data.point_store.point_counts_within(queries, path) == [1, 1]


def test_point_counts_within_includes_points_on_upper_boundary(
    tmp_path: pathlib.Path,
) -> None:
    points = np.asarray([[0.5, 0.5]], dtype=float)
    path = tmp_path / "points.sqlite"
    tests.helpers.factories.spatial_data.point_store.write_database(points, path)
    # The box filter and tile selection include a point exactly on the tile boundary,
    # Exact containment excludes a point on the query geometry's boundary; a box
    # strictly containing the point counts it.
    counts = spatial_data.point_store.point_counts_within(
        [shapely.geometry.box(0.4, 0.4, 0.5, 0.5)],
        path,
    )
    assert counts == [0]
    counts = spatial_data.point_store.point_counts_within(
        [shapely.geometry.box(0.4, 0.4, 0.51, 0.51)],
        path,
    )
    assert counts == [1]
    counts = spatial_data.point_store.point_counts_within(
        [shapely.geometry.box(0.4, 0.4, 0.5, 0.5)],
        path,
    )
    assert counts == [0]


def test_point_counts_within_tests_exact_containment(tmp_path: pathlib.Path) -> None:
    points = np.asarray([[0.2, 0.1], [0.1, 0.2]], dtype=float)
    path = tmp_path / "points.sqlite"
    tests.helpers.factories.spatial_data.point_store.write_database(points, path)
    triangle = shapely.geometry.Polygon([(0, 0), (1, 0), (1, 1)])
    counts = spatial_data.point_store.point_counts_within([triangle], path)
    assert counts == [1]


def test_point_counts_within_counts_point_for_each_containing_geometry(
    tmp_path: pathlib.Path,
) -> None:
    points = np.asarray([[0.5, 0.5]], dtype=float)
    path = tmp_path / "points.sqlite"
    tests.helpers.factories.spatial_data.point_store.write_database(points, path)
    counts = spatial_data.point_store.point_counts_within(
        [
            shapely.geometry.box(0.0, 0.0, 1.0, 1.0),
            shapely.geometry.box(0.25, 0.25, 0.75, 0.75),
        ],
        path,
    )
    assert counts == [1, 1]


def test_point_counts_within_returns_zero_without_geometry(
    tmp_path: pathlib.Path,
) -> None:
    path = tmp_path / "points.sqlite"
    tests.helpers.factories.spatial_data.point_store.write_database(
        np.asarray([[0.2, 0.2]], dtype=float),
        path,
    )
    counts = spatial_data.point_store.point_counts_within(
        [None, shapely.geometry.Polygon()],
        path,
    )
    assert counts == [0, 0]


def test_point_counts_within_counts_duplicate_coordinates(
    tmp_path: pathlib.Path,
) -> None:
    path = tmp_path / "points.sqlite"
    tests.helpers.factories.spatial_data.point_store.write_database(
        np.asarray([[0.2, 0.2], [0.2, 0.2]]),
        path,
    )
    assert spatial_data.point_store.point_counts_within(
        [shapely.geometry.box(0.1, 0.1, 0.3, 0.3)],
        path,
    ) == [2]


def test_point_counts_within_respects_multipolygon_holes(
    tmp_path: pathlib.Path,
) -> None:
    path = tmp_path / "points.sqlite"
    tests.helpers.factories.spatial_data.point_store.write_database(
        np.asarray([[0.1, 0.1], [0.2, 0.3], [0.3, 0.3], [0.7, 0.3], [0.9, 0.3]]),
        path,
    )
    geometry = shapely.geometry.MultiPolygon([
        shapely.geometry.Polygon(
            shapely.geometry.box(0.0, 0.0, 0.5, 0.5).exterior,
            [shapely.geometry.box(0.2, 0.2, 0.4, 0.4).exterior],
        ),
        shapely.geometry.box(0.6, 0.2, 0.8, 0.4),
    ])
    assert spatial_data.point_store.point_counts_within([geometry], path) == [2]


def test_point_counts_within_reads_shared_tile_once(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "points.sqlite"
    tests.helpers.factories.spatial_data.point_store.write_database(
        np.asarray([[0.2, 0.2]]),
        path,
    )
    identifiers: list[int] = []
    read_tile_points = spatial_data.point_store.read_tile_points

    read = tests.helpers.doubles.spatial_data.point_store.make_tile_read_recorder(
        identifiers=identifiers,
        read_tile_points=read_tile_points,
    )

    monkeypatch.setattr(spatial_data.point_store, "read_tile_points", read)
    spatial_data.point_store.point_counts_within(
        [
            shapely.geometry.box(0.1, 0.1, 0.3, 0.3),
            shapely.geometry.box(0.1, 0.1, 0.4, 0.4),
        ],
        path,
    )
    assert identifiers == spatial_data.point_store.tile_ids_for_box((
        0.1,
        0.1,
        0.4,
        0.4,
    ))


def test_point_counts_within_releases_prepared_geometry(
    tmp_path: pathlib.Path,
) -> None:
    path = tmp_path / "points.sqlite"
    tests.helpers.factories.spatial_data.point_store.write_database(
        np.asarray([[0.2, 0.2]]),
        path,
    )
    geometry = shapely.geometry.box(0.1, 0.1, 0.3, 0.3)
    shapely.prepare(geometry)
    spatial_data.point_store.point_counts_within([geometry], path)
    assert not shapely.is_prepared(geometry)


def test_point_counts_within_skips_geometries_without_candidates(
    tmp_path: pathlib.Path,
) -> None:
    path = tmp_path / "points.sqlite"
    tests.helpers.factories.spatial_data.point_store.write_database(
        np.asarray([[0.2, 0.2]], dtype=float),
        path,
    )
    counts = spatial_data.point_store.point_counts_within(
        [shapely.geometry.box(200.0, 200.0, 201.0, 201.0)],
        path,
    )
    assert counts == [0]


def test_point_counts_within_returns_zero_without_database(
    tmp_path: pathlib.Path,
) -> None:
    counts = spatial_data.point_store.point_counts_within(
        [shapely.geometry.box(0.0, 0.0, 1.0, 1.0)],
        tmp_path / "missing.sqlite",
    )
    assert counts == [0]


def test_point_counts_within_excludes_points_outside_envelope_in_same_tile(
    tmp_path: pathlib.Path,
) -> None:
    path = tmp_path / "points.sqlite"
    tests.helpers.factories.spatial_data.point_store.write_database(
        np.asarray([[0.2, 0.2]]),
        path,
    )
    counts = spatial_data.point_store.point_counts_within(
        [shapely.geometry.box(0.3, 0.3, 0.4, 0.4)],
        path,
    )
    assert counts == [0]
