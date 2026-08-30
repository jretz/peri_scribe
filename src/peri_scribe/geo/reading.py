"""Reading fire rows and memberships from GeoPackage files and caches."""

from __future__ import annotations

import pathlib
import sqlite3
import typing

import geopandas
import structlog

import peri_scribe.geo.database
import peri_scribe.geo.package
import peri_scribe.models
import peri_scribe.sources.feed_types
import peri_scribe.sources.snapshots


logger = structlog.get_logger()


def read_snapshot_contents(
    conn: sqlite3.Connection,
    serial: int,
) -> peri_scribe.geo.package.GeopackageContents:
    """Return the parsed contents stored for snapshot *serial* in *conn*.

    Args:
        conn: The record cache database connection, reading rows by column name.
        serial: The snapshot's serial number.

    Returns:
        The snapshot's fire rows and complex memberships.
    """
    rows = conn.execute(
        "SELECT serial, object_id, source_name, name, status, identifiers, "
        "names, geometry_wkb, observed_at, mission, point_of_origin_state, "
        "point_of_origin_fips, attributes_json FROM rows WHERE serial = ?",
        (serial,),
    ).fetchall()
    memberships = conn.execute(
        "SELECT fire_identifier, complex_identifier, complex_name "
        "FROM memberships WHERE serial = ?",
        (serial,),
    ).fetchall()
    return peri_scribe.geo.package.GeopackageContents(
        rows=tuple(peri_scribe.geo.package.FireRowRecord.from_row(row) for row in rows),
        memberships=tuple(
            peri_scribe.models.ComplexMembership(
                fire_identifier=row["fire_identifier"],
                complex_identifier=row["complex_identifier"],
                complex_name=row["complex_name"],
            )
            for row in memberships
        ),
    )


def fetch_snapshot_rows(
    conn: sqlite3.Connection,
    serial: int,
) -> peri_scribe.geo.package.GeopackageContents | None:
    """Return the contents stored for snapshot *serial*, or None when absent.

    Args:
        conn: The record cache database connection.
        serial: The snapshot's serial number.

    Returns:
        The snapshot's fire rows and complex memberships, or None when the database does
        not cover the snapshot.
    """
    conn.row_factory = sqlite3.Row
    present = conn.execute(
        "SELECT 1 FROM snapshots WHERE serial = ?",
        (serial,),
    ).fetchone()
    if present is None:
        return None
    return read_snapshot_contents(conn, serial)


def read_snapshot_rows(
    db_path: pathlib.Path,
    serial: int,
) -> peri_scribe.geo.package.GeopackageContents | None:
    """Return the contents stored for snapshot *serial* at *db_path*.

    Args:
        db_path: The record cache database path.
        serial: The snapshot's serial number.

    Returns:
        The snapshot's fire rows and complex memberships, or None when the database does
        not cover the snapshot.
    """
    conn = sqlite3.connect(db_path)
    try:
        return fetch_snapshot_rows(conn, serial)
    finally:
        conn.close()


def read_cached_snapshot(
    db_path: pathlib.Path,
    serial: int,
    path: pathlib.Path,
) -> peri_scribe.geo.package.GeopackageContents:
    """Return the cached contents stored for snapshot *serial*, or read the file.

    A snapshot that the database does not cover (for example one written while the
    database was being checked) and a database that cannot be read both fall back to
    reading the GeoPackage directly, so the cache never fails a read.

    Args:
        db_path: The record cache database path.
        serial: The snapshot's serial number.
        path: The snapshot GeoPackage file to read.

    Returns:
        The snapshot's fire rows and complex memberships.
    """
    try:
        contents = read_snapshot_rows(db_path, serial)
    except OSError, ValueError, sqlite3.Error:
        logger.debug("Failed to read record cache", path=str(path))
        return peri_scribe.geo.package.read_geopackage(path)
    if contents is None:
        return peri_scribe.geo.package.read_geopackage(path)
    return contents


def read_geopackage_cached(
    path: pathlib.Path,
) -> peri_scribe.geo.package.GeopackageContents:
    """Return the contents of the GeoPackage at *path*, using its record cache.

    Reading and decoding a GeoPackage is far more expensive than loading its parsed
    contents from a database, and snapshots are immutable once written, so each feed's
    parsed contents are cached in one SQLite database stored inside the feed's snapshot
    directory (``sources/{feed}/record_cache.db``). The database records each snapshot
    file's size and modification time, so a snapshot that is ever rewritten (or restored
    from a backup) is read and cached again, and a snapshot whose file disappears is
    dropped. A missing, stale, corrupt, or unusable database never fails the read: it is
    rebuilt from the GeoPackages, and a failed cache update falls back to reading the
    file directly.

    Args:
        path: The snapshot GeoPackage file to read.

    Returns:
        The fire rows and complex memberships of the file.
    """
    try:
        path.stat()
        source_directory = path.parent.parent
        db_path = peri_scribe.sources.snapshots.record_cache_database_path(
            source_directory,
        )
        serial = peri_scribe.sources.snapshots.SourceFile.from_path(path).serial_number
    except OSError, ValueError:
        return peri_scribe.geo.package.read_geopackage(path)
    try:
        with peri_scribe.geo.database.RECORD_CACHE_LOCK:
            peri_scribe.geo.database.ensure_database_current(db_path, source_directory)
    except OSError, ValueError, sqlite3.Error:
        logger.debug("Failed to update record cache", path=str(path))
        return peri_scribe.geo.package.read_geopackage(path)
    return read_cached_snapshot(db_path, serial, path)


def read_layer(
    path: pathlib.Path,
    layer_name: str,
) -> geopandas.GeoDataFrame:
    """Read *layer_name* from the GeoPackage at *path*.

    The file is only read, never written.

    Args:
        path: The GeoPackage file to read.
        layer_name: The layer to read.

    Returns:
        The layer's features as a GeoDataFrame.
    """
    return geopandas.read_file(path, layer=layer_name)


def read_layer_dataframe(
    path: pathlib.Path,
    feed: peri_scribe.sources.feed_types.Feed,
) -> geopandas.GeoDataFrame:
    """Read the feed's layer from the GeoPackage at *path*.

    The file is only read, never written.

    Args:
        path: The GeoPackage file to read.
        feed: The feed whose layer is read.

    Returns:
        The layer's features as a GeoDataFrame.
    """
    return read_layer(path, feed.name)


def read_layer_chunks(
    path: pathlib.Path,
    layer_name: str | None,
    chunk_size: int,
) -> typing.Iterator[geopandas.GeoDataFrame]:
    """Yield *layer_name* from *path* in chunks of at most *chunk_size* rows.

    Each chunk is a bounded read of at most *chunk_size* features, so a layer of any
    size can be processed without loading the whole layer into memory. The final chunk
    may be smaller; a layer with no features yields nothing. When *layer_name* is None
    the file's default layer is read, which is how a single-layer file such as a
    shapefile or file geodatabase is read. The file is only read, never written.

    GeoPackage layers are paginated by their ``fid`` primary key rather than with
    ``skip_features``, because skip-based pagination rescans the layer from the start
    for every chunk and becomes quadratic over the whole read. Other file kinds fall
    back to skip-based pagination.

    Args:
        path: The vector data file to read.
        layer_name: The layer to read, or None for the file's default layer.
        chunk_size: The maximum number of features per chunk.

    Yields:
        Each chunk of the layer's features, in row order.
    """
    if path.suffix.lower() == ".gpkg" and layer_name is not None:
        yield from read_gpkg_layer_chunks(path, layer_name, chunk_size)
        return
    yield from read_skip_layer_chunks(path, layer_name, chunk_size)


def read_skip_layer_chunks(
    path: pathlib.Path,
    layer_name: str | None,
    chunk_size: int,
) -> typing.Iterator[geopandas.GeoDataFrame]:
    """Yield chunks using ``skip_features``, which rescans from the start each time.

    Yields:
        Each chunk of the layer's features, in row order.
    """
    offset = 0
    while True:
        dataframe = geopandas.read_file(
            path,
            layer=layer_name,
            max_features=chunk_size,
            skip_features=offset,
        )
        if dataframe.empty:
            return
        yield dataframe
        offset += len(dataframe)


def read_gpkg_layer_chunks(
    path: pathlib.Path,
    layer_name: str,
    chunk_size: int,
) -> typing.Iterator[geopandas.GeoDataFrame]:
    """Yield chunks of a GeoPackage layer paginated by its ``fid`` primary key.

    Each chunk is ``where="fid > lower AND fid <= upper"`` for fid boundaries spaced
    ``chunk_size`` apart, so every chunk is an indexed range read of constant cost
    rather than a rescan. Boundaries are taken at ``fid % chunk_size == 0``; for the
    dense fids this project writes, that yields chunks of exactly ``chunk_size`` rows in
    fid order, matching the skip-based contract.

    Yields:
        Each chunk of the layer's features, in fid order.
    """
    connection = sqlite3.connect(path)
    try:
        minimum_fid = connection.execute(
            f'SELECT MIN(fid) FROM "{layer_name}"',
        ).fetchone()[0]
        boundaries = [
            row[0]
            for row in connection.execute(
                f'SELECT fid FROM "{layer_name}" '
                f"WHERE fid % {chunk_size} = 0 ORDER BY fid",
            )
        ]
    finally:
        connection.close()
    if minimum_fid is None:
        return
    lower = minimum_fid - 1
    for upper in boundaries:
        dataframe = geopandas.read_file(
            path,
            layer=layer_name,
            where=f"fid > {lower} AND fid <= {upper}",
        )
        if not dataframe.empty:
            yield dataframe
        lower = upper
    dataframe = geopandas.read_file(
        path,
        layer=layer_name,
        where=f"fid > {lower}",
    )
    if not dataframe.empty:
        yield dataframe
