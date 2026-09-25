"""Reading fire rows and memberships from GeoPackage files and caches."""

from __future__ import annotations

import pathlib
import sqlite3
import typing

import structlog

import peri_scribe.geo.database
import peri_scribe.geo.package
import peri_scribe.models
import peri_scribe.sources.feed_types
import peri_scribe.sources.snapshots
import spatial_data.geometry_pool
import spatial_data.layers


if typing.TYPE_CHECKING:
    import geopandas


logger = structlog.get_logger()


def read_snapshot_contents(
    conn: sqlite3.Connection,
    serial: int,
    *,
    geometry_pool: spatial_data.geometry_pool.GeometryPool,
) -> peri_scribe.geo.package.GeopackageContents:
    """Return the parsed contents stored for snapshot *serial* in *conn*.

    Args:
        conn: The record cache database connection, reading rows by column name.
        serial: The snapshot's serial number.
        geometry_pool: The source read's shared snapshot geometries.

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
        rows=tuple(
            peri_scribe.geo.package.FireRowRecord.from_row(
                row,
                geometry_pool=geometry_pool,
            )
            for row in rows
        ),
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
    *,
    checksum: str,
    geometry_pool: spatial_data.geometry_pool.GeometryPool,
) -> peri_scribe.geo.package.GeopackageContents | None:
    """Return the contents stored for snapshot *serial*, or None when absent.

    Args:
        conn: The record cache database connection.
        serial: The snapshot's serial number.
        checksum: Current authoritative snapshot bytes, required before reusing a parse.
        geometry_pool: The source read's shared snapshot geometries.

    Returns:
        The snapshot's fire rows and complex memberships, or None when the database does
        not cover the snapshot.
    """
    conn.row_factory = sqlite3.Row
    present = conn.execute(
        "SELECT 1 FROM snapshots WHERE serial = ? AND checksum = ?",
        (serial, checksum),
    ).fetchone()
    if present is None:
        return None
    return read_snapshot_contents(conn, serial, geometry_pool=geometry_pool)


def read_snapshot_rows(
    db_path: pathlib.Path,
    serial: int,
    *,
    checksum: str,
    geometry_pool: spatial_data.geometry_pool.GeometryPool,
) -> peri_scribe.geo.package.GeopackageContents | None:
    """Return the contents stored for snapshot *serial* at *db_path*.

    Args:
        db_path: The record cache database path.
        serial: The snapshot's serial number.
        checksum: Current authoritative snapshot bytes, required before reusing a parse.
        geometry_pool: The source read's shared snapshot geometries.

    Returns:
        The snapshot's fire rows and complex memberships, or None when the database does
        not cover the snapshot.
    """
    conn = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        return fetch_snapshot_rows(
            conn,
            serial,
            checksum=checksum,
            geometry_pool=geometry_pool,
        )
    finally:
        conn.close()


def read_cached_snapshot(
    db_path: pathlib.Path,
    serial: int,
    path: pathlib.Path,
    *,
    geometry_pool: spatial_data.geometry_pool.GeometryPool,
) -> peri_scribe.geo.package.GeopackageContents:
    """Return the cached contents stored for snapshot *serial*, or read the file.

    Missing or unauthenticated parsed records and unreadable databases fall back to
    reading the GeoPackage directly. Each lookup checks the current content checksum
    even when unchanged directory metadata allowed the feed synchronization to skip.

    Args:
        db_path: The record cache database path.
        serial: The snapshot's serial number.
        path: The snapshot GeoPackage file to read.
        geometry_pool: The source read's shared snapshot geometries.

    Returns:
        The snapshot's fire rows and complex memberships.
    """
    try:
        contents = read_snapshot_rows(
            db_path,
            serial,
            checksum=peri_scribe.geo.database.snapshot_checksum(path),
            geometry_pool=geometry_pool,
        )
    except OSError, ValueError, sqlite3.Error:
        logger.debug("Failed to read record cache", path=str(path), exc_info=True)
        return peri_scribe.geo.package.read_geopackage(path)
    if contents is None:
        return peri_scribe.geo.package.read_geopackage(path)
    return contents


def read_geopackage_cached(
    path: pathlib.Path,
    *,
    geometry_pool: spatial_data.geometry_pool.GeometryPool | None = None,
) -> peri_scribe.geo.package.GeopackageContents:
    """Return the contents of the GeoPackage at *path*, using its record cache.

    Reading and decoding a GeoPackage is far more expensive than loading its parsed
    contents from a database, and snapshots are immutable once written, so each feed's
    parsed contents are cached in one SQLite database stored inside the feed's snapshot
    directory (``sources/{feed}/record_cache.db``). The database records each snapshot's
    checksum as well as its size and modification time. Every cached read checks the
    current bytes, so in-place edits and replacements with preserved timestamps cannot
    reuse stale records. Missing snapshots are dropped during synchronization.
    A missing, stale, corrupt, or unusable database never fails the read: it is
    rebuilt from the GeoPackages, and a failed cache update falls back to reading the
    file directly.

    Args:
        path: The snapshot GeoPackage file to read.
        geometry_pool: Shared geometries for a larger source read, if supplied.

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
        logger.debug("Failed to update record cache", path=str(path), exc_info=True)
        return peri_scribe.geo.package.read_geopackage(path)
    if geometry_pool is None:
        geometry_pool = spatial_data.geometry_pool.GeometryPool()
    return read_cached_snapshot(db_path, serial, path, geometry_pool=geometry_pool)


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
    return spatial_data.layers.read_layer(path, feed.name)
