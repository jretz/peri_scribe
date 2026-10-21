"""Normalized dictionary storage retains exact payload identity and references."""

import contextlib
import pathlib
import sqlite3
import typing
import unittest.mock


if typing.TYPE_CHECKING:
    import pytest

import peri_scribe.geo.database
import peri_scribe.geo.package
import peri_scribe.geo.reading
import peri_scribe.sources.snapshots
import spatial_data.geometry_pool
import tests.helpers.factories.peri_scribe.geo.database


def test_sync_database_skips_unchanged_parses_and_dictionary_reclamation(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "feed"
    path = (
        source
        / peri_scribe.sources.snapshots.SourceFile(
            serial_number=1,
            last_edit_timestamp=1,
        ).relative_path
    )
    path.parent.mkdir(parents=True)
    path.write_bytes(b"stable source")
    parse = unittest.mock.Mock(
        return_value=tests.helpers.factories.peri_scribe.geo.database.contents(1),
    )
    monkeypatch.setattr(peri_scribe.geo.package, "read_geopackage", parse)
    with contextlib.closing(sqlite3.connect(":memory:")) as connection:
        peri_scribe.geo.database.reset_database(connection)
        peri_scribe.geo.database.sync_database(connection, source)
        parse.reset_mock()
        collect = unittest.mock.Mock(
            side_effect=AssertionError("Unexpected collection"),
        )
        monkeypatch.setattr(
            peri_scribe.geo.database,
            "collect_unreferenced_payloads",
            collect,
        )
        peri_scribe.geo.database.sync_database(connection, source)
        assert not parse.called
        assert not collect.called


def test_intern_payload_resolves_digest_collisions_with_complete_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        peri_scribe.geo.database,
        "payload_digest",
        unittest.mock.Mock(return_value=b"same candidate digest"),
    )
    with contextlib.closing(sqlite3.connect(":memory:")) as connection:
        peri_scribe.geo.database.reset_database(connection)
        kind = peri_scribe.geo.database.PayloadKind.GEOMETRY
        first = peri_scribe.geo.database.intern_payload(connection, kind, b"first")
        second = peri_scribe.geo.database.intern_payload(connection, kind, b"second")
        assert first != second
        assert (
            peri_scribe.geo.database.intern_payload(connection, kind, b"first") == first
        )
        assert connection.execute(
            "SELECT value FROM geometry_payloads ORDER BY id",
        ).fetchall() == [(b"first",), (b"second",)]


def test_collect_unreferenced_payloads_retains_surviving_snapshot_references() -> None:
    with contextlib.closing(sqlite3.connect(":memory:")) as connection:
        peri_scribe.geo.database.reset_database(connection)
        for serial in (1, 2):
            tests.helpers.factories.peri_scribe.geo.database.store(
                connection,
                1,
                serial,
            )
        tests.helpers.factories.peri_scribe.geo.database.store(connection, 2, 3)
        for table in ("rows", "memberships", "snapshots"):
            connection.execute(f"DELETE FROM {table} WHERE serial IN (1, 3)")
        peri_scribe.geo.database.collect_unreferenced_payloads(connection)
        for table in ("geometry_payloads", "attribute_payloads"):
            assert connection.execute(f"SELECT count(*) FROM {table}").fetchone()[
                0
            ] == len(tests.helpers.factories.peri_scribe.geo.database.contents(1).rows)
        actual = peri_scribe.geo.reading.fetch_snapshot_batch(
            connection,
            {pathlib.Path("survivor"): (2, "1")},
            geometry_pool=spatial_data.geometry_pool.GeometryPool(),
        )
        assert actual[pathlib.Path("survivor")] == (
            tests.helpers.factories.peri_scribe.geo.database.contents(1)
        )
