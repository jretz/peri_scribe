"""Small parsed caches with sparse occurrence keys and reclaimable free pages."""

import contextlib
import pathlib
import sqlite3

import peri_scribe.geo.compaction
import peri_scribe.geo.database
import tests.helpers.factories.peri_scribe.geo.database


def database(path: pathlib.Path, sequence: tuple[int, ...] = (2, 1, 2)) -> None:
    """Keep duplicate observations and noncontiguous keys visible through compaction.

    Args:
        path: New test cache path.
        sequence: Ordered symbolic revisions with independently retained occurrences.
    """
    with contextlib.closing(sqlite3.connect(path)) as connection:
        peri_scribe.geo.database.reset_database(connection)
        for serial, revision in enumerate(sequence, 1):
            tests.helpers.factories.peri_scribe.geo.database.store(
                connection,
                revision,
                serial,
            )
        connection.execute("UPDATE rows SET rowid = rowid + 100")
        connection.execute("UPDATE memberships SET rowid = rowid + 200")
        connection.execute("CREATE TABLE padding(value BLOB)")
        connection.execute("INSERT INTO padding VALUES (zeroblob(65536))")
        connection.commit()
        connection.execute("DROP TABLE padding")
        connection.commit()


def signature(path: pathlib.Path) -> tuple[tuple[tuple[object, ...], ...], ...]:
    """Expose every stored value and occurrence key independently of parsed decoding.

    Args:
        path: Complete cache whose exact stored contents are being compared.

    Returns:
        Every table's ordered complete rows, including implicit keys.
    """
    with contextlib.closing(sqlite3.connect(path)) as connection:
        return tuple(
            tuple(connection.execute(f"SELECT rowid, * FROM {table} ORDER BY rowid"))
            for table in peri_scribe.geo.compaction.TABLES
        )
