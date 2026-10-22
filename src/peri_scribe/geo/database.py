"""The record cache database that stores parsed snapshot rows.

Design notes:
[Authenticated parsed source cache](../../../docs/algorithms/parsed-source-cache.md).
"""

from __future__ import annotations

import contextlib
import enum
import hashlib
import pathlib
import sqlite3
import threading
import typing

import structlog

import peri_scribe.geo.compaction
import peri_scribe.geo.fingerprints
import peri_scribe.geo.package
import peri_scribe.geo.payload_storage
import peri_scribe.sources.authentication
import peri_scribe.sources.snapshots


logger = structlog.get_logger()


# Cache compatibility includes preservation of all supported relationship identifiers.
RECORD_CACHE_SCHEMA_VERSION = 9


RECORD_CACHE_SCHEMA = """
CREATE TABLE snapshots (
  serial INTEGER PRIMARY KEY,
  last_edit INTEGER NOT NULL,
  size INTEGER NOT NULL,
  mtime_ns INTEGER NOT NULL,
  checksum TEXT NOT NULL
);
CREATE TABLE rows (
  serial INTEGER NOT NULL,
  object_id INTEGER,
  source_name TEXT NOT NULL,
  name TEXT,
  status TEXT,
  identifiers TEXT,
  names TEXT,
  geometry_id INTEGER,
  observed_at TEXT,
  mission TEXT,
  point_of_origin_state TEXT,
  point_of_origin_fips TEXT,
  attributes_id INTEGER NOT NULL,
  evidence_fingerprint TEXT NOT NULL
);
CREATE INDEX rows_serial ON rows(serial);
CREATE TABLE memberships (
  serial INTEGER NOT NULL,
  fire_identifier TEXT NOT NULL,
  complex_identifier TEXT,
  complex_name TEXT,
  observation_time TEXT
);
DROP TABLE IF EXISTS geometry_payloads;
DROP TABLE IF EXISTS attribute_payloads;
CREATE TABLE geometry_payloads (
  id INTEGER PRIMARY KEY,
  digest BLOB NOT NULL,
  value BLOB NOT NULL,
  encoding INTEGER NOT NULL DEFAULT 0,
  original_size INTEGER NOT NULL
);
CREATE INDEX geometry_payloads_digest ON geometry_payloads(digest);
CREATE TABLE attribute_payloads (
  id INTEGER PRIMARY KEY,
  digest BLOB NOT NULL,
  value BLOB NOT NULL,
  encoding INTEGER NOT NULL DEFAULT 0,
  original_size INTEGER NOT NULL,
  dictionary_id INTEGER
);
CREATE INDEX attribute_payloads_digest ON attribute_payloads(digest);
CREATE INDEX memberships_serial ON memberships(serial);
DROP TABLE IF EXISTS codec_dictionaries;
CREATE TABLE codec_dictionaries (id INTEGER PRIMARY KEY, value BLOB NOT NULL);
"""


RECORD_CACHE_LOCK = threading.Lock()


# Tracks which record cache databases are already in sync with their snapshot
# directories, so open_and_sync is only run once per signature.
RECORD_CACHE_SYNCED: dict[pathlib.Path, tuple[int | tuple[str, int], ...]] = {}


class PayloadKind(enum.Enum):
    """Limit dynamic SQL table selection to the two exact payload dictionaries."""

    GEOMETRY = "geometry_payloads"
    ATTRIBUTES = "attribute_payloads"


def intern_payload(
    conn: sqlite3.Connection,
    kind: PayloadKind,
    payload: bytes | str,
) -> int:
    """Resolve digest candidates with complete bytes before sharing an encoding.

    Args:
        conn: The transaction also publishing row references and snapshot receipts.
        kind: The dictionary's closed table identity.
        payload: Complete geometry bytes or canonical attribute JSON.

    Returns:
        A database-local key whose equality never substitutes digest equality.
    """
    digest = payload_digest(payload)
    dictionaries = peri_scribe.geo.payload_storage.dictionaries(conn)
    dictionary_column = "dictionary_id" if kind is PayloadKind.ATTRIBUTES else "NULL"
    for identifier, value, encoding, size, dictionary_id in conn.execute(
        f"SELECT id, value, encoding, original_size, {dictionary_column} "
        f"FROM {kind.value} WHERE digest = ?",
        (digest,),
    ):
        candidate = peri_scribe.geo.payload_storage.decode(
            value,
            encoding,
            size,
            dictionary=dictionaries.get(dictionary_id),
            text=kind is PayloadKind.ATTRIBUTES,
        )
        if candidate == payload:
            return identifier
    dictionary_id = next(iter(dictionaries), None) if isinstance(payload, str) else None
    stored, encoding, size = peri_scribe.geo.payload_storage.encode(
        payload,
        dictionary=dictionaries.get(dictionary_id),
    )
    extra_column = ", dictionary_id" if kind is PayloadKind.ATTRIBUTES else ""
    extra_placeholder = ", ?" if kind is PayloadKind.ATTRIBUTES else ""
    values = (digest, stored, encoding, size)
    if kind is PayloadKind.ATTRIBUTES:
        values += (dictionary_id,)
    return typing.cast(
        "int",
        conn.execute(
            f"INSERT INTO {kind.value} (digest, value, encoding, original_size"
            f"{extra_column}) VALUES (?, ?, ?, ?{extra_placeholder})",
            values,
        ).lastrowid,
    )


def payload_digest(payload: bytes | str) -> bytes:
    """Keep indexes compact while exact candidate checks resolve hash collisions.

    Args:
        payload: Complete binary geometry or canonical attribute text.

    Returns:
        The digest selecting dictionary equality candidates.
    """
    return hashlib.sha256(
        payload.encode() if isinstance(payload, str) else payload,
    ).digest()


def normalized_row(
    conn: sqlite3.Connection,
    row: peri_scribe.geo.package.FireRowRecord,
    serial: int,
) -> tuple[object, ...]:
    """Retain every row occurrence while replacing repeated payloads with references.

    Args:
        conn: The snapshot writer's current transaction.
        row: Complete immutable record fields and caller-owned attributes.
        serial: The snapshot serial owning this occurrence.

    Returns:
        Typed metadata, dictionary keys, and a complete path-independent fingerprint.
    """
    values = row.to_row(serial)
    geometry = typing.cast("bytes | None", values[7])
    attributes = typing.cast("str", values[12])
    geometry_key = (
        None
        if geometry is None
        else intern_payload(conn, PayloadKind.GEOMETRY, geometry)
    )
    attributes_key = intern_payload(conn, PayloadKind.ATTRIBUTES, attributes)
    fingerprint = peri_scribe.geo.fingerprints.fingerprint_from_payloads(
        row,
        None if geometry is None else hashlib.sha256(geometry).hexdigest(),
        hashlib.sha256(attributes.encode()).hexdigest(),
    )
    return (*values[:7], geometry_key, *values[8:12], attributes_key, fingerprint)


def collect_unreferenced_payloads(conn: sqlite3.Connection) -> None:
    """Retire only encodings no surviving row can reference in this transaction.

    Args:
        conn: The transaction replacing or deleting complete snapshot row sets.
    """
    conn.execute(
        "DELETE FROM geometry_payloads WHERE id NOT IN "
        "(SELECT geometry_id FROM rows WHERE geometry_id IS NOT NULL)",
    )
    conn.execute(
        "DELETE FROM attribute_payloads WHERE id NOT IN "
        "(SELECT attributes_id FROM rows)",
    )


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
    *,
    checksum: str,
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
        checksum: The SHA-256 identity of the snapshot bytes that were parsed.
    """
    conn.execute(
        "INSERT OR REPLACE INTO snapshots VALUES (?, ?, ?, ?, ?)",
        (
            source_file.serial_number,
            source_file.last_edit_timestamp,
            size,
            mtime_ns,
            checksum,
        ),
    )
    conn.execute("DELETE FROM rows WHERE serial = ?", (source_file.serial_number,))
    conn.execute(
        "DELETE FROM memberships WHERE serial = ?",
        (source_file.serial_number,),
    )
    conn.executemany(
        "INSERT INTO rows (serial, object_id, source_name, name, status, "
        "identifiers, names, geometry_id, observed_at, mission, "
        "point_of_origin_state, point_of_origin_fips, attributes_id, "
        "evidence_fingerprint) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [normalized_row(conn, row, source_file.serial_number) for row in contents.rows],
    )
    conn.executemany(
        "INSERT INTO memberships VALUES (?, ?, ?, ?, ?)",
        [
            (
                source_file.serial_number,
                membership.fire_identifier,
                membership.complex_identifier,
                membership.complex_name,
                membership.observation_time.isoformat()
                if membership.observation_time is not None
                else None,
            )
            for membership in contents.memberships
        ],
    )


def snapshot_directories_signature(
    source_directory: pathlib.Path,
) -> tuple[tuple[str, int], ...] | None:
    """Detect snapshot inventory changes made by the application's atomic writer.

    Snapshots live in bucket subdirectories named for the serial number's thousands.
    Creating, removing, or atomically replacing a snapshot changes its bucket's
    modification time. Adding or removing a bucket changes the set of buckets. Those two
    observations identify changes made by the application.

    External edits made in place or with restored timestamps can escape this check.
    Readers therefore also compare each snapshot's contents with its cached checksum.
    The feed directory's own modification time is excluded: writes to the cache and
    current-state files there should not force snapshot synchronization.

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


def snapshot_checksum(path: pathlib.Path) -> str:
    """Authenticate snapshot contents independently of mutable filesystem timestamps.

    Args:
        path: The authoritative snapshot whose parsed records may be cached.

    Returns:
        The SHA-256 checksum of all snapshot bytes.
    """
    return peri_scribe.sources.authentication.file_digest(path)


def sync_database(conn: sqlite3.Connection, source_directory: pathlib.Path) -> None:
    """Bring *conn*'s snapshot rows in line with *source_directory*'s files.

    Check the source bytes even when a replacement preserves the file's size and
    modification time. Remove records for missing snapshots and keep parsed records
    whose contents have not changed.

    Args:
        conn: The record cache database connection.
        source_directory: The feed's snapshot directory.
    """
    stored = {
        serial: (size, mtime_ns, checksum)
        for serial, size, mtime_ns, checksum in conn.execute(
            "SELECT serial, size, mtime_ns, checksum FROM snapshots",
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
    removed = set(stored) - set(current)
    changed = bool(removed)
    for serial in removed:
        conn.execute("DELETE FROM rows WHERE serial = ?", (serial,))
        conn.execute("DELETE FROM memberships WHERE serial = ?", (serial,))
        conn.execute("DELETE FROM snapshots WHERE serial = ?", (serial,))
    for serial, (source_file, size, mtime_ns) in current.items():
        path = source_directory / source_file.relative_path
        checksum = snapshot_checksum(path)
        if stored.get(serial) == (size, mtime_ns, checksum):
            continue
        changed = True
        contents = peri_scribe.geo.package.read_geopackage(path)
        write_snapshot(conn, source_file, size, mtime_ns, contents, checksum=checksum)
    if changed:
        collect_unreferenced_payloads(conn)
        peri_scribe.geo.payload_storage.prepare_dictionary(conn)
    conn.commit()


def open_and_sync(db_path: pathlib.Path, source_directory: pathlib.Path) -> None:
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
    with peri_scribe.geo.compaction.writer_lock(db_path):
        try:
            open_and_sync(db_path, source_directory)
        except sqlite3.DatabaseError, ValueError:
            logger.debug(
                "Record cache database unusable; rebuilding",
                path=str(db_path),
                exc_info=True,
            )
            with contextlib.suppress(OSError):
                db_path.unlink()
            open_and_sync(db_path, source_directory)
        try:
            peri_scribe.geo.compaction.compact(db_path, RECORD_CACHE_SCHEMA)
        except OSError, ValueError, sqlite3.Error:
            logger.warning(
                "Record cache compaction unavailable; keeping synchronized data",
                path=str(db_path),
                exc_info=True,
            )
    RECORD_CACHE_SYNCED[db_path] = signature
