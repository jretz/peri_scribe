"""Tests for snapshot replacement in the record cache database."""

from __future__ import annotations

import contextlib
import sqlite3

import hypothesis
import hypothesis.strategies

import peri_scribe.geo.database
import peri_scribe.geo.geometry_pool
import peri_scribe.geo.package
import peri_scribe.geo.reading
import peri_scribe.sources.snapshots
import tests.peri_scribe.geo.database_helpers


# This test is slow, so limit examples to keep routine test runs fast.
@hypothesis.settings(max_examples=25)
@hypothesis.given(
    updates=hypothesis.strategies.lists(
        hypothesis.strategies.tuples(
            hypothesis.strategies.integers(0, 3),
            tests.peri_scribe.geo.database_helpers.snapshot_contents(),
        ),
        max_size=10,
    ),
)
def test_write_snapshot_matches_last_write_wins_model(
    updates: list[tuple[int, peri_scribe.geo.package.GeopackageContents]],
) -> None:
    expected: dict[int, peri_scribe.geo.package.GeopackageContents] = {}
    metadata: dict[int, tuple[int, int, int, int]] = {}
    with contextlib.closing(sqlite3.connect(":memory:")) as connection:
        connection.row_factory = sqlite3.Row
        peri_scribe.geo.database.reset_database(connection)
        for revision, (serial, contents) in enumerate(updates):
            source_file = peri_scribe.sources.snapshots.SourceFile(
                serial_number=serial,
                last_edit_timestamp=revision,
            )
            peri_scribe.geo.database.write_snapshot(
                connection,
                source_file,
                size=revision + 10,
                mtime_ns=revision + 1000,
                contents=contents,
            )
            connection.commit()
            expected[serial] = contents
            metadata[serial] = (serial, revision, revision + 10, revision + 1000)
            stored = connection.execute("SELECT * FROM snapshots ORDER BY serial")
            assert [tuple(row) for row in stored] == [
                metadata[key] for key in sorted(metadata)
            ]
            pool = peri_scribe.geo.geometry_pool.GeometryPool()
            for key, snapshot in expected.items():
                actual = peri_scribe.geo.reading.read_snapshot_contents(
                    connection,
                    key,
                    geometry_pool=pool,
                )
                assert actual == snapshot
