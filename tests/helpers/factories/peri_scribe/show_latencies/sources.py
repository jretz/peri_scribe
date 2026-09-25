"""Source metadata fixtures ensure chart reads never need polygon coordinates."""

from __future__ import annotations

import contextlib
import datetime
import pathlib
import sqlite3

import peri_scribe.models
import peri_scribe.show_latencies.sources
import peri_scribe.sources.feed_types
import peri_scribe.sources.snapshots
import tests.helpers.factories.peri_scribe.show_latencies.evidence


def record(
    feed: peri_scribe.sources.feed_types.Feed,
    object_id: int | None = 1,
    *,
    identifier: str | None = "fire",
    name: str | None = "First",
    surveyed: int | None = 0,
    created: int | None = None,
    geometry: bytes | None = b"GP\x00\x01unread polygon coordinates",
) -> dict[str, object]:
    """Use a GeoPackage header with deliberately undecodable coordinate bytes.

    Args:
        feed: The configured source defining metadata column names.
        object_id: The source feature identifier.
        identifier: The feed's primary fire identifier.
        name: The fire name reported by the source.
        surveyed: Polygon survey seconds relative to the test window, or None.
        created: Polygon creation seconds relative to the test window, or None.
        geometry: Header and unused coordinate payload, or None for a missing polygon.

    Returns:
        Raw GeoPackage attributes for one source record.
    """
    now = tests.helpers.factories.peri_scribe.show_latencies.evidence.NOW
    return {
        peri_scribe.models.OBJECT_ID_COLUMN_NAME: object_id,
        feed.fire_identifier_columns[0]: identifier,
        feed.fire_identifier_columns[1]: None,
        feed.fire_name_column: name,
        "poly_DateCurrent": (
            (now + datetime.timedelta(seconds=surveyed)).isoformat()
            if surveyed is not None
            else None
        ),
        "poly_CreateDate": (
            (now + datetime.timedelta(seconds=created)).isoformat()
            if created is not None
            else None
        ),
        "geom": geometry,
    }


def snapshot(
    year_directory: pathlib.Path,
    feed: peri_scribe.sources.feed_types.Feed,
    serial: int,
    seconds: int,
    rows: list[dict[str, object]],
    *,
    geometry_type: str = "POLYGON",
) -> pathlib.Path:
    """Write authoritative SQLite metadata under the production snapshot naming scheme.

    Args:
        year_directory: The per-test retained year directory.
        feed: The source defining the GeoPackage table name.
        serial: Its immutable snapshot serial.
        seconds: Publication seconds relative to the test window.
        rows: Source metadata rows and their lightweight geometry headers.
        geometry_type: Geometry type declared by the snapshot layer.

    Returns:
        The written snapshot's path.
    """
    published = (
        tests.helpers.factories.peri_scribe.show_latencies.evidence.NOW
        + datetime.timedelta(seconds=seconds)
    )
    source = peri_scribe.sources.snapshots.SourceFile(
        serial_number=serial,
        last_edit_timestamp=int(published.timestamp() * 1000),
    )
    path = year_directory / "sources" / feed.name / source.relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = sorted({column for row in rows for column in row})
    names = ",".join(
        peri_scribe.show_latencies.sources.quoted_identifier(column)
        for column in columns
    )
    table = peri_scribe.show_latencies.sources.quoted_identifier(feed.name)
    with contextlib.closing(sqlite3.connect(path)) as connection:
        connection.execute(
            "CREATE TABLE gpkg_geometry_columns "
            "(table_name, column_name, geometry_type_name)",
        )
        connection.execute(
            "INSERT INTO gpkg_geometry_columns VALUES (?, ?, ?)",
            (feed.name, "geom", geometry_type),
        )
        connection.execute(f"CREATE TABLE {table} ({names})")
        placeholders = ",".join("?" for _ in columns)
        connection.executemany(
            f"INSERT INTO {table} VALUES ({placeholders})",
            [tuple(row.get(column) for column in columns) for row in rows],
        )
        connection.commit()
    return path
