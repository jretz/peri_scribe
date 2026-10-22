"""Transaction failures must leave disposable cache writes unpublished."""

import pathlib
import sqlite3
import typing

import spatial_data.product_cache


class CommitFailureConnection(sqlite3.Connection):
    """Keep real SQLite rollback behavior while refusing the final commit."""

    @typing.override
    def commit(self) -> None:
        """Expose storage failure without replacing the actual transaction.

        Raises:
            sqlite3.OperationalError: The simulated storage device rejects commit.
        """
        message = "storage rejected commit"
        raise sqlite3.OperationalError(message)


def connect_with_commit_failure(
    path: pathlib.Path,
    *,
    timeout: float,
) -> sqlite3.Connection:
    """Allow ordinary reads and writes before the storage failure.

    Args:
        path: The isolated product database used by the test.
        timeout: The caller's lock-wait policy.

    Returns:
        A real connection that cannot commit.
    """
    return CommitFailureConnection(path, timeout=timeout)


def interrupt_product_replacement(path: pathlib.Path) -> typing.Never:
    """Interrupt after replacing an acknowledged value and adding a new one.

    Args:
        path: The isolated product database used by the test.

    Raises:
        RuntimeError: Publication fails after preparation has produced some results.
    """
    with spatial_data.product_cache.scope(path, "policy"):
        spatial_data.product_cache.put("history", "existing", b"partial replacement")
        spatial_data.product_cache.put("history", "new", b"partial addition")
        message = "publication interrupted"
        raise RuntimeError(message)


def interrupt_nested_publication(path: pathlib.Path) -> typing.Never:
    """Let a borrowed scope finish before its owning publication fails.

    Args:
        path: The isolated product database shared by both scopes.

    Raises:
        RuntimeError: Publication fails after the nested consumer completes.
    """
    with spatial_data.product_cache.scope(path, "policy"):
        spatial_data.product_cache.put("history", "outer", b"pending outer")
        with spatial_data.product_cache.scope(path, "policy"):
            spatial_data.product_cache.put("history", "inner", b"pending inner")
        message = "outer publication interrupted"
        raise RuntimeError(message)


def interrupt_pruned_publication(path: pathlib.Path) -> typing.Never:
    """Interrupt after replacing a generation and pruning its preceding products.

    Args:
        path: The isolated product database whose previous publication must survive.

    Raises:
        RuntimeError: Publication fails after the replacement was assembled.
    """
    with spatial_data.product_cache.scope(path, "policy"):
        spatial_data.product_cache.put("history", "replacement", b"pending publication")
        spatial_data.product_cache.prune("history", ["replacement"])
        message = "interrupted"
        raise RuntimeError(message)


def interrupt_changed_context(path: pathlib.Path) -> typing.Never:
    """A failed new-context publication must preserve the preceding cache contexts.

    Args:
        path: The isolated cache containing previous-context products.

    Raises:
        RuntimeError: Publication fails after writing an uncommitted current product.
    """
    with spatial_data.product_cache.scope(path, "current"):
        spatial_data.product_cache.put("history", "key", b"uncommitted")
        message = "publication failed"
        raise RuntimeError(message)


def hold_compaction_reader(
    reader: sqlite3.Connection,
    connection: sqlite3.Connection,
    *,
    retired: bool,
) -> bool:
    """Pin an independent committed snapshot after retirement and before VACUUM.

    Args:
        reader: The independent connection owned by the test.
        connection: The production maintenance connection.
        retired: Whether production retirement removed obsolete contexts.

    Returns:
        True so the actual SQLite compaction encounters the active reader.
    """
    reader.execute("BEGIN")
    reader.execute("SELECT count(*) FROM products").fetchone()
    return True


def deny_statements(
    action: int,
    first_argument: str | None,
    second_argument: str | None,
    database: str | None,
    source: str | None,
) -> int:
    """Reject a statement while allowing the test to restore the real connection.

    Args:
        action: SQLite's requested operation identifier.
        first_argument: The operation's first object name or argument.
        second_argument: The operation's second object name or argument.
        database: The database containing the affected object.
        source: The triggering view or trigger, if present.

    Returns:
        SQLite's denial code, producing a real database exception.
    """
    return sqlite3.SQLITE_DENY
