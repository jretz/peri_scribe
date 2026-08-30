"""Reading fire records and complex memberships from GeoPackage files.

Interprets each configured feed's layer into fire records, full source rows, and complex
memberships, and provides the attribute-value helpers the rest of the project uses to
read those rows.
"""

from __future__ import annotations

import contextlib
import dataclasses
import datetime
import json
import pathlib
import re
import sqlite3
import threading
import typing

import geopandas
import pandas as pd
import shapely
import structlog
import us.states

import peri_scribe.exceptions
import peri_scribe.feed_types
import peri_scribe.feeds
import peri_scribe.models
import peri_scribe.snapshots


logger = structlog.get_logger()

# The schema version of the record cache databases; bump it whenever the stored record
# structure changes so that stale databases are rebuilt rather than misread.
RECORD_CACHE_SCHEMA_VERSION = 1

# One SQLite database per feed holds every snapshot's parsed records. The schema version
# is recorded in ``user_version``; the ``snapshots`` table records each snapshot file's
# size and modification time so the database can be checked against the filesystem, and
# the ``rows`` and ``memberships`` tables hold the parsed contents of each snapshot,
# keyed by its serial number.
_RECORD_CACHE_SCHEMA = """
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

# Serializes record cache database updates so that parallel readers never race to write
# the same database; reads take no lock.
_RECORD_CACHE_LOCK = threading.Lock()

# Remembers, per process, the snapshot-directory signature at which each record cache
# database was last verified, so steady-state reads skip the per-file freshness check.
# Every snapshot write goes through ``write_geopackage``, which unlinks and recreates
# the file, changing the bucket directory's modification time, so a changed snapshot set
# is still detected on the next read; the memo only skips re-verifying files that cannot
# have changed within this process.
_RECORD_CACHE_SYNCED: dict[pathlib.Path, tuple[int | tuple[str, int], ...]] = {}


def fire_status_from(value: object) -> peri_scribe.models.FireStatus | None:
    """Classify a feed's raw status value as active or inactive.

    Blank values (including None) are treated as missing and return None. Values
    that do not represent a known status raise an error, since they point at a
    misconfigured status column or unexpected data.

    Args:
        value: The raw status value from a feed.

    Returns:
        The corresponding fire status, or None when the value is blank.

    Raises:
        ValueError: If the value does not represent a known status.
    """
    if is_missing(value):
        return None
    normalized = str(value).strip().casefold()
    if normalized in {"1", "true", "active"}:
        return peri_scribe.models.FireStatus.ACTIVE
    if normalized in {"0", "false", "inactive"}:
        return peri_scribe.models.FireStatus.INACTIVE
    if normalized:
        message = f"Unknown fire status value: {value!r}"
        raise ValueError(message)
    return None


def is_missing(value: object) -> bool:
    """Return True when *value* is a missing (null) value.

    Pandas missing values are treated as missing, except for strings and bytes, which
    are never treated as missing here (an empty string is a present value). Values that
    pandas cannot truth-test (e.g. lists) are treated as present.

    Args:
        value: The value to test.

    Returns:
        True when *value* is missing.
    """
    if value is None:
        return True
    try:
        return bool(pd.isna(value)) and not isinstance(value, (str, bytes))
    except TypeError, ValueError:
        return False


def numeric_value(value: object) -> float | None:
    """Return *value* as a float, or None when it is missing or not numeric.

    Args:
        value: Any attribute value.

    Returns:
        The numeric value, or None when it cannot be interpreted as a number.
    """
    if is_missing(value):
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def geometries_describe_same_shape(
    left: shapely.Geometry | None,
    right: shapely.Geometry | None,
) -> bool:
    """Return whether two geometries describe the same shape.

    Shapes are compared topologically rather than byte-for-byte, so a source
    re-serializing an unchanged geometry (different vertex order, ring orientation, or
    ring type) still counts as the same shape. None and empty geometries each count as
    equal to themselves.

    Args:
        left: One geometry, or None.
        right: The other geometry, or None.

    Returns:
        True when the geometries are the same shape, or when both are None or empty.
    """
    if left is None or right is None:
        return left is None and right is None
    if left.is_empty or right.is_empty:
        return left.is_empty and right.is_empty
    if left.wkb == right.wkb:
        # Byte-identical geometries are the same shape; short-circuit before the
        # more expensive topological equality check.
        return True
    return left.equals(right)


def normalize_identifier(value: object) -> str | None:
    """Normalize a raw identifier value, or return None when it is missing.

    Identifiers are case-folded and stripped of surrounding braces so that equal
    identifiers match regardless of formatting, e.g. ``{286B7F1D-8945-4A5D-9D81-
    5235C18AF1FE}`` and ``286b7f1d-8945-4a5d-9d81-5235c18af1fe``. Blank values
    (including None and NaN) are treated as missing and return None.

    Args:
        value: The raw identifier value from a feed.

    Returns:
        The normalized identifier, or None when the value is missing.
    """
    if is_missing(value):
        return None
    text = str(value).strip()
    if not text:
        return None
    return text.casefold().strip("{}")


def is_complex_child_from(value: object) -> bool:
    """Classify a feed's raw complex child value.

    Blank values (including None) are treated as false. Values that do not represent a
    known boolean raise an error, since they point at a misconfigured column or
    unexpected data.

    Args:
        value: The raw complex child value from a feed.

    Returns:
        True when the value represents a complex child.

    Raises:
        ValueError: If the value does not represent a known boolean.
    """
    if value is None:
        return False
    normalized = str(value).strip().casefold()
    if normalized in {"1", "true", "yes"}:
        return True
    if normalized in {"0", "false", "no"}:
        return False
    if normalized:
        message = f"Unknown complex child value: {value!r}"
        raise ValueError(message)
    return False


MISSION_TAIL_PATTERN = re.compile(r"^[a-z]?\d{2}[a-z]$")

MINIMUM_UNIT_CODE_LENGTH = 3
UNIT_PREFIX_TOKEN_COUNT = 2

MISSION_NAME_NOISE_TOKENS = frozenset({
    "updated",
    "update",
    "revised",
    "final",
    "copy",
})


def fire_name_from(value: object) -> str | None:
    """Return *value* as a non-blank fire name, or None when it is missing.

    Args:
        value: A raw fire name value.

    Returns:
        The stripped name, or None when *value* is missing or blank.
    """
    if is_missing(value):
        return None
    text = str(value).strip()
    return text or None


def mission_name_from(value: object) -> peri_scribe.models.MissionName | None:
    """Return the fire-name parts of a mapping mission code, or None.

    A mission code such as ``CA-LNU-RUMSEY-UPDATED-N40Y`` is parsed into the fire name
    (``rumsey-updated``) and a base name with mapping-revision markers removed
    (``rumsey``), so an updated re-mapping can still be matched to the original fire.
    The leading state and unit tokens and a trailing aircraft-tail token are dropped
    when present.

    Args:
        value: A raw mission code value.

    Returns:
        The mission name parts, or None when *value* is missing, blank, or does not name
        a fire.
    """
    if is_missing(value):
        return None
    text = str(value).strip()
    if not text:
        return None
    tokens = text.split("-")
    folded = [token.casefold() for token in tokens]
    start = 0
    if (
        len(folded) >= UNIT_PREFIX_TOKEN_COUNT
        and us.states.lookup(folded[0]) is not None
        and len(folded[1]) >= MINIMUM_UNIT_CODE_LENGTH
        and folded[1].isalnum()
    ):
        start = 2
    end = len(folded)
    if end > start and MISSION_TAIL_PATTERN.fullmatch(folded[end - 1]) is not None:
        end -= 1
    name_tokens = tokens[start:end]
    if not name_tokens:
        return None
    folded_name_tokens = folded[start:end]
    base_tokens = list(name_tokens)
    folded_base_tokens = list(folded_name_tokens)
    while folded_base_tokens and folded_base_tokens[-1] in MISSION_NAME_NOISE_TOKENS:
        folded_base_tokens.pop()
        base_tokens.pop()
    name = "-".join(name_tokens)
    base_name = "-".join(base_tokens) if base_tokens else name
    return peri_scribe.models.MissionName(name=name, base_name=base_name)


def observation_time_from(value: object) -> datetime.datetime | None:
    """Parse an observation timestamp into an aware UTC datetime.

    Blank values are treated as missing. Naive datetimes are assumed to be UTC.

    Args:
        value: The raw observation timestamp value.

    Returns:
        The parsed UTC datetime, or None when *value* is blank or not parseable.
    """
    if is_missing(value):
        return None
    parsed: datetime.datetime | None
    if isinstance(value, datetime.datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.datetime.fromisoformat(value.strip())
        except ValueError:
            parsed = None
    else:
        parsed = None
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=datetime.UTC)
    return parsed.astimezone(datetime.UTC)


def fire_record_from_row(
    row: pd.Series,
    feed: peri_scribe.feed_types.Feed,
    geometry: shapely.Geometry | None,
) -> peri_scribe.models.FireRecord | None:
    """Return the fire record described by *row*, or None when it has none.

    A row yields no record when its status is missing or when neither its name column
    nor its mission code names a fire. Every identifier, name spelling, and timestamp is
    read from the columns the feed configures.

    Args:
        row: One feature row from a GeoPackage layer.
        feed: The feed that names the row's columns.
        geometry: The row's shapely geometry.

    Returns:
        The fire record, or None when the row does not describe a fire.
    """
    status = fire_status_from(row[feed.status_column])
    if status is None:
        return None
    recorded_name = fire_name_from(row[feed.fire_name_column])
    mission = mission_name_from(
        row[feed.mission_column] if feed.mission_column is not None else None,
    )
    name = recorded_name or (mission.name if mission is not None else None)
    if name is None:
        return None
    identifiers = frozenset(
        normalized
        for column in feed.fire_identifier_columns
        if (normalized := normalize_identifier(row[column])) is not None
    )
    names = frozenset(
        peri_scribe.models.normalize_fire_name(candidate)
        for candidate in (
            recorded_name,
            mission.name if mission is not None else None,
            mission.base_name if mission is not None else None,
        )
        if candidate is not None
    )
    observed_at = (
        observation_time_from(row[feed.observation_time_column])
        if feed.observation_time_column is not None
        else None
    )
    mission_code = (
        fire_name_from(row[feed.mission_column])
        if feed.mission_column is not None
        else None
    )
    point_of_origin_state = (
        fire_name_from(row[feed.point_of_origin_state_column])
        if feed.point_of_origin_state_column is not None
        else None
    )
    point_of_origin_fips = (
        fire_name_from(row[feed.point_of_origin_fips_column])
        if feed.point_of_origin_fips_column is not None
        else None
    )
    return peri_scribe.models.FireRecord(
        name=name,
        status=status,
        identifiers=identifiers,
        names=names,
        geometry=geometry,
        observed_at=observed_at,
        mission=mission_code,
        point_of_origin_state=point_of_origin_state,
        point_of_origin_fips=point_of_origin_fips,
    )


def layers_by_feed(
    path: pathlib.Path,
) -> typing.Iterator[tuple[peri_scribe.feed_types.Feed, geopandas.GeoDataFrame]]:
    """Yield each layer of the GeoPackage at *path* with its configured feed.

    Args:
        path: The GeoPackage file to read.

    Yields:
        Each ``(feed, dataframe)`` pair, one per layer, in the order encountered.

    Raises:
        UnknownLayerError: If a layer does not correspond to a configured feed.
    """
    feeds_by_name = {feed.name: feed for feed in peri_scribe.feeds.FEEDS}
    for layer_name in geopandas.list_layers(path)["name"]:
        feed = feeds_by_name.get(layer_name)
        if feed is None:
            raise peri_scribe.exceptions.UnknownLayerError(layer_name, path)
        yield feed, geopandas.read_file(path, layer=feed.name)


@dataclasses.dataclass(frozen=True, kw_only=True)
class FireRowRecord:
    """One fire source row with its identifying record and full attributes.

    The record carries the fire's identifying fields; the attributes carry every
    non-geometry column so downstream consumers can bring the row's own fields along.
    """

    record: peri_scribe.models.FireRecord
    object_id: int | None
    source_name: str
    attributes: dict[str, object]

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> FireRowRecord:
        """Return the row described by one record cache database row.

        The record's fixed fields come from typed columns and the attribute bag comes
        from a JSON column, mirroring how the row was stored by ``to_row``. The identity
        and name sets are rebuilt as frozensets and timestamps are parsed by the same
        normalization helpers the rest of the project uses.

        Args:
            row: One ``rows`` table row, keyed by column name.

        Returns:
            The fire row.
        """
        return cls(
            record=peri_scribe.models.FireRecord(
                name=row["name"],
                status=peri_scribe.models.FireStatus(row["status"]),
                identifiers=frozenset(json.loads(row["identifiers"])),
                names=frozenset(json.loads(row["names"])),
                geometry=(
                    shapely.from_wkb(row["geometry_wkb"])
                    if row["geometry_wkb"] is not None
                    else None
                ),
                observed_at=observation_time_from(row["observed_at"]),
                mission=row["mission"],
                point_of_origin_state=row["point_of_origin_state"],
                point_of_origin_fips=row["point_of_origin_fips"],
            ),
            object_id=row["object_id"],
            source_name=row["source_name"],
            attributes=json.loads(row["attributes_json"]),
        )

    def to_row(self, serial: int) -> tuple[object, ...]:
        """Return this row's record cache database columns, keyed by *serial*.

        Timestamps are stored as ISO-8601 text and the attribute bag as a JSON-safe
        object, so the database is inspectable with standard SQLite tools.

        Args:
            serial: The serial number of the snapshot the row came from.

        Returns:
            The ``rows`` table columns, in schema order.
        """
        record = self.record
        return (
            serial,
            self.object_id,
            self.source_name,
            record.name,
            record.status.value,
            json.dumps(sorted(record.identifiers)),
            json.dumps(sorted(record.names)),
            record.geometry.wkb if record.geometry is not None else None,
            (
                record.observed_at.isoformat()
                if record.observed_at is not None
                else None
            ),
            record.mission,
            record.point_of_origin_state,
            record.point_of_origin_fips,
            json.dumps(
                {
                    key: _json_cache_value(value)
                    for key, value in self.attributes.items()
                },
            ),
        )


@dataclasses.dataclass(frozen=True, kw_only=True)
class GeopackageContents:
    """Every fire row and complex membership in one GeoPackage file."""

    rows: tuple[FireRowRecord, ...]
    memberships: tuple[peri_scribe.models.ComplexMembership, ...]


def complex_membership_columns(
    feed: peri_scribe.feed_types.Feed,
) -> tuple[str, str, str, str] | None:
    """Return the columns used to read a complex membership, or None.

    A feed that does not declare identifier and complex columns records no memberships.

    Args:
        feed: The feed whose layer is being read.

    Returns:
        The fire identifier, complex identifier, complex name, and complex child
        columns, or None when the feed records no memberships.
    """
    if (
        not feed.fire_identifier_columns
        or feed.complex_identifier_column is None
        or feed.complex_name_column is None
        or feed.is_complex_child_column is None
    ):
        return None
    return (
        feed.fire_identifier_columns[0],
        feed.complex_identifier_column,
        feed.complex_name_column,
        feed.is_complex_child_column,
    )


def complex_membership_from_row(
    row: pd.Series,
    columns: tuple[str, str, str, str],
) -> peri_scribe.models.ComplexMembership | None:
    """Return the complex membership *row* records, or None.

    Args:
        row: One feature row.
        columns: The fire identifier, complex identifier, complex name, and complex
            child columns.

    Returns:
        The membership, or None when the row is not a complex child with a complete
        identifier pair and name.
    """
    fire_identifier_column, complex_identifier_column, complex_name_column, child = (
        columns
    )
    if any(
        is_missing(row[column])
        for column in (
            fire_identifier_column,
            complex_identifier_column,
            complex_name_column,
            child,
        )
    ):
        return None
    if not is_complex_child_from(row[child]):
        return None
    fire_identifier = normalize_identifier(row[fire_identifier_column])
    complex_identifier = normalize_identifier(row[complex_identifier_column])
    complex_name = fire_name_from(row[complex_name_column])
    if fire_identifier is None or complex_identifier is None or complex_name is None:
        return None
    return peri_scribe.models.ComplexMembership(
        fire_identifier=fire_identifier,
        complex_identifier=complex_identifier,
        complex_name=complex_name,
    )


def object_id_from(row: pd.Series) -> int | None:
    """Return the row's OBJECTID, or None when it is missing.

    Args:
        row: One feature row.

    Returns:
        The row's OBJECTID as an integer, or None when the row has none.
    """
    if peri_scribe.models.OBJECT_ID_COLUMN_NAME not in row.index:
        return None
    value = row[peri_scribe.models.OBJECT_ID_COLUMN_NAME]
    if is_missing(value):
        return None
    return int(value)


def row_attributes(
    row: pd.Series,
    geometry_name: str,
) -> dict[str, object]:
    """Return the row's non-geometry columns as a dictionary.

    Args:
        row: One feature row.
        geometry_name: The row's geometry column name.

    Returns:
        The row's attribute columns, keyed by column name.
    """
    return {
        str(column): row[column] for column in row.index if str(column) != geometry_name
    }


def read_geopackage(path: pathlib.Path) -> GeopackageContents:
    """Read the fire rows and complex memberships of the GeoPackage at *path*.

    Each layer is read once and each of its rows is walked once, so a row that both
    names a fire and records a complex membership contributes to both results. The file
    is only read, never written.

    Args:
        path: The GeoPackage file to read.

    Returns:
        The fire rows and complex memberships, each in row order.
    """
    rows: list[FireRowRecord] = []
    memberships: list[peri_scribe.models.ComplexMembership] = []
    for feed, dataframe in layers_by_feed(path):
        geometry_name = str(dataframe.geometry.name)
        membership_columns = complex_membership_columns(feed)
        for index in range(len(dataframe)):
            row = dataframe.iloc[index]
            record = fire_record_from_row(row, feed, row[geometry_name])
            if record is not None:
                rows.append(
                    FireRowRecord(
                        record=record,
                        object_id=object_id_from(row),
                        source_name=feed.name,
                        attributes=row_attributes(row, geometry_name),
                    ),
                )
            if membership_columns is not None:
                membership = complex_membership_from_row(row, membership_columns)
                if membership is not None:
                    memberships.append(membership)
    return GeopackageContents(rows=tuple(rows), memberships=tuple(memberships))


def _json_cache_value(value: object) -> object:
    """Return *value* in a JSON-serializable form for the record cache.

    Missing values become None, numpy scalars become their Python equivalents, and
    datetimes become ISO-8601 text, so the attribute bag stores cleanly in JSON.

    Args:
        value: An attribute value from a fire row.

    Returns:
        The JSON-serializable form of *value*.
    """
    if is_missing(value):
        return None
    if isinstance(value, (str, bool, int, float)):
        return value
    if hasattr(value, "item"):
        return typing.cast("typing.Any", value).item()
    if hasattr(value, "isoformat"):
        return typing.cast("typing.Any", value).isoformat()
    return str(value)


def _reset_database(conn: sqlite3.Connection) -> None:
    """Replace the record cache tables in *conn* with an empty current schema.

    Args:
        conn: The record cache database connection.
    """
    conn.executescript(
        "DROP TABLE IF EXISTS rows;"
        "DROP TABLE IF EXISTS memberships;"
        "DROP TABLE IF EXISTS snapshots;",
    )
    conn.executescript(_RECORD_CACHE_SCHEMA)
    conn.execute(f"PRAGMA user_version = {RECORD_CACHE_SCHEMA_VERSION}")
    conn.commit()


def _write_snapshot(
    conn: sqlite3.Connection,
    source_file: peri_scribe.snapshots.SourceFile,
    size: int,
    mtime_ns: int,
    contents: GeopackageContents,
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


def _snapshot_directories_signature(
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


def _sync_database(
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
    current: dict[int, tuple[peri_scribe.snapshots.SourceFile, int, int]] = {}
    for source_file in peri_scribe.snapshots.existing_source_files(source_directory):
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
        contents = read_geopackage(path)
        _write_snapshot(conn, source_file, size, mtime_ns, contents)
    conn.commit()


def _open_and_sync(
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
            _reset_database(conn)
        _sync_database(conn, source_directory)
    finally:
        conn.close()


def _ensure_database_current(
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
    signature = _snapshot_directories_signature(source_directory)
    if signature is None:
        # No snapshot directory to sync from.
        return
    if _RECORD_CACHE_SYNCED.get(db_path) == signature:
        return
    db_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        _open_and_sync(db_path, source_directory)
    except sqlite3.DatabaseError:
        logger.debug(
            "Record cache database unusable; rebuilding",
            path=str(db_path),
        )
        with contextlib.suppress(OSError):
            db_path.unlink()
        _open_and_sync(db_path, source_directory)
    _RECORD_CACHE_SYNCED[db_path] = signature


def _read_snapshot_contents(
    conn: sqlite3.Connection,
    serial: int,
) -> GeopackageContents:
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
    return GeopackageContents(
        rows=tuple(FireRowRecord.from_row(row) for row in rows),
        memberships=tuple(
            peri_scribe.models.ComplexMembership(
                fire_identifier=row["fire_identifier"],
                complex_identifier=row["complex_identifier"],
                complex_name=row["complex_name"],
            )
            for row in memberships
        ),
    )


def _fetch_snapshot_rows(
    conn: sqlite3.Connection,
    serial: int,
) -> GeopackageContents | None:
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
    return _read_snapshot_contents(conn, serial)


def _read_snapshot_rows(
    db_path: pathlib.Path,
    serial: int,
) -> GeopackageContents | None:
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
        return _fetch_snapshot_rows(conn, serial)
    finally:
        conn.close()


def _read_cached_snapshot(
    db_path: pathlib.Path,
    serial: int,
    path: pathlib.Path,
) -> GeopackageContents:
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
        contents = _read_snapshot_rows(db_path, serial)
    except OSError, ValueError, sqlite3.Error:
        logger.debug("Failed to read record cache", path=str(path))
        return read_geopackage(path)
    if contents is None:
        return read_geopackage(path)
    return contents


def read_geopackage_cached(path: pathlib.Path) -> GeopackageContents:
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
        db_path = peri_scribe.snapshots.record_cache_database_path(source_directory)
        serial = peri_scribe.snapshots.SourceFile.from_path(path).serial_number
    except OSError, ValueError:
        return read_geopackage(path)
    try:
        with _RECORD_CACHE_LOCK:
            _ensure_database_current(db_path, source_directory)
    except OSError, ValueError, sqlite3.Error:
        logger.debug("Failed to update record cache", path=str(path))
        return read_geopackage(path)
    return _read_cached_snapshot(db_path, serial, path)


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
    feed: peri_scribe.feed_types.Feed,
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
        yield from _read_gpkg_layer_chunks(path, layer_name, chunk_size)
        return
    yield from _read_skip_layer_chunks(path, layer_name, chunk_size)


def _read_skip_layer_chunks(
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


def _read_gpkg_layer_chunks(
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
