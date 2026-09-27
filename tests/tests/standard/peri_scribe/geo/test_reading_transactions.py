"""Regressions for authenticating a parsed snapshot across concurrent commits."""

import contextlib
import pathlib
import sqlite3

import pytest

import peri_scribe.geo.database
import peri_scribe.geo.reading
import spatial_data.geometry_pool
import tests.helpers.doubles.peri_scribe.geo.reading
import tests.helpers.factories.peri_scribe.geo.database


@pytest.mark.parametrize("before_select", [2, 3])
@pytest.mark.parametrize("revision", [0, 2])
def test_fetch_snapshot_rows_preserves_authenticated_generation(
    tmp_path: pathlib.Path,
    before_select: int,
    revision: int,
) -> None:
    path = tmp_path / "record_cache.db"
    with (
        contextlib.closing(sqlite3.connect(path)) as writer,
        contextlib.closing(sqlite3.connect(path)) as reader,
    ):
        writer.execute("PRAGMA journal_mode = WAL")
        peri_scribe.geo.database.reset_database(writer)
        tests.helpers.factories.peri_scribe.geo.database.store(writer, 1)
        writer.commit()
        interleave = tests.helpers.doubles.peri_scribe.geo.reading.ConcurrentCommit(
            writer=writer,
            revision=revision,
            before_select=before_select,
        )
        reader.set_trace_callback(interleave)
        actual = peri_scribe.geo.reading.fetch_snapshot_rows(
            reader,
            1,
            checksum="1",
            geometry_pool=spatial_data.geometry_pool.GeometryPool(),
        )
        assert interleave.committed
        assert actual == tests.helpers.factories.peri_scribe.geo.database.contents(1)


def test_fetch_snapshot_rows_preserves_existing_caller_transaction(
    tmp_path: pathlib.Path,
) -> None:
    path = tmp_path / "record_cache.db"
    with (
        contextlib.closing(sqlite3.connect(path)) as writer,
        contextlib.closing(sqlite3.connect(path)) as observer,
    ):
        peri_scribe.geo.database.reset_database(writer)
        tests.helpers.factories.peri_scribe.geo.database.store(writer, 1)
        actual = peri_scribe.geo.reading.fetch_snapshot_rows(
            writer,
            1,
            checksum="1",
            geometry_pool=spatial_data.geometry_pool.GeometryPool(),
        )
        assert actual == tests.helpers.factories.peri_scribe.geo.database.contents(1)
        assert writer.in_transaction
        assert not observer.execute("SELECT 1 FROM snapshots").fetchall()
        writer.rollback()
        assert not writer.execute("SELECT 1 FROM snapshots").fetchall()
