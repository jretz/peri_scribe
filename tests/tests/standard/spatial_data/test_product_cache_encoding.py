"""Stored compression preserves logical products and safe cache-miss behavior."""

import contextlib
import hashlib
import pathlib
import sqlite3

import pytest

import spatial_data.payload_codec
import spatial_data.product_cache
import tests.helpers.doubles.errors


def test_put_stores_compressed_bytes_with_logical_checksum(
    tmp_path: pathlib.Path,
) -> None:
    payload = b"exact source evidence" * 5000
    with spatial_data.product_cache.scope(tmp_path / "cache.sqlite", "policy"):
        spatial_data.product_cache.put("history", "one", payload)
        store = spatial_data.product_cache.CURRENT.get()
        assert store is not None
        checksum, stored, encoding = store.connection.execute(
            "SELECT checksum, value, encoding FROM products",
        ).fetchone()
        assert encoding == 1
        assert len(stored) < len(payload)
        assert checksum == hashlib.sha256(payload).digest()
        assert spatial_data.payload_codec.decode(stored) == payload


def test_open_store_preserves_explicit_raw_encoding_when_adding_column(
    tmp_path: pathlib.Path,
) -> None:
    path = tmp_path / "cache.sqlite"
    payload = b"PSCV\x02arbitrary raw bytes"
    with contextlib.closing(sqlite3.connect(path)) as connection:
        connection.execute(
            "CREATE TABLE products (context TEXT, namespace TEXT, key TEXT, "
            "checksum BLOB, value BLOB, "
            "PRIMARY KEY (context, namespace, key)) WITHOUT ROWID",
        )
        connection.execute(
            "INSERT INTO products VALUES (?, ?, ?, ?, ?)",
            ("policy", "history", "one", hashlib.sha256(payload).digest(), payload),
        )
        connection.commit()
    with spatial_data.product_cache.scope(path, "policy"):
        assert spatial_data.product_cache.get("history", "one") == payload


@pytest.mark.parametrize("encoding", [-1, 2])
def test_get_ignores_unsupported_storage_formats(
    tmp_path: pathlib.Path,
    encoding: int,
) -> None:
    with spatial_data.product_cache.scope(tmp_path / "cache.sqlite", "policy"):
        spatial_data.product_cache.put("history", "one", b"content")
        store = spatial_data.product_cache.CURRENT.get()
        assert store is not None
        store.connection.execute("UPDATE products SET encoding = ?", (encoding,))
        assert spatial_data.product_cache.get("history", "one") is None


def test_get_rejects_changed_logical_checksum_of_valid_frame(
    tmp_path: pathlib.Path,
) -> None:
    with spatial_data.product_cache.scope(tmp_path / "cache.sqlite", "policy"):
        spatial_data.product_cache.put("history", "one", b"content")
        store = spatial_data.product_cache.CURRENT.get()
        assert store is not None
        store.connection.execute("UPDATE products SET checksum = ?", (b"incorrect",))
        assert spatial_data.product_cache.get("history", "one") is None


def test_put_skips_unsupported_encoding_without_disabling_cache(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with spatial_data.product_cache.scope(tmp_path / "cache.sqlite", "policy"):
        spatial_data.product_cache.put("history", "one", b"preserved")
        monkeypatch.setattr(
            spatial_data.payload_codec,
            "encode",
            tests.helpers.doubles.errors.raising_stub(ValueError("too large")),
        )
        spatial_data.product_cache.put("history", "oversized", b"not stored")
        assert spatial_data.product_cache.active()
        assert spatial_data.product_cache.get("history", "one") == b"preserved"
        assert spatial_data.product_cache.get("history", "oversized") is None
