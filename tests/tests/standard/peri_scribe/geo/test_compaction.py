import contextlib
import pathlib
import sqlite3
import typing
import unittest.mock

import pytest

import peri_scribe.geo.compaction
import peri_scribe.geo.database
import tests.helpers.doubles.peri_scribe.geo.compaction
import tests.helpers.factories.peri_scribe.geo.compaction


def test_compact_preserves_every_value_and_sparse_occurrence_key(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "cache.db"
    tests.helpers.factories.peri_scribe.geo.compaction.database(path)
    expected = tests.helpers.factories.peri_scribe.geo.compaction.signature(path)
    size = path.stat().st_size
    monkeypatch.setattr(peri_scribe.geo.compaction, "MINIMUM_FREE_BYTES", 1)
    with peri_scribe.geo.compaction.writer_lock(path):
        assert peri_scribe.geo.compaction.compact(
            path,
            peri_scribe.geo.database.RECORD_CACHE_SCHEMA,
        )
    assert (
        tests.helpers.factories.peri_scribe.geo.compaction.signature(path) == expected
    )
    assert path.stat().st_size < size


def test_compact_keeps_an_admitted_reader_on_its_complete_original(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "cache.db"
    tests.helpers.factories.peri_scribe.geo.compaction.database(path)
    monkeypatch.setattr(peri_scribe.geo.compaction, "MINIMUM_FREE_BYTES", 1)
    with contextlib.closing(sqlite3.connect(path)) as reader:
        reader.execute("BEGIN")
        expected = reader.execute("SELECT rowid, * FROM rows ORDER BY rowid").fetchall()
        with peri_scribe.geo.compaction.writer_lock(path):
            peri_scribe.geo.compaction.compact(
                path,
                peri_scribe.geo.database.RECORD_CACHE_SCHEMA,
            )
        assert (
            reader.execute("SELECT rowid, * FROM rows ORDER BY rowid").fetchall()
            == expected
        )


@pytest.mark.parametrize("journal", ["delete", "wal"])
def test_compact_skips_small_or_wal_databases(
    tmp_path: pathlib.Path,
    journal: str,
) -> None:
    path = tmp_path / "cache.db"
    tests.helpers.factories.peri_scribe.geo.compaction.database(path)
    with contextlib.closing(sqlite3.connect(path)) as connection:
        connection.execute(f"PRAGMA journal_mode = {journal}")
    before = path.read_bytes()
    assert not peri_scribe.geo.compaction.compact(
        path,
        peri_scribe.geo.database.RECORD_CACHE_SCHEMA,
    )
    assert path.read_bytes() == before


def test_validate_rejects_changed_occurrence_keys(tmp_path: pathlib.Path) -> None:
    original = tmp_path / "original.db"
    target = tmp_path / "target.db"
    for path in (original, target):
        tests.helpers.factories.peri_scribe.geo.compaction.database(path)
    with (
        contextlib.closing(sqlite3.connect(original)) as source,
        contextlib.closing(sqlite3.connect(target)) as candidate,
    ):
        candidate.execute("UPDATE rows SET rowid = rowid + 1000")
        with pytest.raises(ValueError, match="changed ordered rows"):
            peri_scribe.geo.compaction.validate(source, candidate)


def test_validate_rejects_missing_memberships(tmp_path: pathlib.Path) -> None:
    original = tmp_path / "original.db"
    target = tmp_path / "target.db"
    for path in (original, target):
        tests.helpers.factories.peri_scribe.geo.compaction.database(path)
    with (
        contextlib.closing(sqlite3.connect(original)) as source,
        contextlib.closing(sqlite3.connect(target)) as candidate,
    ):
        candidate.execute("DELETE FROM memberships")
        with pytest.raises(ValueError, match="shorter"):
            peri_scribe.geo.compaction.validate(source, candidate)


def test_validate_rejects_sqlite_integrity_errors(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "source.db"
    tests.helpers.factories.peri_scribe.geo.compaction.database(path)
    with contextlib.closing(sqlite3.connect(path)) as source:
        target = unittest.mock.Mock()
        target.execute.return_value.fetchall.return_value = [("damaged index",)]
        with (
            unittest.mock.patch.object(
                peri_scribe.geo.compaction,
                "ordered_rows",
                return_value=iter(()),
            ),
            pytest.raises(ValueError, match="SQLite integrity"),
        ):
            peri_scribe.geo.compaction.validate(
                source,
                typing.cast("sqlite3.Connection", target),
            )


def test_compact_preserves_original_after_failed_publication(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "source.db"
    tests.helpers.factories.peri_scribe.geo.compaction.database(path)
    before = path.read_bytes()
    monkeypatch.setattr(peri_scribe.geo.compaction, "MINIMUM_FREE_BYTES", 1)
    monkeypatch.setattr(
        pathlib.Path,
        "replace",
        unittest.mock.Mock(side_effect=OSError("cannot publish")),
    )
    with pytest.raises(OSError, match="cannot publish"):
        peri_scribe.geo.compaction.compact(
            path,
            peri_scribe.geo.database.RECORD_CACHE_SCHEMA,
        )
    assert path.read_bytes() == before
    assert not list(tmp_path.glob(".source.db-compact-*"))


def test_ensure_database_current_retains_cache_after_failed_compaction(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "source.db"
    tests.helpers.factories.peri_scribe.geo.compaction.database(path)
    expected = path.read_bytes()
    monkeypatch.setattr(peri_scribe.geo.database, "open_and_sync", unittest.mock.Mock())
    monkeypatch.setattr(
        peri_scribe.geo.compaction,
        "compact",
        unittest.mock.Mock(side_effect=OSError("no staging space")),
    )
    peri_scribe.geo.database.ensure_database_current(path, tmp_path)
    assert path.read_bytes() == expected


def test_writer_lock_excludes_other_processes_until_owner_closes(
    tmp_path: pathlib.Path,
) -> None:
    path = tmp_path / "source.db"
    with peri_scribe.geo.compaction.writer_lock(path):
        assert (
            tests.helpers.doubles.peri_scribe.geo.compaction.lock_status(path)
            == "blocked"
        )
    assert (
        tests.helpers.doubles.peri_scribe.geo.compaction.lock_status(path) == "acquired"
    )


@pytest.mark.parametrize("phase", ["copy", "closed", "published"])
def test_compact_process_termination_preserves_exact_complete_contents(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
) -> None:
    path = tmp_path / "source.db"
    tests.helpers.factories.peri_scribe.geo.compaction.database(path)
    expected = tests.helpers.factories.peri_scribe.geo.compaction.signature(path)
    assert tests.helpers.doubles.peri_scribe.geo.compaction.crash(path, phase) == (
        tests.helpers.doubles.peri_scribe.geo.compaction.CRASH_STATUS
    )
    assert (
        tests.helpers.factories.peri_scribe.geo.compaction.signature(path) == expected
    )
    monkeypatch.setattr(peri_scribe.geo.compaction, "MINIMUM_FREE_BYTES", 1)
    with peri_scribe.geo.compaction.writer_lock(path):
        peri_scribe.geo.compaction.compact(
            path,
            peri_scribe.geo.database.RECORD_CACHE_SCHEMA,
        )
    assert (
        tests.helpers.factories.peri_scribe.geo.compaction.signature(path) == expected
    )
    assert not list(tmp_path.glob(".source.db-compact-*"))


def test_warranted_skips_small_fraction_of_unused_pages(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "source.db"
    with contextlib.closing(sqlite3.connect(path)) as connection:
        connection.execute("CREATE TABLE retained(value BLOB)")
        connection.execute("INSERT INTO retained VALUES (zeroblob(1048576))")
        connection.execute("CREATE TABLE temporary(value BLOB)")
        connection.execute("INSERT INTO temporary VALUES (zeroblob(65536))")
        connection.commit()
        connection.execute("DROP TABLE temporary")
        connection.commit()
        monkeypatch.setattr(peri_scribe.geo.compaction, "MINIMUM_FREE_BYTES", 1)
        assert not peri_scribe.geo.compaction.warranted(connection)


@pytest.mark.parametrize("journal", ["delete", "wal"])
def test_explicit_compaction_repacks_small_cache_but_keeps_journal_boundary(
    tmp_path: pathlib.Path,
    journal: str,
) -> None:
    path = tmp_path / "cache.db"
    tests.helpers.factories.peri_scribe.geo.compaction.database(path)
    expected = tests.helpers.factories.peri_scribe.geo.compaction.signature(path)
    with contextlib.closing(sqlite3.connect(path)) as connection:
        connection.execute(f"PRAGMA journal_mode = {journal}")
    with peri_scribe.geo.compaction.writer_lock(path):
        changed = peri_scribe.geo.compaction.compact(
            path,
            peri_scribe.geo.database.RECORD_CACHE_SCHEMA,
            force=True,
        )
    assert changed == (journal == "delete")
    assert (
        tests.helpers.factories.peri_scribe.geo.compaction.signature(path) == expected
    )
