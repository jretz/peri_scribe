"""Exact encoded-coordinate fixtures preserve tile boundaries and point multiplicity."""

import itertools
import pathlib
import sqlite3

import numpy as np

import spatial_data.point_store


Point = tuple[int, int]
Box = tuple[int, int, int, int]
LONGITUDE_LIMIT = 18_000_000
LATITUDE_LIMIT = 9_000_000


def offset(point: Point) -> str:
    """Transport valid geographic coordinates as nonnegative offsets from the origin.

    Args:
        point: Signed coordinates in the production integer encoding.

    Returns:
        The coordinate pair consumed by Lean's integer grid.
    """
    longitude, latitude = point
    return (
        f"{longitude + spatial_data.point_store.LONGITUDE_OFFSET},"
        f"{latitude + spatial_data.point_store.LATITUDE_OFFSET}"
    )


def coordinate_boundaries() -> list[Point]:
    """Cover both sides and the exact value of every world-grid axis boundary.

    Returns:
        Valid encoded positions spanning all columns, rows, and geographic endpoints.
    """
    positions = set()
    for longitude in range(-18_000_000, 18_000_001, 50_000):
        for delta in (-1, 0, 1):
            value = longitude + delta
            if -LONGITUDE_LIMIT <= value <= LONGITUDE_LIMIT:
                positions.add((value, 0))
    for latitude in range(-9_000_000, 9_000_001, 50_000):
        for delta in (-1, 0, 1):
            value = latitude + delta
            if -LATITUDE_LIMIT <= value <= LATITUDE_LIMIT:
                positions.add((0, value))
    positions.update(
        itertools.product((-18_000_000, 18_000_000), (-9_000_000, 9_000_000)),
    )
    return sorted(positions)


def query_cases() -> tuple[list[Point], list[Box]]:
    """Mix duplicates, negative coordinates, endpoint clamps, and empty matches.

    Returns:
        One shared point bag and narrow queries near different geographic regions.
    """
    positions = []
    boxes = []
    for longitude, latitude in (
        (-18_000_000, -9_000_000),
        (18_000_000, 9_000_000),
        (-12_200_000, 3_750_000),
        (-15_000_000, 6_000_000),
        (0, 0),
        (50_000, -50_000),
    ):
        for horizontal, vertical in itertools.product(
            (-50_001, -1, 0, 1, 50_001),
            repeat=2,
        ):
            point = longitude + horizontal, latitude + vertical
            if (
                -LONGITUDE_LIMIT <= point[0] <= LONGITUDE_LIMIT
                and -LATITUDE_LIMIT <= point[1] <= LATITUDE_LIMIT
            ):
                positions.extend([point] * (1 + (horizontal == vertical)))
        for left, right in itertools.combinations((-50_002, -1, 0, 1, 50_002), 2):
            boxes.append((
                max(-18_000_000, longitude + left),
                max(-9_000_000, latitude + left),
                min(18_000_000, longitude + right),
                min(9_000_000, latitude + right),
            ))
    return positions, [box for box in boxes if box[0] < box[2] and box[1] < box[3]]


def degrees(box: Box) -> tuple[float, float, float, float]:
    """Use the stored coordinate basis for production geometry construction.

    Args:
        box: Query limits in signed integer units.

    Returns:
        Geographic coordinates for Shapely and the production tile enumerator.
    """
    scale = spatial_data.point_store.COORDINATE_SCALE
    return box[0] / scale, box[1] / scale, box[2] / scale, box[3] / scale


def database(path: pathlib.Path, points: list[Point]) -> None:
    """Write a valid isolated tile database without external feeds or cached data.

    Args:
        path: Per-test temporary database destination.
        points: A bag of coordinates whose duplicates must remain independent records.
    """
    encoded = np.array(points, dtype="<i4")
    identifiers = spatial_data.point_store.tile_ids(encoded)
    with sqlite3.connect(path) as connection:
        connection.executescript(spatial_data.point_store.DATABASE_SCHEMA)
        connection.executemany(
            "INSERT INTO metadata(key, value) VALUES (?, ?)",
            spatial_data.point_store.expected_metadata().items(),
        )
        for identifier in np.unique(identifiers):
            members = encoded[identifiers == identifier]
            connection.execute(
                "INSERT INTO tiles(tile_id, building_count, payload) VALUES (?, ?, ?)",
                (
                    int(identifier),
                    len(members),
                    spatial_data.point_store.compress_tile_points(members),
                ),
            )
