"""Parsed snapshot caches preserve source row and membership order."""

import contextlib
import sqlite3

import peri_scribe.geo.database
import peri_scribe.geo.reading
import spatial_data.geometry_pool
import tests.helpers.factories.peri_scribe.geo.database


def test_fetch_snapshot_rows_preserves_source_order() -> None:
    with contextlib.closing(sqlite3.connect(":memory:")) as connection:
        peri_scribe.geo.database.reset_database(connection)
        tests.helpers.factories.peri_scribe.geo.database.store(connection, 1)
        connection.execute("PRAGMA reverse_unordered_selects = ON")

        actual = peri_scribe.geo.reading.fetch_snapshot_rows(
            connection,
            1,
            checksum="1",
            geometry_pool=spatial_data.geometry_pool.GeometryPool(),
        )

        assert actual == tests.helpers.factories.peri_scribe.geo.database.contents(1)
