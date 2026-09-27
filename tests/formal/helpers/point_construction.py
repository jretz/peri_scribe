"""Finite encoded point bags for the proved partition/merge construction."""

from __future__ import annotations

import collections
import concurrent.futures
import pathlib
import sqlite3

import numpy as np

import spatial_data.point_store
import tests.formal.helpers.oracle
import tests.formal.helpers.spatial_index


type Point = tuple[int, int]


def cases() -> list[list[Point]]:
    """Include multiplicities, endpoints, all partition residues and tile collisions.

    Returns:
        Encoded point bags independent of production partition and tile functions.
    """
    points = [(-18_000_000 + column * 50_000, -9_000_000) for column in range(33)]
    points.extend([
        (-18_000_000, -9_000_000),
        (18_000_000, 9_000_000),
        (17_999_999, 8_999_999),
        (0, 0),
        (0, 0),
        (0, 0),
        (-1, -1),
        (49_999, 49_999),
        (50_000, 50_000),
        (50_001, 50_001),
    ])
    return [
        [],
        [(0, 0)],
        [(0, 0), (0, 0)],
        points,
        list(reversed(points)),
        points[7:] + points[:7],
    ]


def decoded(values: tuple[int, ...]) -> collections.Counter[Point]:
    """Decode oracle coordinates while retaining duplicate point multiplicity.

    Args:
        values: Flattened offset coordinate pairs from Lean.

    Returns:
        Signed encoded coordinate counts.
    """
    assert len(values) % 2 == 0
    return collections.Counter(
        (longitude - 18_000_000, latitude - 9_000_000)
        for longitude, latitude in zip(values[::2], values[1::2], strict=True)
    )


def replay(points: list[Point], chunk_size: int, directory: pathlib.Path) -> None:
    """Compare partitions, SQLite tile counts and compressed payload bags with Lean.

    Args:
        points: Encoded input records, including duplicates.
        chunk_size: The arbitrary upstream conversion chunk boundary.
        directory: Isolated construction directory.
    """
    directory.mkdir()
    vectors = " ".join(
        tests.formal.helpers.spatial_index.offset(point) for point in points
    )
    suffix = " " + vectors if vectors else ""
    partitions = tests.formal.helpers.oracle.evaluate(
        [f"partition {identifier}{suffix}" for identifier in range(16)],
        executable="oracleIngestion",
    )
    identifiers = tests.formal.helpers.oracle.evaluate(
        [f"tiles{suffix}"],
        executable="oracleIngestion",
    )[0]
    tiles = (
        tests.formal.helpers.oracle.evaluate(
            [f"build {identifier}{suffix}" for identifier in identifiers],
            executable="oracleIngestion",
        )
        if identifiers
        else []
    )
    partition_directory = directory / "partitions"
    partition_directory.mkdir()
    with (
        spatial_data.point_store.PartitionFiles(partition_directory) as files,
        concurrent.futures.ThreadPoolExecutor(max_workers=3) as workers,
    ):
        pending = [
            workers.submit(
                spatial_data.point_store.append_centroids_to_partitions,
                np.asarray(points[start : start + chunk_size], dtype=float) / 100_000,
                files,
            )
            for start in range(0, len(points), chunk_size)
        ]
        for result in pending:
            result.result(timeout=10)
    for identifier, expected in enumerate(partitions):
        path = partition_directory / spatial_data.point_store.partition_filename(
            identifier,
        )
        actual = np.fromfile(path, dtype="<i4").reshape(-1, 2)
        assert collections.Counter(map(tuple, actual.tolist())) == decoded(expected)
    output = directory / "buildings.sqlite"
    assert spatial_data.point_store.build_tiles_database(
        partition_directory,
        output,
    ) == len(points)
    assert spatial_data.point_store.is_valid_database(output)
    with sqlite3.connect(output) as connection:
        rows = connection.execute(
            "SELECT tile_id, building_count, payload FROM tiles",
        ).fetchall()
    assert {row[0] for row in rows} == set(identifiers)
    expectations = dict(zip(identifiers, tiles, strict=True))
    for identifier, count, payload in rows:
        expected = decoded(expectations[identifier])
        actual = spatial_data.point_store.decode_payload(payload)
        assert count == expected.total() == len(actual)
        assert collections.Counter(map(tuple, actual.tolist())) == expected
