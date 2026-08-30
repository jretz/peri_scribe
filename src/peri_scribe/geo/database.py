"""The record cache database that stores parsed snapshot rows."""

from __future__ import annotations

import contextlib
import pathlib
import sqlite3
import threading

import structlog

import peri_scribe.geo.package
import peri_scribe.sources.snapshots


logger = structlog.get_logger()


RECORD_CACHE_SCHEMA_VERSION = 1


RECORD_CACHE_SCHEMA = """
CREATE TABLE snapshots (
  serial INTEGER PRIMARY KEY,
  last_edit INTEGER NOT NULL,
  size INTEGER NOT NULL,
  mtime_ns INTEGER NOT NULL
);
CREATE TABLE rows (
  serial INTEGER NOT NULL,
  object_id INTEGER,
  source_name TEXT NOT NULL,
  name TEXT,
  status TEXT,
  identifiers TEXT,
  names TEXT,
  geometry_wkb BLOB,
  observed_at TEXT,
  mission TEXT,
  point_of_origin_state TEXT,
  point_of_origin_fips TEXT,
  attributes_json TEXT
);
CREATE INDEX rows_serial ON rows(serial);
CREATE TABLE memberships (
  serial INTEGER NOT NULL,
  fire_identifier TEXT NOT NULL,
  complex_identifier TEXT NOT NULL,
  complex_name TEXT NOT NULL
);
"""


RECORD_CACHE_LOCK = threading.Lock()


# Tracks which record cache databases are already in sync with their snapshot
# directories, so open_and_sync is only run once per signature.
RECORD_CACHE_SYNCED: dict[pathlib.Path, tuple[int | tuple[str, int], ...]] = {}


def reset_database(conn: sqlite3.Connection) -> None:
    """Replace the record cache tables in *conn* with an empty current schema.

    Args:
        conn: The record cache database connection.
    """
    conn.executescript(
        "DROP TABLE IF EXISTS rows;"
        "DROP TABLE IF EXISTS memberships;"
        "DROP TABLE IF EXISTS snapshots;",
    )
    conn.executescript(RECORD_CACHE_SCHEMA)
    conn.execute(f"PRAGMA user_version = {RECORD_CACHE_SCHEMA_VERSION}")
    conn.commit()


def write_snapshot(
    conn: sqlite3.Connection,
    source_file: peri_scribe.sources.snapshots.SourceFile,
    size: int,
    mtime_ns: int,
    contents: peri_scribe.geo.package.GeopackageContents,
) -> None:
    """Store one snapshot's parsed contents in *conn*.

    The snapshot's previous rows, if any, are replaced, so a rewritten snapshot file is
    reflected without stale rows.

    Args:
        conn: The record cache database connection.
        source_file: The snapshot being stored.
        size: The snapshot file's size in bytes.
        mtime_ns: The snapshot file's modification time in nanoseconds.
        contents: The snapshot's parsed rows and memberships.
    """
    conn.execute(
        "INSERT OR REPLACE INTO snapshots VALUES (?, ?, ?, ?)",
        (
            source_file.serial_number,
            source_file.last_edit_timestamp,
            size,
            mtime_ns,
        ),
    )
    conn.execute("DELETE FROM rows WHERE serial = ?", (source_file.serial_number,))
    conn.execute(
        "DELETE FROM memberships WHERE serial = ?",
        (source_file.serial_number,),
    )
    conn.executemany(
        "INSERT INTO rows (serial, object_id, source_name, name, status, "
        "identifiers, names, geometry_wkb, observed_at, mission, "
        "point_of_origin_state, point_of_origin_fips, attributes_json) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [row.to_row(source_file.serial_number) for row in contents.rows],
    )
    conn.executemany(
        "INSERT INTO memberships VALUES (?, ?, ?, ?)",
        [
            (
                source_file.serial_number,
                membership.fire_identifier,
                membership.complex_identifier,
                membership.complex_name,
            )
            for membership in contents.memberships
        ],
    )


def snapshot_directories_signature(
    source_directory: pathlib.Path,
) -> tuple[tuple[str, int], ...] | None:
    """Return a signature that changes whenever a snapshot file changes.

    Snapshot files live in bucket subdirectories named for the serial number's
    thousands, and every write goes through ``write_geopackage``, which unlinks and
    recreates the file, so adding, removing, or rewriting a snapshot changes a bucket
    directory's modification time, and adding or removing a bucket changes the set of
    buckets. The signature is the buckets' names and modification times, so a matching
    signature means no snapshot file can have changed since the signature was taken. The
    feed directory's own modification time is deliberately excluded: the feed directory
    also holds the record cache and current-state files, whose writes should not force
    the snapshot cache to re-sync.

    Args:
        source_directory: The feed's snapshot directory.

    Returns:
        The signature, or None when the feed directory cannot be read.
    """
    try:
        source_directory.stat()
    except OSError:
        return None
    bucket_mtime_ns: list[tuple[str, int]] = []
    for bucket in source_directory.iterdir():
        if not bucket.is_dir():
            continue
        try:
            bucket_mtime_ns.append((bucket.name, bucket.stat().st_mtime_ns))
        except OSError:
            continue
    return tuple(sorted(bucket_mtime_ns))


def sync_database(
    conn: sqlite3.Connection,
    source_directory: pathlib.Path,
) -> None:
    """Bring *conn*'s snapshot rows in line with *source_directory*'s files.

    Snapshots that are new or whose file size or modification time changed are read and
    stored; snapshots whose files have disappeared are dropped. Snapshots are immutable
    once written, so an unchanged file is not re-read.

    Args:
        conn: The record cache database connection.
        source_directory: The feed's snapshot directory.
    """
    stored = {
        serial: (size, mtime_ns)
        for serial, _last_edit, size, mtime_ns in conn.execute(
            "SELECT serial, last_edit, size, mtime_ns FROM snapshots",
        )
    }
    current: dict[int, tuple[peri_scribe.sources.snapshots.SourceFile, int, int]] = {}
    for source_file in peri_scribe.sources.snapshots.existing_source_files(
        source_directory,
    ):
        path = source_directory / source_file.relative_path
        try:
            stat = path.stat()
        except OSError:
            continue
        current[source_file.serial_number] = (
            source_file,
            stat.st_size,
            stat.st_mtime_ns,
        )
    for serial in set(stored) - set(current):
        conn.execute("DELETE FROM rows WHERE serial = ?", (serial,))
        conn.execute("DELETE FROM memberships WHERE serial = ?", (serial,))
        conn.execute("DELETE FROM snapshots WHERE serial = ?", (serial,))
    for serial, (source_file, size, mtime_ns) in current.items():
        if stored.get(serial) == (size, mtime_ns):
            continue
        path = source_directory / source_file.relative_path
        contents = peri_scribe.geo.package.read_geopackage(path)
        write_snapshot(conn, source_file, size, mtime_ns, contents)
    conn.commit()


def open_and_sync(
    db_path: pathlib.Path,
    source_directory: pathlib.Path,
) -> None:
    """Open the record cache database and bring it in line with the snapshots.

    A database with an outdated or missing schema is rebuilt before the snapshot rows
    are synchronized.

    Args:
        db_path: The record cache database path.
        source_directory: The feed's snapshot directory.
    """
    conn = sqlite3.connect(db_path)
    try:
        if (
            conn.execute("PRAGMA user_version").fetchone()[0]
            != RECORD_CACHE_SCHEMA_VERSION
        ):
            reset_database(conn)
        sync_database(conn, source_directory)
    finally:
        conn.close()


def ensure_database_current(
    db_path: pathlib.Path,
    source_directory: pathlib.Path,
) -> None:
    """Ensure the record cache database at *db_path* is current and usable.

    A database that cannot be read (a corrupt file or an unusable format) is replaced
    and rebuilt once; the caller falls back to reading the GeoPackage directly if the
    replacement also fails.

    Args:
        db_path: The record cache database path.
        source_directory: The feed's snapshot directory.
    """
    signature = snapshot_directories_signature(source_directory)
    if signature is None:
        # No snapshot directory to sync from.
        return
    if RECORD_CACHE_SYNCED.get(db_path) == signature:
        return
    db_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        open_and_sync(db_path, source_directory)
    except sqlite3.DatabaseError:
        logger.debug(
            "Record cache database unusable; rebuilding",
            path=str(db_path),
        )
        with contextlib.suppress(OSError):
            db_path.unlink()
        open_and_sync(db_path, source_directory)
    RECORD_CACHE_SYNCED[db_path] = signature
