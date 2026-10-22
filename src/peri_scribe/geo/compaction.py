"""Reclaim disposable parsed-cache pages while preserving exact source occurrence order.

Design: [Ordered cache compaction](../../../docs/algorithms/parsed-cache-compaction.md).
"""

import collections.abc
import contextlib
import fcntl
import pathlib
import shutil
import sqlite3
import tempfile


TABLES = (
    "snapshots",
    "rows",
    "memberships",
    "geometry_payloads",
    "attribute_payloads",
    "codec_dictionaries",
)
MINIMUM_FREE_BYTES = 8 * 1024 * 1024


@contextlib.contextmanager
def writer_lock(path: pathlib.Path) -> collections.abc.Generator[None]:
    """Serialize cooperating cache writers across replacement of the database inode.

    Args:
        path: Parsed cache whose stable neighboring lock belongs to every writer.

    Yields:
        Control with exclusive ownership of synchronization and replacement.
    """
    with path.with_suffix(path.suffix + ".lock").open("a+b") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield


def warranted(connection: sqlite3.Connection) -> bool:
    """Amortize rewriting against substantial absolute and proportional free space.

    WAL files retain companions tied to their database inode. The application's normal
    rollback-journal cache can be replaced after its SQLite connections close.

    Args:
        connection: The cache owned by the cooperating writer lock.

    Returns:
        Whether at least eight MiB and one quarter of its pages are unused.
    """
    if connection.execute("PRAGMA journal_mode").fetchone()[0] != "delete":
        return False
    pages = connection.execute("PRAGMA page_count").fetchone()[0]
    free = connection.execute("PRAGMA freelist_count").fetchone()[0]
    page_size = connection.execute("PRAGMA page_size").fetchone()[0]
    return free * page_size >= MINIMUM_FREE_BYTES and free * 4 >= pages


def ordered_rows(connection: sqlite3.Connection, table: str) -> sqlite3.Cursor:
    """Expose stable occurrence keys alongside every stored value for exact copying.

    Args:
        connection: Source or staged cache transaction.
        table: One of this module's fixed table names.

    Returns:
        A streaming cursor ordered by the stored row identity.
    """
    return connection.execute(f"SELECT rowid, * FROM {table} ORDER BY rowid")


def copy_table(
    source: sqlite3.Connection,
    target: sqlite3.Connection,
    table: str,
) -> None:
    """Retain sparse rowids explicitly because source occurrence order is meaningful.

    Args:
        source: The pinned original cache transaction.
        target: The private replacement transaction.
        table: One of this module's fixed table names.
    """
    columns = [
        "rowid",
        *(row[1] for row in source.execute(f"PRAGMA table_info({table})")),
    ]
    names = ", ".join(f'"{column}"' for column in columns)
    placeholders = ", ".join("?" for _column in columns)
    target.executemany(
        f"INSERT INTO {table} ({names}) VALUES ({placeholders})",
        ordered_rows(source, table),
    )


def validate(source: sqlite3.Connection, target: sqlite3.Connection) -> None:
    """Reject a replacement with any changed value, identity, order or SQLite damage.

    Args:
        source: The original cache still protected by its writer ownership.
        target: The complete replacement cache.

    Raises:
        ValueError: If the candidate differs or its SQLite structure is invalid.
    """
    for table in TABLES:
        for original, copied in zip(
            ordered_rows(source, table),
            ordered_rows(target, table),
            strict=True,
        ):
            if original != copied:
                message = f"Compacted cache changed ordered {table} contents"
                raise ValueError(message)
    if target.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
        message = "Compacted cache failed SQLite integrity checking"
        raise ValueError(message)


def prepare(
    path: pathlib.Path,
    target: pathlib.Path,
    schema: str,
    *,
    force: bool = False,
) -> bool:
    """Build and validate a complete candidate, closing every SQLite handle on return.

    Args:
        path: Original cache protected by the caller's stable writer lock.
        target: Private new file beside the original cache.
        schema: Current parsed-cache tables and indexes.
        force: Repack within-page slack even below the usual freelist thresholds.

    Returns:
        Whether enough unused space justified constructing a replacement.
    """
    with contextlib.closing(
        sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True),
    ) as source:
        if not warranted(source) and not (
            force and source.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
        ):
            return False
        source.execute("BEGIN")
        with contextlib.closing(sqlite3.connect(target)) as candidate:
            candidate.executescript(schema)
            for table in TABLES:
                copy_table(source, candidate, table)
            version = source.execute("PRAGMA user_version").fetchone()[0]
            candidate.execute(f"PRAGMA user_version = {version}")
            candidate.commit()
            validate(source, candidate)
    return True


def compact(path: pathlib.Path, schema: str, *, force: bool = False) -> bool:
    """Publish a verified complete replacement under the caller's cache writer lock.

    Admitted readers retain the complete original inode. New readers open the complete
    replacement after the atomic rename. Failed preparation leaves the original intact.

    Args:
        path: Parsed cache whose synchronized SQLite writer has already closed.
        schema: Current parsed-cache tables and indexes.
        force: Repack within-page slack even below the usual freelist thresholds.

    Returns:
        Whether a compact replacement was published.
    """
    prefix = f".{path.name}-compact-"
    for abandoned in path.parent.glob(prefix + "*"):
        shutil.rmtree(abandoned)
    with tempfile.TemporaryDirectory(prefix=prefix, dir=path.parent) as name:
        target = pathlib.Path(name) / "cache.sqlite"
        prepared = (
            prepare(path, target, schema, force=True)
            if force
            else prepare(path, target, schema)
        )
        if not prepared:
            return False
        target.replace(path)
    return True
