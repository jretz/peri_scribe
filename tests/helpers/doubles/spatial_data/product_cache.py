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
