"""Upgrade selected disposable caches without reopening source files."""

import argparse
import contextlib
import pathlib
import sqlite3

import peri_scribe.geo.compaction
import peri_scribe.geo.database
import peri_scribe.geo.payload_storage


INPUT_SCHEMA_VERSION = 8


def upgrade(path: pathlib.Path) -> None:
    """Preserve receipts, payload identity, and implicit occurrence order atomically.

    Args:
        path: An existing schema-eight parsed cache explicitly selected by the operator.

    Raises:
        ValueError: If schema or exact payload checksums cannot authenticate the input.
    """
    with (
        peri_scribe.geo.compaction.writer_lock(path),
        contextlib.closing(
            sqlite3.connect(path.resolve().as_uri() + "?mode=rw", uri=True),
        ) as connection,
    ):
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version == peri_scribe.geo.database.RECORD_CACHE_SCHEMA_VERSION:
            return
        if version != INPUT_SCHEMA_VERSION:
            message = f"Expected schema 8 or current schema: {path} has {version}"
            raise ValueError(message)
        connection.execute("BEGIN IMMEDIATE")
        for kind in peri_scribe.geo.database.PayloadKind:
            connection.execute(
                f"ALTER TABLE {kind.value} ADD COLUMN encoding "
                "INTEGER NOT NULL DEFAULT 0",
            )
            connection.execute(
                f"ALTER TABLE {kind.value} ADD COLUMN original_size "
                "INTEGER NOT NULL DEFAULT 0",
            )
            for identifier, digest, value in connection.execute(
                f"SELECT id, digest, value FROM {kind.value} ORDER BY id",
            ):
                if peri_scribe.geo.database.payload_digest(value) != digest:
                    message = f"Invalid logical payload checksum: {path}, {identifier}"
                    raise ValueError(message)
                stored, encoding, size = peri_scribe.geo.payload_storage.encode(value)
                connection.execute(
                    f"UPDATE {kind.value} SET value = ?, encoding = ?, "
                    "original_size = ? WHERE id = ?",
                    (stored, encoding, size, identifier),
                )
        connection.execute(
            "ALTER TABLE attribute_payloads ADD COLUMN dictionary_id INTEGER",
        )
        connection.execute(
            "CREATE TABLE codec_dictionaries "
            "(id INTEGER PRIMARY KEY, value BLOB NOT NULL)",
        )
        peri_scribe.geo.payload_storage.prepare_dictionary(connection)
        connection.execute(
            "PRAGMA user_version = "
            f"{peri_scribe.geo.database.RECORD_CACHE_SCHEMA_VERSION}",
        )
        connection.commit()


def main() -> None:
    """Require explicit cache paths so authoritative source files remain untouched."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("databases", type=pathlib.Path, nargs="+")
    arguments = parser.parse_args()
    for path in arguments.databases:
        upgrade(path)
        with peri_scribe.geo.compaction.writer_lock(path):
            peri_scribe.geo.compaction.compact(
                path,
                peri_scribe.geo.database.RECORD_CACHE_SCHEMA,
                force=True,
            )


if __name__ == "__main__":
    main()
