"""Cache reproducible products without keeping their inputs in memory.

[Product cache reasoning](../../docs/algorithms/product-caching.md)
explains the contract and correctness argument.
[Context retention](../../docs/algorithms/product-cache-retention.md) explains
transactional retirement and physical compaction.
"""

from __future__ import annotations

import collections.abc
import contextlib
import contextvars
import dataclasses
import hashlib
import pathlib
import sqlite3

import structlog

import spatial_data.payload_codec


logger = structlog.get_logger()
MINIMUM_COMPACTION_BYTES = 16 * 1024 * 1024


@dataclasses.dataclass(frozen=True, kw_only=True)
class Store:
    """One connection owns a publication and all contexts used by nested scopes."""

    path: pathlib.Path
    context: str
    connection: sqlite3.Connection
    unconditional: bool
    retained_contexts: set[str] = dataclasses.field(default_factory=set)


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
            "encoding INTEGER NOT NULL DEFAULT 0, "
            "PRIMARY KEY (context, namespace, key)) WITHOUT ROWID",
        )
        columns = {row[1] for row in connection.execute("PRAGMA table_info(products)")}
        if "encoding" not in columns:
            connection.execute(
                "ALTER TABLE products ADD COLUMN encoding INTEGER NOT NULL DEFAULT 0",
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
) -> collections.abc.Generator[None]:
    """Commit completed preparations together and discard interrupted transactions.

    A nested consumer of the same database shares its transaction while using its own
    dependency fingerprint. If either scope disables cache reads, the nested scope does
    too. When the cache is unavailable, publication can still compute the products.

    Args:
        path: The disposable product database.
        context: Complete application, policy, and runtime dependency fingerprint.
        unconditional: Whether reads must miss while completed results refresh storage.

    Yields:
        None; the scope that opened the shared connection closes it on exit.
    """
    resolved = path.resolve()
    existing = CURRENT.get()
    if existing is not None and existing.path == resolved:
        existing.retained_contexts.add(context)
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
            disabled = CURRENT.get() is None
            CURRENT.reset(token)
            if disabled:
                CURRENT.set(None)
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
    store = Store(
        path=resolved,
        context=context,
        connection=connection,
        unconditional=unconditional,
        retained_contexts={context},
    )
    token = CURRENT.set(store)
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
        else:
            if CURRENT.get() is not None:
                maintain_store(store)
    finally:
        CURRENT.reset(token)
        connection.close()


def retire_contexts(
    connection: sqlite3.Connection,
    retained_contexts: collections.abc.Set[str],
) -> bool:
    """Delete obsolete contexts within a transaction owned by the caller.

    Args:
        connection: The cache connection after application products have committed.
        retained_contexts: Every dependency context admitted by that owning scope.

    Returns:
        Whether obsolete contexts were present and their removal was requested.
    """
    obsolete = tuple(
        (context,)
        for (context,) in connection.execute("SELECT DISTINCT context FROM products")
        if context not in retained_contexts
    )
    connection.executemany("DELETE FROM products WHERE context = ?", obsolete)
    return bool(obsolete)


def needs_compaction(connection: sqlite3.Connection, *, retired: bool) -> bool:
    """Reclaim retired generations and retry substantial deferred compaction.

    Args:
        connection: A cache connection with no uncommitted transaction.
        retired: Whether this maintenance pass removed obsolete contexts.

    Returns:
        Whether free pages justify rebuilding SQLite's physical page layout.
    """
    (free_pages,) = connection.execute("PRAGMA freelist_count").fetchone()
    if not free_pages:
        return False
    if retired:
        return True
    (page_size,) = connection.execute("PRAGMA page_size").fetchone()
    (pages,) = connection.execute("PRAGMA page_count").fetchone()
    return (
        free_pages * page_size >= MINIMUM_COMPACTION_BYTES and free_pages * 4 >= pages
    )


def maintain_store(store: Store) -> None:
    """Retire unused contexts after successful publication without risking its products.

    SQLite readers retain their committed snapshot. A busy reader, interrupted cleanup,
    or storage failure can defer physical reclamation; none permits partial retirement
    or changes a retained product's bytes. The products table has no implicit rowids.

    Args:
        store: The outer scope whose application transaction has already committed.
    """
    try:
        with store.connection:
            retired = retire_contexts(
                store.connection,
                store.retained_contexts | {store.context},
            )
    except sqlite3.Error:
        logger.warning("Product context retirement deferred", exc_info=True)
        return
    try:
        if needs_compaction(store.connection, retired=retired):
            compact_store(store.connection)
    except sqlite3.Error:
        logger.warning("Product cache compaction deferred", exc_info=True)


def compact_store(connection: sqlite3.Connection) -> None:
    """Rebuild physical pages while SQLite preserves complete logical products.

    Args:
        connection: A committed connection to the WITHOUT ROWID product table.
    """
    connection.execute("VACUUM")


def get(namespace: str, key: str) -> bytes | None:
    """Read and check one cached result without loading unrelated products.

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
            "SELECT checksum, value, encoding FROM products "
            "WHERE context = ? AND namespace = ? AND key = ?",
            (store.context, namespace, key),
        ).fetchone()
    except sqlite3.Error:
        logger.warning("Product cache read failed", exc_info=True)
        CURRENT.set(None)
        return None
    if row is None:
        return None
    checksum, value, encoding = row
    if not isinstance(value, bytes):
        return None
    try:
        value = decoded_payload(value, encoding)
    except ValueError:
        return None
    return value if hashlib.sha256(value).digest() == checksum else None


def decoded_payload(value: bytes, encoding: int) -> bytes:
    """Decode the explicit storage format independently of the logical checksum.

    Args:
        value: Stored payload bytes.
        encoding: The row's format marker; raw bytes are zero, framed bytes are one.

    Returns:
        The exact logical payload awaiting checksum validation.

    Raises:
        ValueError: If the storage format is unsupported.
    """
    if encoding == 0:
        return value
    if encoding == 1:
        return spatial_data.payload_codec.decode(value)
    message = "Unsupported product storage encoding"
    raise ValueError(message)


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
        encoded = spatial_data.payload_codec.encode(value)
    except ValueError:
        return
    try:
        store.connection.execute(
            "INSERT INTO products (context, namespace, key, checksum, value, encoding) "
            "VALUES (?, ?, ?, ?, ?, 1) "
            "ON CONFLICT (context, namespace, key) DO UPDATE SET "
            "checksum = excluded.checksum, value = excluded.value, encoding = 1 "
            "WHERE products.checksum IS NOT excluded.checksum "
            "OR products.value IS NOT excluded.value OR products.encoding != 1",
            (store.context, namespace, key, hashlib.sha256(value).digest(), encoded),
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
