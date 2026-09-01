"""The streaming compact buildings database and its reader.

The building-footprint source stores only each footprint's centroid: no attributes, in a
database built for fast spatial counting rather than general-purpose GIS. Each centroid
is quantized to an integer coordinate pair (``round(longitude * 100000)``,
``round(latitude * 100000)``) and written as an 8-byte little-endian record. The world
is divided into 0.5° tiles, and every record belongs to the tile holding its encoded
coordinate. A 16-way partition on the tile id spreads the records of one archive across
sixteen temporary binary files that are retained across every state's archive, so all
records of a tile are collected into the same partition no matter which state they came
from; each partition is then processed one at a time, well under the memory budget. A
tile's records are sorted by their raw 8-byte representation (which groups identical
coordinate prefixes and compresses far better than spatial order) and the sorted payload
is zlib-compressed into one ``tiles`` row per occupied tile. The database holds metadata
describing the coordinate encoding, and the reader selects the tiles intersecting a
query envelope, decompresses their payloads into NumPy arrays, filters by the envelope
with NumPy, and tests exact polygon containment only for the remaining points, so
building counts never touch GeoPandas, GeoPackage geometry blobs, or an R-Tree index.

The archive's bytes arrive from the HTTP response, ``stream_unzip`` decompresses the
GeoJSON member as they arrive, and each parsed geometry passes through the bounded
centroid conversion. Neither the archive nor its GeoJSON is ever written to disk, and
the database is written to a temporary path and atomically renamed into place only after
validation succeeds, so an existing valid database survives any download or generation
failure.
"""

from __future__ import annotations

import collections
import pathlib
import sqlite3
import struct
import tempfile
import typing
import zlib

import ijson
import numpy as np
import requests
import shapely
import stream_unzip
import structlog

import peri_scribe.exceptions
import peri_scribe.fires.centroid_math
import peri_scribe.fires.centroid_streaming
import peri_scribe.sources.downloading
import peri_scribe.sources.external_sources


logger = structlog.get_logger()


# The coordinate scale and 0.5° tile layout of the compact buildings database.
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
BUILDINGS_VERSION = "2026-08-31"

REQUEST_TIMEOUT_SECONDS = 60

DOWNLOAD_CHUNK_SIZE = 1024 * 1024


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
    """Return the metadata every compact buildings database must hold.

    Returns:
        The expected key-to-value metadata mapping.
    """
    return {
        "version": BUILDINGS_VERSION,
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
    """
    return round(longitude * COORDINATE_SCALE)


def encode_latitude(latitude: float) -> int:
    """Return *latitude* quantized to the database's integer coordinates.

    Args:
        latitude: The latitude in degrees.

    Returns:
        The encoded latitude.
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


def encode_record(longitude: float, latitude: float) -> bytes:
    """Return the 8-byte little-endian record for the coordinate pair.

    Args:
        longitude: The longitude in degrees.
        latitude: The latitude in degrees.

    Returns:
        The record's eight bytes.
    """
    return struct.pack(
        "<ii",
        encode_longitude(longitude),
        encode_latitude(latitude),
    )


def tile_id(encoded_longitude: int, encoded_latitude: int) -> int:
    """Return the 0.5° tile id containing the encoded coordinates.

    Args:
        encoded_longitude: The encoded longitude.
        encoded_latitude: The encoded latitude.

    Returns:
        The tile id.
    """
    column = (encoded_longitude + LONGITUDE_OFFSET) // TILE_STEPS
    row = (encoded_latitude + LATITUDE_OFFSET) // TILE_STEPS
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
    return rows * np.int32(TILE_COLUMNS) + columns


def partition_id(tile_id: int) -> int:
    """Return the partition file holding a record of *tile_id*.

    Args:
        tile_id: The tile id.

    Returns:
        The partition number, from 0 to ``PARTITION_COUNT - 1``.
    """
    return tile_id % PARTITION_COUNT


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
    minimum_longitude, minimum_latitude, maximum_longitude, maximum_latitude = box
    first_column = max(
        0,
        (encode_longitude(minimum_longitude) + LONGITUDE_OFFSET) // TILE_STEPS,
    )
    last_column = min(
        TILE_COLUMNS - 1,
        (encode_longitude(maximum_longitude) + LONGITUDE_OFFSET) // TILE_STEPS,
    )
    first_row = max(
        0,
        (encode_latitude(minimum_latitude) + LATITUDE_OFFSET) // TILE_STEPS,
    )
    last_row = min(
        TILE_ROWS - 1,
        (encode_latitude(maximum_latitude) + LATITUDE_OFFSET) // TILE_STEPS,
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
    would. The sorted records are then zlib-compressed at level 1, which keeps the
    database build fast while still shrinking the payload substantially.

    Args:
        points: The tile's ``(n, 2)`` int32 encoded coordinate pairs.

    Returns:
        The compressed payload bytes.
    """
    records = np.ascontiguousarray(points.view("V8").reshape(-1))
    records.sort()
    return zlib.compress(records, level=1)


def decode_payload(payload: bytes) -> np.ndarray:
    """Return the ``(n, 2)`` int32 points held in a compressed tile payload.

    Args:
        payload: The compressed payload bytes.

    Returns:
        The decoded encoded coordinate pairs.
    """
    return np.frombuffer(zlib.decompress(payload), dtype="<i4").reshape(-1, 2)


class PartitionFiles:
    """The temporary binary partition files being accumulated.

    Each of the sixteen files holds only concatenated 8-byte records: no headers,
    delimiters, tile ids, or SQLite row structures. Records are appended across every
    state's archive, so all records of a tile always reach the same partition, and the
    files are removed once all archives have been consumed.
    """

    def __init__(self, directory: pathlib.Path) -> None:
        self._directory = directory
        for partition in range(PARTITION_COUNT):
            (directory / partition_filename(partition)).touch()

    def append(self, partition: int, records: collections.abc.Buffer) -> None:
        """Append *records* to *partition*'s file.

        Args:
            partition: The partition number.
            records: The concatenated record bytes, as any buffer of raw bytes.
        """
        with (self._directory / partition_filename(partition)).open("ab") as file:
            file.write(records)

    def __enter__(self) -> typing.Self:
        """Return the writer as its own context manager.

        Returns:
            The writer itself.
        """
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        """Release nothing; the files are appended and closed per write."""


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


def convert_geometry_chunks_to_partitions(
    features_iter: typing.Iterator[typing.Any],
    partition_files: PartitionFiles,
) -> int:
    """Convert *features_iter*'s geometry dicts into records at *partition_files*.

    Each bounded chunk's centroid points are quantized and appended to the partition
    files, so the stream is consumed without ever holding the whole archive in memory.

    Args:
        features_iter: The ijson geometry iterator, created by the caller.
        partition_files: The partition files to append to.

    Returns:
        The number of features converted.
    """
    feature_count = 0
    while True:
        chunk = peri_scribe.fires.centroid_streaming.collect_geometry_chunk(
            features_iter,
            peri_scribe.fires.centroid_streaming.FEATURE_CHUNK_SIZE,
            peri_scribe.fires.centroid_streaming.MAXIMUM_VERTICES_PER_CHUNK,
        )
        if chunk is None:
            break
        centroids = peri_scribe.fires.centroid_math.polygon_centroids(chunk)
        append_centroids_to_partitions(centroids, partition_files)
        feature_count += len(centroids)
    return feature_count


def stream_zip_members_to_partitions(
    bytes_source: typing.Iterable[bytes],
    partition_files: PartitionFiles,
) -> tuple[int, bool]:
    """Convert the GeoJSON members of a zip archive streaming from *bytes_source*.

    Each member named like ``*.geojson`` is parsed and converted; other members are
    consumed so the archive's next member can be read from the stream.

    Args:
        bytes_source: An iterable of byte chunks of the zip archive, in order.
        partition_files: The partition files to append to.

    Returns:
        The number of features converted and whether any were written.
    """
    feature_count = 0
    wrote_any = False
    for filename, _size, chunks in stream_unzip.stream_unzip(bytes_source):
        if not filename.endswith(
            peri_scribe.fires.centroid_streaming.GEOJSON_MEMBER_SUFFIX,
        ):
            collections.deque(chunks, maxlen=0)
            continue
        features_iter = ijson.items(
            peri_scribe.fires.centroid_streaming.ByteStream(chunks),
            "features.item.geometry",
            use_float=True,
        )
        count = convert_geometry_chunks_to_partitions(features_iter, partition_files)
        wrote_any = wrote_any or count > 0
        feature_count += count
    return feature_count, wrote_any


def stream_state_archive(
    url: str,
    partition_files: PartitionFiles,
) -> int:
    """Stream *url*'s archive and convert its records at *partition_files*.

    The archive's bytes are read from the response as they arrive and converted without
    ever writing the archive or its GeoJSON to disk.

    Args:
        url: The archive's URL.
        partition_files: The partition files to append to.

    Returns:
        The number of features converted.

    Raises:
        ExternalDataError: If the download fails, the stream is not a zip archive, or
            the archive holds no GeoJSON member with any features.
    """
    try:
        response = requests.get(
            url,
            stream=True,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.exceptions.RequestException as error:
        message = f"Failed to download {url}: {error}"
        raise peri_scribe.exceptions.ExternalDataError(message) from error
    feature_count, wrote_any = convert_stream_to_partitions(
        response.iter_content(chunk_size=DOWNLOAD_CHUNK_SIZE),
        partition_files,
    )
    if not wrote_any:
        message = "No GeoJSON data found in the streamed archive"
        raise peri_scribe.exceptions.ExternalDataError(message)
    return feature_count


def convert_stream_to_partitions(
    bytes_source: typing.Iterable[bytes],
    partition_files: PartitionFiles,
) -> tuple[int, bool]:
    """Convert the GeoJSON members of a zip archive streaming from *bytes_source*.

    Each member named like ``*.geojson`` is parsed and converted; other members are
    consumed so the archive's next member can be read from the stream.

    Args:
        bytes_source: An iterable of byte chunks of the zip archive, in order.
        partition_files: The partition files to append to.

    Returns:
        The number of features converted and whether any were written.

    Raises:
        ExternalDataError: If the stream is not a zip archive or its GeoJSON cannot be
            read.
    """
    try:
        return stream_zip_members_to_partitions(bytes_source, partition_files)
    except stream_unzip.UnzipError as error:
        message = f"The streamed archive is not a zip file: {error}"
        raise peri_scribe.exceptions.ExternalDataError(message) from error
    except Exception as error:
        message = f"Failed to read the streamed GeoJSON: {error}"
        raise peri_scribe.exceptions.ExternalDataError(message) from error


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
    """Build the compact buildings database at *output* from the partition files.

    The database's schema and metadata are created, then each partition file is
    processed one at a time and its tiles are written. The output holds one row per
    occupied tile.

    Args:
        partition_directory: The directory holding the sixteen partition files.
        output: The database path to write.

    Returns:
        The total number of building records written.
    """
    output.unlink(missing_ok=True)
    connection = sqlite3.connect(output)
    try:
        connection.executescript(DATABASE_SCHEMA)
        connection.executemany(
            "INSERT INTO metadata(key, value) VALUES (?, ?)",
            expected_metadata().items(),
        )
        building_count = 0
        for partition in range(PARTITION_COUNT):
            building_count += process_partition(
                partition_directory / partition_filename(partition),
                connection,
            )
        connection.commit()
        return building_count
    finally:
        connection.close()


def normalized_sql(statement: str) -> str:
    """Return *statement* with whitespace normalized for schema comparison.

    Args:
        statement: The SQL statement text.

    Returns:
        The statement with runs of whitespace collapsed to single spaces.
    """
    return " ".join(statement.split())


def is_valid_database(path: pathlib.Path) -> bool:
    """Return True when *path* holds a valid compact buildings database.

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


def fetch_buildings_database(
    source: peri_scribe.sources.external_sources.ExternalSource,
    year_directory: pathlib.Path,
) -> tuple[pathlib.Path, ...]:
    """Retrieve *source*'s compact buildings database into *year_directory*.

    When a valid database already exists at the output path, nothing is downloaded and
    its path is returned. Otherwise the repository page is read, every state's archive
    is streamed into the sixteen partition files, and the partition files are processed
    into a database written at a temporary path. The temporary database is validated and
    only then atomically renamed into place, so an existing database (valid or not) is
    preserved whenever downloading or generation fails and the temporary partition files
    are removed either way.

    Args:
        source: The compact buildings external source.
        year_directory: The year directory that holds the ``sources`` directory.

    Returns:
        The path of the stored database.

    Raises:
        ExternalDataError: If the source's page or any archive cannot be retrieved, or
            the generated database fails validation.
    """
    output = peri_scribe.sources.external_sources.output_path(year_directory, source)
    if is_valid_database(output):
        logger.debug(
            "External source already present",
            source=source.name,
            path=output,
        )
        return (output,)
    output.parent.mkdir(parents=True, exist_ok=True)
    state_urls = source.state_urls() if source.state_urls is not None else None
    with tempfile.TemporaryDirectory(dir=output.parent) as temporary_directory:
        directory = pathlib.Path(temporary_directory)
        partition_directory = directory / "partitions"
        partition_directory.mkdir()
        with PartitionFiles(partition_directory) as partition_files:
            for state in source.states:
                url = peri_scribe.sources.downloading.state_download_url(
                    source,
                    state,
                    state_urls,
                )
                stream_state_archive(url, partition_files)
        database_path = directory / f"{output.stem}.tmp.sqlite"
        building_count = build_tiles_database(partition_directory, database_path)
        if not is_valid_database(database_path):
            message = "The generated buildings database is invalid"
            raise peri_scribe.exceptions.ExternalDataError(message)
        database_path.replace(output)
    logger.debug(
        "Fetched compact buildings database",
        source=source.name,
        path=output,
        buildings=building_count,
    )
    return (output,)


def read_tile_points(
    connection: sqlite3.Connection,
    tile_id: int,
) -> np.ndarray | None:
    """Return a tile's decoded points from *connection*, or None when absent.

    Args:
        connection: The database connection.
        tile_id: The tile id to read.

    Returns:
        The tile's ``(n, 2)`` int32 encoded coordinate pairs, or None when the
        database holds no row for the tile.
    """
    row = connection.execute(
        "SELECT payload FROM tiles WHERE tile_id = ?",
        (tile_id,),
    ).fetchone()
    if row is None:
        return None
    return decode_payload(row[0])


def building_counts_within(
    buffered_geometries: list[shapely.Geometry | None],
    path: pathlib.Path,
) -> list[int]:
    """Return how many building points lie within each buffered geometry.

    Each buffered geometry's envelope selects the intersecting tiles from the compact
    buildings database; those tiles' payloads are decompressed into NumPy arrays and
    filtered to the envelope, and the remaining points are tested for exact containment
    against that geometry. Every point inside a geometry is inside its envelope, so the
    per-geometry candidate set is complete and the containment test is exact; testing
    each geometry's candidates against itself also keeps genuinely duplicate points
    (multiple buildings with identical quantized coordinates) counted separately. Each
    fire's tiles are decoded only while that fire is counted, so the reader's memory
    stays bounded by the largest single envelope rather than by the whole database.

    Args:
        buffered_geometries: One buffered geometry per fire, in WGS84, or None.
        path: The compact buildings database.

    Returns:
        One building count per fire, aligned with *buffered_geometries*.
    """
    valid = [
        (index, geometry)
        for index, geometry in enumerate(buffered_geometries)
        if geometry is not None and not geometry.is_empty
    ]
    counts = [0] * len(buffered_geometries)
    if not valid:
        return counts
    if not path.is_file():
        return counts
    connection = sqlite3.connect(path)
    try:
        for index, geometry in valid:
            bounds = geometry.bounds
            encoded = encoded_box(bounds)
            selected: list[np.ndarray] = []
            for identifier in tile_ids_for_box(bounds):
                tile_points = read_tile_points(connection, identifier)
                if tile_points is None:
                    continue
                filtered = points_within_box(tile_points, encoded)
                if filtered.size:
                    selected.append(filtered)
            if not selected:
                continue
            candidates = np.concatenate(selected)
            point_geometries = shapely.points(
                candidates[:, 0] / COORDINATE_SCALE,
                candidates[:, 1] / COORDINATE_SCALE,
            )
            counts[index] = int(
                np.count_nonzero(shapely.within(point_geometries, geometry)),
            )
    finally:
        connection.close()
    return counts
