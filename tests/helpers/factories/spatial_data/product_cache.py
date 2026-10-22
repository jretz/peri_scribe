"""Construct committed product rows independently of scope-retention decisions."""

import collections.abc
import contextlib
import hashlib
import pathlib
import sqlite3

import spatial_data.product_cache


type Product = tuple[str, str, str, bytes]
type StoredProduct = tuple[str, str, str, bytes, bytes]


def write_products(
    path: pathlib.Path,
    products: collections.abc.Iterable[Product],
) -> None:
    """Seed complete checksummed rows without invoking publication cleanup.

    Args:
        path: The isolated cache database.
        products: Context, namespace, key, and payload tuples.
    """
    with contextlib.closing(spatial_data.product_cache.open_store(path)) as connection:
        connection.executemany(
            "INSERT INTO products (context, namespace, key, checksum, value) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                (context, namespace, key, hashlib.sha256(value).digest(), value)
                for context, namespace, key, value in products
            ),
        )
        connection.commit()


def read_products(path: pathlib.Path) -> tuple[StoredProduct, ...]:
    """Expose exact retained rows through an independent read-only connection.

    Args:
        path: The isolated cache database.

    Returns:
        All five columns in primary-key order.
    """
    with contextlib.closing(
        sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True),
    ) as connection:
        records = connection.execute(
            "SELECT context, namespace, key, checksum, value, encoding "
            "FROM products ORDER BY 1, 2, 3",
        )
        return tuple(
            (
                context,
                namespace,
                key,
                checksum,
                spatial_data.product_cache.decoded_payload(value, encoding),
            )
            for context, namespace, key, checksum, value, encoding in records
        )
