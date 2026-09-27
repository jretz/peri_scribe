"""Distinct parsed records for snapshot transaction and visibility checks."""

import datetime
import sqlite3

import shapely.geometry

import peri_scribe.geo.database
import peri_scribe.geo.package
import peri_scribe.models
import peri_scribe.sources.snapshots


def contents(revision: int) -> peri_scribe.geo.package.GeopackageContents:
    """Keep every persisted field distinguishable across revisions.

    Args:
        revision: A positive symbolic snapshot revision.

    Returns:
        Two ordered fire rows and complex memberships for that revision.
    """
    return peri_scribe.geo.package.GeopackageContents(
        rows=tuple(
            peri_scribe.geo.package.FireRowRecord(
                record=peri_scribe.models.FireRecord(
                    name=f"Fire {revision}-{index}",
                    status=peri_scribe.models.FireStatus.ACTIVE,
                    identifiers=frozenset({f"fire-{revision}-{index}"}),
                    names=frozenset({f"FIRE {revision}-{index}"}),
                    geometry=shapely.geometry.Point(revision, index),
                    observed_at=datetime.datetime(
                        2026,
                        1,
                        revision,
                        tzinfo=datetime.UTC,
                    ),
                    mission=f"mission-{revision}",
                    point_of_origin_state="US-CA",
                    point_of_origin_fips=f"{revision:05}",
                ),
                object_id=revision * 10 + index,
                source_name="formal_source",
                attributes={"revision": revision, "nested": [index, None, True]},
            )
            for index in (2, 1)
        ),
        memberships=tuple(
            peri_scribe.models.ComplexMembership(
                fire_identifier=f"fire-{revision}-{index}",
                complex_identifier=None if index == 1 else f"complex-{revision}",
                complex_name=None if index == 1 else f"Complex {revision}",
                observation_time=datetime.datetime(
                    2026,
                    1,
                    revision,
                    tzinfo=datetime.UTC,
                ),
            )
            for index in (2, 1)
        ),
    )


def store(connection: sqlite3.Connection, revision: int, serial: int = 1) -> None:
    """Apply one concrete snapshot mutation without deciding its commit boundary.

    Args:
        connection: The owning SQLite transaction.
        revision: Positive snapshot revision, or zero for a removed snapshot.
        serial: The snapshot identifier.
    """
    if revision:
        peri_scribe.geo.database.write_snapshot(
            connection,
            peri_scribe.sources.snapshots.SourceFile(
                serial_number=serial,
                last_edit_timestamp=revision,
            ),
            size=revision * 100,
            mtime_ns=revision * 1000,
            contents=contents(revision),
            checksum=str(revision),
        )
    else:
        for table in ("rows", "memberships", "snapshots"):
            connection.execute(f"DELETE FROM {table} WHERE serial = ?", (serial,))
