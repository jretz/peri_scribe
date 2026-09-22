"""Compact WGS84 point storage supports bounded-memory spatial counting.

Coordinates use signed integer pairs at 1e-5 degree resolution, partitioned into 0.5
degree tiles and compressed per tile. Query envelopes select tiles before exact polygon
containment, counting duplicate coordinates and excluding polygon boundaries.

The on-disk ``building_count`` column is part of the format contract; point payloads
carry no domain attributes and can represent any collection of WGS84 points.
"""

from __future__ import annotations

import collections
import compression.zstd
import pathlib
import sqlite3
import threading
import typing

import numpy as np
import shapely


# The coordinate scale and 0.5° tile layout of the compact point database.
# Coordinates are stored as signed little-endian int32 values in units of 1e-5 degrees,
# so an encoded longitude/latitude of one covers 0.00001°.

COORDINATE_SCALE = 100_000

TILE_SIZE_DEGREES = 0.5

# The encoded coordinate at the grid's origin (-180°, -90°) and the encoded span of one
# tile, matching the coordinate scale and tile size above.
LONGITUDE_OFFSET = 18_000_000
LATITUDE_OFFSET = 9_000_000
TILE_STEPS = 50_000

# The number of 0.5° tiles across the world's longitude and latitude spans.
TILE_COLUMNS = 720
TILE_ROWS = 360

RECORD_SIZE_BYTES = 8

# The number of temporary partition files; each partition holds every record whose tile
# id is congruent to the partition number modulo this count.
PARTITION_COUNT = 16

# The database format version, recorded in the metadata and checked on read.
FORMAT_VERSION = "2026-09-15"


TILES_TABLE_SCHEMA = (
    "CREATE TABLE tiles (\n"
    "    tile_id        INTEGER PRIMARY KEY,\n"
    "    building_count INTEGER NOT NULL,\n"
    "    payload        BLOB NOT NULL\n"
    ") WITHOUT ROWID"
)


DATABASE_SCHEMA = (
    "CREATE TABLE metadata (\n"
    "    key   TEXT PRIMARY KEY,\n"
    "    value TEXT NOT NULL\n"
    ");\n"
    f"{TILES_TABLE_SCHEMA};"
)


def expected_metadata() -> dict[str, str]:
    """Return the metadata every compact point database must hold.

    Returns:
        The expected key-to-value metadata mapping.
    """
    return {
        "version": FORMAT_VERSION,
        "crs": "EPSG:4326",
        "axis_order": "longitude,latitude",
        "coordinate_units": "degrees",
        "coordinate_scale": str(COORDINATE_SCALE),
        "coordinate_integer_type": "signed-int32",
        "coordinate_byte_order": "little-endian",
        "tile_size_degrees": str(TILE_SIZE_DEGREES),
        "record_size_bytes": str(RECORD_SIZE_BYTES),
    }


def encode_longitude(longitude: float) -> int:
    """Return *longitude* quantized to the database's integer coordinates.

    Args:
        longitude: The longitude in degrees.

    Returns:
        The encoded longitude.

    Examples:
        >>> encode_longitude(-122.5)
        -12250000
    """
    return round(longitude * COORDINATE_SCALE)


def encode_latitude(latitude: float) -> int:
    """Return *latitude* quantized to the database's integer coordinates.

    Args:
        latitude: The latitude in degrees.

    Returns:
        The encoded latitude.

    Examples:
        >>> encode_latitude(37.75)
        3775000
    """
    return round(latitude * COORDINATE_SCALE)


def quantize_centroids(centroids: np.ndarray) -> np.ndarray:
    """Return *centroids* quantized to the database's integer coordinates.

    Args:
        centroids: The ``(n, 2)`` longitude/latitude pairs in degrees.

    Returns:
        The ``(n, 2)`` int32 encoded coordinate pairs.
    """
    return np.round(centroids * COORDINATE_SCALE).astype("<i4")


def tile_id(encoded_longitude: int, encoded_latitude: int) -> int:
    """Return the 0.5° tile id containing the encoded coordinates.

    The easternmost column and northernmost row include the geographic domain's upper
    endpoints, since quantization can round a coordinate onto 180° or 90°.

    Args:
        encoded_longitude: The encoded longitude.
        encoded_latitude: The encoded latitude.

    Returns:
        The tile id.

    Examples:
        >>> tile_id(0, 0)
        129960
    """
    column = min((encoded_longitude + LONGITUDE_OFFSET) // TILE_STEPS, TILE_COLUMNS - 1)
    row = min((encoded_latitude + LATITUDE_OFFSET) // TILE_STEPS, TILE_ROWS - 1)
    return row * TILE_COLUMNS + column


def tile_ids(encoded: np.ndarray) -> np.ndarray:
    """Return each encoded coordinate pair's tile id, vectorized.

    The arithmetic stays in int32 (the encoded offsets and tile ids fit comfortably), so
    a chunk's tile ids cost half the memory of an int64 pass.

    Args:
        encoded: The ``(n, 2)`` int32 encoded coordinate pairs.

    Returns:
        The ``(n,)`` tile ids.
    """
    columns = (encoded[:, 0] + np.int32(LONGITUDE_OFFSET)) // TILE_STEPS
    rows = (encoded[:, 1] + np.int32(LATITUDE_OFFSET)) // TILE_STEPS
    np.minimum(columns, TILE_COLUMNS - 1, out=columns)
    np.minimum(rows, TILE_ROWS - 1, out=rows)
    return rows * np.int32(TILE_COLUMNS) + columns


def partition_ids(identifiers: np.ndarray) -> np.ndarray:
    """Return each tile id's partition file, vectorized.

    Args:
        identifiers: The ``(n,)`` tile ids.

    Returns:
        The ``(n,)`` partition numbers.
    """
    return identifiers % PARTITION_COUNT


def partition_filename(partition: int) -> str:
    """Return the temporary partition file's name for *partition*.

    Args:
        partition: The partition number.

    Returns:
        The file name.

    Examples:
        >>> partition_filename(3)
        'partition-03.bin'
    """
    return f"partition-{partition:02d}.bin"


def tile_ids_for_box(box: tuple[float, float, float, float]) -> list[int]:
    """Return the tile ids whose encoded ranges intersect the query *box*.

    *box* is ``(minimum_longitude, minimum_latitude, maximum_longitude,
    maximum_latitude)`` in degrees. A tile is included when its encoded coordinate range
    overlaps the box's encoded coordinate range, so every point whose encoded
    coordinates lie in the box is found in one of the returned tiles.

    Args:
        box: The query box in degrees.

    Returns:
        The intersecting tile ids, ordered by row then column.
    """
    minimum_x, minimum_y, maximum_x, maximum_y = encoded_box(box)
    if (
        minimum_x > LONGITUDE_OFFSET
        or maximum_x < -LONGITUDE_OFFSET
        or minimum_y > LATITUDE_OFFSET
        or maximum_y < -LATITUDE_OFFSET
    ):
        return []
    first_row, first_column = divmod(
        tile_id(max(minimum_x, -LONGITUDE_OFFSET), max(minimum_y, -LATITUDE_OFFSET)),
        TILE_COLUMNS,
    )
    last_row, last_column = divmod(
        tile_id(min(maximum_x, LONGITUDE_OFFSET), min(maximum_y, LATITUDE_OFFSET)),
        TILE_COLUMNS,
    )
    return [
        row * TILE_COLUMNS + column
        for row in range(first_row, last_row + 1)
        for column in range(first_column, last_column + 1)
    ]


def encoded_box(box: tuple[float, float, float, float]) -> tuple[int, int, int, int]:
    """Return *box*'s corners quantized to the database's integer coordinates.

    Args:
        box: The query box in degrees.

    Returns:
        The box's encoded ``(minimum_x, minimum_y, maximum_x, maximum_y)``.
    """
    minimum_longitude, minimum_latitude, maximum_longitude, maximum_latitude = box
    return (
        encode_longitude(minimum_longitude),
        encode_latitude(minimum_latitude),
        encode_longitude(maximum_longitude),
        encode_latitude(maximum_latitude),
    )


def points_within_box(points: np.ndarray, box: tuple[int, int, int, int]) -> np.ndarray:
    """Return the points whose encoded coordinates lie within *box*.

    Args:
        points: The ``(n, 2)`` int32 encoded coordinate pairs.
        box: The encoded ``(minimum_x, minimum_y, maximum_x, maximum_y)``.

    Returns:
        The points inside the box, in their original order.
    """
    minimum_x, minimum_y, maximum_x, maximum_y = box
    return points[
        (points[:, 0] >= minimum_x)
        & (points[:, 0] <= maximum_x)
        & (points[:, 1] >= minimum_y)
        & (points[:, 1] <= maximum_y)
    ]


def compress_tile_points(points: np.ndarray) -> bytes:
    """Return the compressed payload for one tile's *points*.

    The points are sorted by their raw 8-byte representation, so identical coordinate
    prefixes become adjacent and the payload compresses far better than spatial order
    would. The sorted records are then zstd-compressed at level 2, which keeps the
    database build fast while still shrinking the payload substantially.

    Args:
        points: The tile's ``(n, 2)`` int32 encoded coordinate pairs.

    Returns:
        The compressed payload bytes.
    """
    records = np.sort(points.view("V8").reshape(-1))
    return compression.zstd.compress(records, level=2)


def decode_payload(payload: bytes) -> np.ndarray:
    """Return the ``(n, 2)`` int32 points held in a compressed tile payload.

    Args:
        payload: The compressed payload bytes.

    Returns:
        The decoded encoded coordinate pairs.
    """
    return np.frombuffer(compression.zstd.decompress(payload), dtype="<i4").reshape(
        -1,
        2,
    )


class PartitionFiles:
    """The temporary binary partition files being accumulated.

    Each of the sixteen files holds only concatenated 8-byte records: no headers,
    delimiters, tile ids, or SQLite row structures. Records are appended across every
    input stream, so all records of a tile always reach the same partition, and the
    caller manages the partition directory's lifetime.
    """

    def __init__(self, directory: pathlib.Path) -> None:
        """Prepare partition files for collecting centroid records across archives.

        Args:
            directory: The existing directory where partition files are accumulated.
        """
        self.directory = directory
        self.writing = threading.Lock()
        for partition in range(PARTITION_COUNT):
            (directory / partition_filename(partition)).touch()

    def append(self, partition: int, records: collections.abc.Buffer) -> None:
        """Append *records* to *partition*'s file.

        Args:
            partition: The partition number.
            records: The concatenated record bytes, as any buffer of raw bytes.
        """
        with (
            self.writing,
            (self.directory / partition_filename(partition)).open("ab") as file,
        ):
            file.write(records)

    def __enter__(self) -> typing.Self:
        """Return the writer as its own context manager.

        Returns:
            The writer itself.
        """
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        """Release nothing; the files are appended and closed per write.

        Args:
            _type: The exception type supplied by the context manager, or None; unused
                because no handles remain open.
            _value: The exception instance, or None; unused and not suppressed.
            _traceback: The exception traceback, or None; unused.
        """


def append_centroids_to_partitions(
    centroids: np.ndarray,
    partition_files: PartitionFiles,
) -> None:
    """Quantize *centroids* and append their records to the partition files.

    Args:
        centroids: The ``(n, 2)`` longitude/latitude pairs in degrees.
        partition_files: The partition files to append to.
    """
    encoded = quantize_centroids(centroids)
    partitions = partition_ids(tile_ids(encoded))
    for partition in range(PARTITION_COUNT):
        records = encoded[partitions == partition]
        if records.size:
            partition_files.append(partition, records)


def process_partition(
    partition_path: pathlib.Path,
    connection: sqlite3.Connection,
) -> int:
    """Read *partition_path* and write one row per complete tile into *connection*.

    The partition's records are read into NumPy, their tile ids are computed in one
    vectorized pass, and the records are sorted by tile id so each tile's records become
    contiguous; each complete tile is then sorted by raw record bytes and written as a
    single compressed row. Because partition assignment used ``tile_id % 16``, every
    tile is fully contained in this one partition and is written exactly once.
    Within-tile record order does not matter (the payload sort reorders it), so the
    default quicksort is used instead of a stable sort: stable integer sorts use a
    full-size radix temp, doubling the sort's memory.

    Args:
        partition_path: The partition file's path.
        connection: The database connection to write into.

    Returns:
        The number of records processed.
    """
    points = np.fromfile(partition_path, dtype="<i4").reshape(-1, 2)
    if points.size == 0:
        return 0
    identifiers = tile_ids(points)
    order = np.argsort(identifiers)
    ordered_identifiers = identifiers[order]
    del identifiers
    boundaries = np.flatnonzero(ordered_identifiers[1:] != ordered_identifiers[:-1]) + 1
    starts = np.r_[0, boundaries]
    ends = np.r_[boundaries, len(points)]
    for start, end in zip(starts, ends, strict=True):
        connection.execute(
            "INSERT INTO tiles(tile_id, building_count, payload) VALUES (?, ?, ?)",
            (
                int(ordered_identifiers[start]),
                int(end - start),
                compress_tile_points(points[order[start:end]]),
            ),
        )
    return len(points)


def build_tiles_database(
    partition_directory: pathlib.Path,
    output: pathlib.Path,
) -> int:
    """Build the compact point database at *output* from the partition files.

    The database's schema and metadata are created, then each partition file is
    processed one at a time and its tiles are written. The output holds one row per
    occupied tile.

    Args:
        partition_directory: The directory holding the sixteen partition files.
        output: The database path to write.

    Returns:
        The total number of point records written.
    """
    output.unlink(missing_ok=True)
    connection = sqlite3.connect(output)
    try:
        connection.executescript(DATABASE_SCHEMA)
        connection.executemany(
            "INSERT INTO metadata(key, value) VALUES (?, ?)",
            expected_metadata().items(),
        )
        point_count = 0
        for partition in range(PARTITION_COUNT):
            point_count += process_partition(
                partition_directory / partition_filename(partition),
                connection,
            )
        connection.commit()
        return point_count
    finally:
        connection.close()


def normalized_sql(statement: str) -> str:
    """Return *statement* with whitespace normalized for schema comparison.

    Args:
        statement: The SQL statement text.

    Returns:
        The statement with runs of whitespace collapsed to single spaces.

    Examples:
        >>> normalized_sql("CREATE  TABLE   tiles (id INTEGER)")
        'CREATE TABLE tiles (id INTEGER)'
    """
    return " ".join(statement.split())


def is_valid_database(path: pathlib.Path) -> bool:
    """Return True when *path* holds a valid compact point database.

    The database must hold the expected ``metadata`` and ``tiles`` tables, the exact
    expected metadata mapping, and the exact expected tiles schema. A database written
    by a different format version is therefore detected and regenerated.

    Args:
        path: The database path.

    Returns:
        True when the database matches the expected format.
    """
    if not path.is_file():
        return False
    try:
        connection = sqlite3.connect(path)
    except OSError, sqlite3.Error:
        return False
    try:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'",
            )
        }
        if not {"metadata", "tiles"} <= tables:
            return False
        metadata = dict(connection.execute("SELECT key, value FROM metadata"))
        if metadata != expected_metadata():
            return False
        tiles_schema = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'tiles'",
        ).fetchone()
        return tiles_schema is not None and normalized_sql(
            tiles_schema[0],
        ) == normalized_sql(TILES_TABLE_SCHEMA)
    except sqlite3.Error:
        return False
    finally:
        connection.close()


def read_tile_points(connection: sqlite3.Connection, tile_id: int) -> np.ndarray | None:
    """Return a tile's decoded points from *connection*, or None when absent.

    Args:
        connection: The database connection.
        tile_id: The tile id to read.

    Returns:
        The tile's ``(n, 2)`` int32 encoded coordinate pairs, or None when the database
        holds no row for the tile.
    """
    row = connection.execute(
        "SELECT payload FROM tiles WHERE tile_id = ?",
        (tile_id,),
    ).fetchone()
    if row is None:
        return None
    return decode_payload(row[0])


def point_counts_within(
    geometries: list[shapely.Geometry | None],
    path: pathlib.Path,
) -> list[int]:
    """Return how many points lie within each query geometry.

    Grouping queries by tile avoids repeated reads and decompression for nearby queries.
    Only one tile's points and one query's candidates need to be retained at a time.
    Envelope filtering preserves every possible match, and exact containment excludes
    polygon boundaries while counting duplicate point coordinates separately.
    Prepared geometry is released after each containment test to bound its memory.

    Args:
        geometries: The query geometries in WGS84, or None.
        path: The compact point database.

    Returns:
        One point count per geometry, aligned with *geometries*.
    """
    valid = [
        (index, geometry)
        for index, geometry in enumerate(geometries)
        if geometry is not None and not geometry.is_empty
    ]
    counts = [0] * len(geometries)
    if not valid:
        return counts
    if not path.is_file():
        return counts
    queries: collections.defaultdict[
        int,
        list[tuple[int, shapely.Geometry, tuple[int, int, int, int]]],
    ] = collections.defaultdict(list)
    for index, geometry in valid:
        bounds = geometry.bounds
        encoded = encoded_box(bounds)
        for identifier in tile_ids_for_box(bounds):
            queries[identifier].append((index, geometry, encoded))
    connection = sqlite3.connect(path)
    try:
        for identifier, tile_queries in queries.items():
            tile_points = read_tile_points(connection, identifier)
            if tile_points is None:
                continue
            for index, geometry, encoded in tile_queries:
                candidates = points_within_box(tile_points, encoded)
                if not candidates.size:
                    continue
                try:
                    counts[index] += int(
                        np.count_nonzero(
                            shapely.contains_xy(
                                geometry,
                                candidates[:, 0] / COORDINATE_SCALE,
                                candidates[:, 1] / COORDINATE_SCALE,
                            ),
                        ),
                    )
                finally:
                    shapely.destroy_prepared(geometry)
    finally:
        connection.close()
    return counts
