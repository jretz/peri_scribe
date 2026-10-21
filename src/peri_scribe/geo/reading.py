"""Reading fire rows and memberships from GeoPackage files and caches.

Design notes:
[Authenticated parsed source cache](../../../docs/algorithms/parsed-source-cache.md).
"""

from __future__ import annotations

import collections
import collections.abc
import pathlib
import sqlite3
import typing

import shapely.errors
import structlog

import peri_scribe.geo.database
import peri_scribe.geo.dictionaries
import peri_scribe.geo.package
import peri_scribe.geo.parsing
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

    Raises:
        ValueError: If a row refers to an absent dictionary encoding.
    """
    # write_snapshot inserts each tuple in order, so rowid retains source ordering.
    rows = conn.execute(
        "SELECT rows.*, geometry_payloads.value AS geometry_wkb, "
        "attribute_payloads.value AS attributes_json FROM rows "
        "LEFT JOIN geometry_payloads ON geometry_payloads.id = rows.geometry_id "
        "LEFT JOIN attribute_payloads ON attribute_payloads.id = rows.attributes_id "
        "WHERE serial = ? ORDER BY rows.rowid",
        (serial,),
    ).fetchall()
    if any(
        row["attributes_json"] is None
        or (row["geometry_id"] is not None and row["geometry_wkb"] is None)
        for row in rows
    ):
        message = "Parsed rows reference missing dictionary payloads"
        raise ValueError(message)
    memberships = conn.execute(
        "SELECT fire_identifier, complex_identifier, complex_name, observation_time "
        "FROM memberships WHERE serial = ? ORDER BY rowid",
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
                observation_time=peri_scribe.geo.parsing.observation_time_from(
                    row["observation_time"],
                ),
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
    """Return one authenticated transaction's contents, or None when absent.

    Read the checksum receipt, rows, and memberships in one transaction. A concurrent
    cache replacement then cannot substitute different rows after the checksum check. If
    the caller already has a transaction open, a savepoint preserves it.

    Args:
        conn: The record cache database connection.
        serial: The snapshot's serial number.
        checksum: SHA-256 checksum of the current authoritative snapshot bytes.
        geometry_pool: The source read's shared snapshot geometries.

    Returns:
        The snapshot's fire rows and complex memberships, or None when the database does
        not cover the snapshot.
    """
    conn.row_factory = sqlite3.Row
    conn.execute("SAVEPOINT snapshot_read")
    try:
        present = conn.execute(
            "SELECT 1 FROM snapshots WHERE serial = ? AND checksum = ?",
            (serial, checksum),
        ).fetchone()
        if present is None:
            return None
        return read_snapshot_contents(conn, serial, geometry_pool=geometry_pool)
    finally:
        conn.execute("RELEASE snapshot_read")


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
        checksum: SHA-256 checksum of the current authoritative snapshot bytes.
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
    except OSError, ValueError, sqlite3.Error, shapely.errors.GEOSException:
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

    Reading and decoding a GeoPackage costs more than loading its parsed rows from
    SQLite. Each feed therefore caches its immutable snapshots in
    ``sources/{feed}/record_cache.db``. The cache records a snapshot's checksum, size,
    and modification time.

    Every cached read checks the current bytes. This catches edits made in place and
    replacements that preserve timestamps, while synchronization removes missing
    snapshots. When inventory synchronization runs, missing, stale, corrupt, or unusable
    caches are rebuilt from the GeoPackages. A failed update or an unauthenticated
    cached read falls back to the source file directly, preserving access to valid
    source data.

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


def fetch_snapshot_batch(
    conn: sqlite3.Connection,
    requests: collections.abc.Mapping[pathlib.Path, tuple[int, str]],
    *,
    geometry_pool: spatial_data.geometry_pool.GeometryPool,
) -> dict[pathlib.Path, peri_scribe.geo.package.GeopackageContents]:
    """Pin matching receipts, ordered metadata, and shared payloads in one transaction.

    Args:
        conn: A read-only feed connection, possibly already in a caller transaction.
        requests: Snapshot paths and their requested serial/current byte checksum.
        geometry_pool: Shared immutable geometries for this complete source read.

    Returns:
        Complete contents for authenticated requests; absent requests need fallback.
    """
    conn.row_factory = sqlite3.Row
    conn.execute("SAVEPOINT snapshot_batch")
    try:
        receipts = dict(conn.execute("SELECT serial, checksum FROM snapshots"))
        accepted = {
            path: serial
            for path, (serial, checksum) in requests.items()
            if receipts.get(serial) == checksum
        }
        serials = set(accepted.values())
        metadata = [
            row
            for row in conn.execute("SELECT * FROM rows ORDER BY rowid")
            if row["serial"] in serials
        ]
        payloads = peri_scribe.geo.dictionaries.decoded_payloads(
            conn,
            metadata,
            geometry_pool,
        )
        rows: dict[int, list[peri_scribe.geo.package.FireRowRecord]] = (
            collections.defaultdict(list)
        )
        for row in metadata:
            geometry_id = row["geometry_id"]
            attributes_id = row["attributes_id"]
            rows[row["serial"]].append(
                peri_scribe.geo.package.FireRowRecord.from_cached_row(
                    row,
                    None if geometry_id is None else payloads.geometries[geometry_id],
                    payloads.attributes[attributes_id],
                    None
                    if geometry_id is None
                    else payloads.geometry_fingerprints[geometry_id],
                    payloads.attribute_fingerprints[attributes_id],
                ),
            )
        memberships: dict[int, list[peri_scribe.models.ComplexMembership]] = (
            collections.defaultdict(list)
        )
        for row in conn.execute("SELECT * FROM memberships ORDER BY rowid"):
            if row["serial"] in serials:
                memberships[row["serial"]].append(
                    peri_scribe.models.ComplexMembership(
                        fire_identifier=row["fire_identifier"],
                        complex_identifier=row["complex_identifier"],
                        complex_name=row["complex_name"],
                        observation_time=peri_scribe.geo.parsing.observation_time_from(
                            row["observation_time"],
                        ),
                    ),
                )
        contents = {
            serial: peri_scribe.geo.package.GeopackageContents(
                rows=tuple(rows[serial]),
                memberships=tuple(memberships[serial]),
            )
            for serial in serials
        }
        return {path: contents[serial] for path, serial in accepted.items()}
    finally:
        conn.execute("RELEASE snapshot_batch")


def read_feed_batch(
    paths: collections.abc.Sequence[pathlib.Path],
    *,
    geometry_pool: spatial_data.geometry_pool.GeometryPool,
) -> dict[pathlib.Path, peri_scribe.geo.package.GeopackageContents]:
    """Synchronize one feed once and authenticate all requests before its pinned read.

    Args:
        paths: At least one valid named snapshot from the same feed directory.
        geometry_pool: Shared immutable geometries for this complete source read.

    Returns:
        Authenticated complete parses available in this feed's record cache.
    """
    source_directory = paths[0].parent.parent
    database_path = peri_scribe.sources.snapshots.record_cache_database_path(
        source_directory,
    )
    with peri_scribe.geo.database.RECORD_CACHE_LOCK:
        peri_scribe.geo.database.ensure_database_current(
            database_path,
            source_directory,
        )
    requests = {
        path: (
            peri_scribe.sources.snapshots.SourceFile.from_path(path).serial_number,
            peri_scribe.geo.database.snapshot_checksum(path),
        )
        for path in paths
    }
    conn = sqlite3.connect(database_path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        return fetch_snapshot_batch(conn, requests, geometry_pool=geometry_pool)
    finally:
        conn.close()


def read_geopackages_cached(
    paths: collections.abc.Sequence[pathlib.Path],
    *,
    geometry_pool: spatial_data.geometry_pool.GeometryPool | None = None,
    read_fallback: collections.abc.Callable[
        [pathlib.Path],
        peri_scribe.geo.package.GeopackageContents,
    ]
    | None = None,
) -> dict[pathlib.Path, peri_scribe.geo.package.GeopackageContents]:
    """Read feed dictionaries once while preserving each requested snapshot's parse.

    Args:
        paths: Requested source snapshot paths in the caller's order.
        geometry_pool: Shared immutable geometries for the complete source read.
        read_fallback: The caller's authoritative parser and error translation, if any.

    Returns:
        One complete parse per path, with direct-source fallback on cache misses/errors.
    """
    if geometry_pool is None:
        geometry_pool = spatial_data.geometry_pool.GeometryPool()
    if read_fallback is None:
        read_fallback = peri_scribe.geo.package.read_geopackage
    feeds: dict[pathlib.Path, list[pathlib.Path]] = collections.defaultdict(list)
    contents: dict[pathlib.Path, peri_scribe.geo.package.GeopackageContents] = {}
    for path in paths:
        try:
            path.stat()
            peri_scribe.sources.snapshots.SourceFile.from_path(path)
        except OSError, ValueError:
            contents[path] = read_fallback(path)
        else:
            feeds[path.parent.parent].append(path)
    for feed_paths in feeds.values():
        try:
            contents.update(read_feed_batch(feed_paths, geometry_pool=geometry_pool))
        except OSError, ValueError, sqlite3.Error, shapely.errors.GEOSException:
            logger.debug("Failed to read feed record cache", exc_info=True)
        for path in feed_paths:
            if path not in contents:
                contents[path] = read_fallback(path)
    return contents


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
