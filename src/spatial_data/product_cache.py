"""Retain disposable deterministic products without retaining their inputs in RAM."""

from __future__ import annotations

import collections.abc
import contextlib
import contextvars
import dataclasses
import hashlib
import pathlib
import sqlite3

import structlog


logger = structlog.get_logger()


@dataclasses.dataclass(frozen=True, kw_only=True)
class Store:
    """One transaction owns a bounded SQLite page cache for a publication."""

    path: pathlib.Path
    context: str
    connection: sqlite3.Connection
    unconditional: bool


CURRENT: contextvars.ContextVar[Store | None] = contextvars.ContextVar(
    "prepared_product_store",
    default=None,
)


def active() -> bool:
    """Avoid fingerprinting evidence when no persistent cache can consume it.

    Returns:
        Whether a publication currently owns a usable store.
    """
    return CURRENT.get() is not None


def open_store(path: pathlib.Path) -> sqlite3.Connection:
    """Create only disposable state, with SQLite responsible for atomic transactions.

    Args:
        path: The private product database, separate from published artifacts.

    Returns:
        An open connection whose owner must close it.

    Raises:
        sqlite3.Error: If the store cannot be opened or initialized.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=0.1)
    try:
        connection.execute("PRAGMA cache_size = -8192")
        connection.execute(
            "CREATE TABLE IF NOT EXISTS products ("
            "context TEXT NOT NULL, namespace TEXT NOT NULL, key TEXT NOT NULL, "
            "checksum BLOB NOT NULL, value BLOB NOT NULL, "
            "PRIMARY KEY (context, namespace, key)) WITHOUT ROWID",
        )
    except sqlite3.Error:
        connection.close()
        raise
    else:
        return connection


@contextlib.contextmanager
def scope(
    path: pathlib.Path,
    context: str,
    *,
    unconditional: bool = False,
) -> collections.abc.Iterator[None]:
    """Commit complete preparations together and discard interrupted transactions.

    Nested consumers borrow the active store only when all cache semantics agree.
    Unavailable caches disable reuse while allowing the publication to proceed.

    Args:
        path: The disposable product database.
        context: Complete application, policy, and runtime dependency fingerprint.
        unconditional: Whether reads must miss while completed results refresh storage.

    Yields:
        Control to the publication, with no persistent connection surviving this scope.
    """
    resolved = path.resolve()
    existing = CURRENT.get()
    if existing is not None and existing.path == resolved:
        token = CURRENT.set(
            dataclasses.replace(
                existing,
                context=context,
                unconditional=existing.unconditional or unconditional,
            ),
        )
        try:
            yield
        finally:
            CURRENT.reset(token)
        return
    try:
        connection = open_store(resolved)
    except OSError, sqlite3.Error:
        logger.warning("Product cache unavailable", path=str(resolved), exc_info=True)
        token = CURRENT.set(None)
        try:
            yield
        finally:
            CURRENT.reset(token)
        return
    token = CURRENT.set(
        Store(
            path=resolved,
            context=context,
            connection=connection,
            unconditional=unconditional,
        ),
    )
    try:
        yield
        try:
            connection.commit()
        except sqlite3.Error:
            logger.warning(
                "Product cache commit failed",
                path=str(resolved),
                exc_info=True,
            )
    finally:
        CURRENT.reset(token)
        connection.close()


def get(namespace: str, key: str) -> bytes | None:
    """Authenticate one result without materializing unrelated fire products.

    Args:
        namespace: The caller's product type and serialization schema version.
        key: The complete ordered input fingerprint within that namespace.

    Returns:
        The validated payload, or None when unavailable, bypassed, absent, or corrupt.
    """
    store = CURRENT.get()
    if store is None or store.unconditional:
        return None
    try:
        row = store.connection.execute(
            "SELECT checksum, value FROM products "
            "WHERE context = ? AND namespace = ? AND key = ?",
            (store.context, namespace, key),
        ).fetchone()
    except sqlite3.Error:
        logger.warning("Product cache read failed", exc_info=True)
        CURRENT.set(None)
        return None
    if row is None:
        return None
    checksum, value = row
    if not isinstance(value, bytes) or hashlib.sha256(value).digest() != checksum:
        return None
    return value


def put(namespace: str, key: str, value: bytes) -> None:
    """Store only completed deterministic results in the owning transaction.

    Args:
        namespace: The caller's product type and serialization schema version.
        key: The complete ordered input fingerprint within that namespace.
        value: Explicitly serialized data, never an executable object format.
    """
    store = CURRENT.get()
    if store is None:
        return
    try:
        store.connection.execute(
            "INSERT INTO products VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT (context, namespace, key) DO UPDATE SET "
            "checksum = excluded.checksum, value = excluded.value "
            "WHERE products.checksum IS NOT excluded.checksum "
            "OR products.value IS NOT excluded.value",
            (store.context, namespace, key, hashlib.sha256(value).digest(), value),
        )
    except sqlite3.Error:
        logger.warning("Product cache write failed", exc_info=True)
        CURRENT.set(None)


def prune(namespace: str, keep_keys: collections.abc.Collection[str]) -> None:
    """Discard superseded products only within the current publication transaction.

    A temporary key table avoids SQLite's bound-parameter limit as a season grows.

    Args:
        namespace: The product family whose completed replacement is now available.
        keep_keys: Keys referenced by that replacement, possibly empty.
    """
    store = CURRENT.get()
    if store is None:
        return
    try:
        store.connection.execute(
            "CREATE TEMP TABLE retained_product_keys "
            "(key TEXT PRIMARY KEY) WITHOUT ROWID",
        )
        store.connection.executemany(
            "INSERT OR IGNORE INTO retained_product_keys VALUES (?)",
            ((key,) for key in keep_keys),
        )
        store.connection.execute(
            "DELETE FROM products WHERE context = ? AND namespace = ? "
            "AND key NOT IN (SELECT key FROM retained_product_keys)",
            (store.context, namespace),
        )
        store.connection.execute("DROP TABLE retained_product_keys")
    except sqlite3.Error:
        logger.warning("Product cache pruning failed", exc_info=True)
        CURRENT.set(None)
