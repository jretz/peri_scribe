"""Retirement and physical compaction preserve committed products and live readers."""

import contextlib
import functools
import pathlib
import sqlite3

import pytest

import spatial_data.product_cache
import tests.helpers.doubles.spatial_data.product_cache
import tests.helpers.factories.spatial_data.product_cache


def test_scope_retires_only_contexts_unused_by_the_complete_scope(
    tmp_path: pathlib.Path,
) -> None:
    path = tmp_path / "products.sqlite"
    tests.helpers.factories.spatial_data.product_cache.write_products(
        path,
        (
            (context, namespace, "key", context.encode() + b"\x00\xff")
            for context in ("current", "nested", "obsolete")
            for namespace in ("history", "chart")
        ),
    )
    before = tests.helpers.factories.spatial_data.product_cache.read_products(path)

    with (
        spatial_data.product_cache.scope(path, "current"),
        spatial_data.product_cache.scope(path, "nested"),
    ):
        assert spatial_data.product_cache.get("history", "key") == b"nested\x00\xff"

    assert tests.helpers.factories.spatial_data.product_cache.read_products(
        path,
    ) == tuple(row for row in before if row[0] != "obsolete")


def test_scope_recomputes_a_retired_context_without_reusing_other_context_values(
    tmp_path: pathlib.Path,
) -> None:
    path = tmp_path / "products.sqlite"
    with spatial_data.product_cache.scope(path, "previous"):
        spatial_data.product_cache.put("history", "key", b"previous")
    with spatial_data.product_cache.scope(path, "current"):
        spatial_data.product_cache.put("history", "key", b"current")

    with spatial_data.product_cache.scope(path, "previous"):
        assert spatial_data.product_cache.get("history", "key") is None
        spatial_data.product_cache.put("history", "key", b"recomputed previous")

    with spatial_data.product_cache.scope(path, "previous"):
        assert (
            spatial_data.product_cache.get("history", "key") == b"recomputed previous"
        )


def test_scope_compacts_obsolete_payloads_without_changing_retained_rows(
    tmp_path: pathlib.Path,
) -> None:
    path = tmp_path / "products.sqlite"
    tests.helpers.factories.spatial_data.product_cache.write_products(
        path,
        (
            ("current", "history", "key", b"retained\x00\xff"),
            ("obsolete", "geometry", "key", bytes(range(256)) * 4096),
        ),
    )
    before = path.stat().st_size
    retained = tests.helpers.factories.spatial_data.product_cache.read_products(path)[0]

    with spatial_data.product_cache.scope(path, "current"):
        assert spatial_data.product_cache.get("history", "key") == retained[4]

    assert path.stat().st_size < before / 10
    assert tests.helpers.factories.spatial_data.product_cache.read_products(path) == (
        retained,
    )


def test_scope_does_not_retire_contexts_after_application_failure(
    tmp_path: pathlib.Path,
) -> None:
    path = tmp_path / "products.sqlite"
    tests.helpers.factories.spatial_data.product_cache.write_products(
        path,
        (("obsolete", "history", "key", b"previous"),),
    )
    before = tests.helpers.factories.spatial_data.product_cache.read_products(path)
    with pytest.raises(RuntimeError, match="publication failed"):
        tests.helpers.doubles.spatial_data.product_cache.interrupt_changed_context(path)

    assert (
        tests.helpers.factories.spatial_data.product_cache.read_products(path) == before
    )


def test_maintain_store_rolls_back_partial_retirement_after_a_statement_failure(
    tmp_path: pathlib.Path,
) -> None:
    path = tmp_path / "products.sqlite"
    tests.helpers.factories.spatial_data.product_cache.write_products(
        path,
        ((context, "history", "key", b"previous") for context in ("first", "last")),
    )
    with contextlib.closing(sqlite3.connect(path)) as connection:
        connection.execute(
            "CREATE TRIGGER prevent_last_retirement BEFORE DELETE ON products "
            "WHEN OLD.context = 'last' BEGIN "
            "SELECT RAISE(FAIL, 'retirement interrupted'); END",
        )

    with spatial_data.product_cache.scope(path, "current"):
        spatial_data.product_cache.put("history", "key", b"committed")

    rows = tests.helpers.factories.spatial_data.product_cache.read_products(path)
    assert tuple((row[0], row[4]) for row in rows) == (
        ("current", b"committed"),
        ("first", b"previous"),
        ("last", b"previous"),
    )


def test_maintain_store_defers_retirement_while_a_reader_owns_its_snapshot(
    tmp_path: pathlib.Path,
) -> None:
    path = tmp_path / "products.sqlite"
    tests.helpers.factories.spatial_data.product_cache.write_products(
        path,
        ((context, "history", "key", context.encode()) for context in ("new", "old")),
    )
    before = tests.helpers.factories.spatial_data.product_cache.read_products(path)
    with contextlib.closing(sqlite3.connect(path)) as reader:
        reader.execute("BEGIN")
        assert (
            tuple(
                reader.execute(
                    "SELECT context, namespace, key, checksum, value "
                    "FROM products ORDER BY 1, 2, 3",
                ),
            )
            == before
        )

        with spatial_data.product_cache.scope(path, "new"):
            assert spatial_data.product_cache.get("history", "key") == b"new"

        assert (
            tuple(
                reader.execute(
                    "SELECT context, namespace, key, checksum, value "
                    "FROM products ORDER BY 1, 2, 3",
                ),
            )
            == before
        )
    assert (
        tests.helpers.factories.spatial_data.product_cache.read_products(path) == before
    )

    with spatial_data.product_cache.scope(path, "new"):
        assert spatial_data.product_cache.get("history", "key") == b"new"

    assert (
        len(tests.helpers.factories.spatial_data.product_cache.read_products(path)) == 1
    )


def test_scope_nested_database_retention_is_independent(tmp_path: pathlib.Path) -> None:
    first = tmp_path / "first.sqlite"
    second = tmp_path / "second.sqlite"
    for path in (first, second):
        tests.helpers.factories.spatial_data.product_cache.write_products(
            path,
            (("obsolete", "history", "key", b"previous"),),
        )

    with spatial_data.product_cache.scope(first, "outer"):
        spatial_data.product_cache.put("history", "key", b"outer")
        with spatial_data.product_cache.scope(second, "inner"):
            spatial_data.product_cache.put("history", "key", b"inner")

    assert tuple(
        row[0]
        for row in tests.helpers.factories.spatial_data.product_cache.read_products(
            first,
        )
    ) == ("outer",)
    assert tuple(
        row[0]
        for row in tests.helpers.factories.spatial_data.product_cache.read_products(
            second,
        )
    ) == ("inner",)


def test_retire_contexts_treats_contexts_as_literal_data(
    tmp_path: pathlib.Path,
) -> None:
    path = tmp_path / "products.sqlite"
    retained = "'); DROP TABLE products; --"
    tests.helpers.factories.spatial_data.product_cache.write_products(
        path,
        ((context, "history", "key", b"value") for context in (retained, "obsolete")),
    )

    with spatial_data.product_cache.scope(path, retained):
        assert spatial_data.product_cache.get("history", "key") == b"value"

    assert tuple(
        row[0]
        for row in tests.helpers.factories.spatial_data.product_cache.read_products(
            path,
        )
    ) == (retained,)


def test_scope_skips_retirement_after_cache_operations_become_unavailable(
    tmp_path: pathlib.Path,
) -> None:
    path = tmp_path / "products.sqlite"
    tests.helpers.factories.spatial_data.product_cache.write_products(
        path,
        (("previous", "history", "key", b"retained"),),
    )
    before = tests.helpers.factories.spatial_data.product_cache.read_products(path)

    with spatial_data.product_cache.scope(path, "current"):
        store = spatial_data.product_cache.CURRENT.get()
        assert store is not None
        store.connection.execute("PRAGMA query_only = ON")
        spatial_data.product_cache.put("history", "key", b"rejected")

    assert (
        tests.helpers.factories.spatial_data.product_cache.read_products(path) == before
    )


@pytest.mark.parametrize("operation", ["get", "put", "prune"])
def test_scope_keeps_nested_cache_failure_disabled_after_the_database_recovers(
    tmp_path: pathlib.Path,
    operation: str,
) -> None:
    path = tmp_path / "products.sqlite"
    tests.helpers.factories.spatial_data.product_cache.write_products(
        path,
        (("previous", "history", "key", b"retained"),),
    )
    before = tests.helpers.factories.spatial_data.product_cache.read_products(path)

    with spatial_data.product_cache.scope(path, "current"):
        spatial_data.product_cache.put("history", "key", b"completed")
        with spatial_data.product_cache.scope(path, "nested"):
            store = spatial_data.product_cache.CURRENT.get()
            assert store is not None
            store.connection.set_authorizer(
                tests.helpers.doubles.spatial_data.product_cache.deny_statements,
            )
            match operation:
                case "get":
                    assert spatial_data.product_cache.get("history", "key") is None
                case "put":
                    spatial_data.product_cache.put("history", "key", b"rejected")
                case "prune":
                    spatial_data.product_cache.prune("history", [])
            assert not spatial_data.product_cache.active()
            store.connection.set_authorizer(None)

        assert not spatial_data.product_cache.active()
        assert spatial_data.product_cache.get("history", "key") is None

    rows = tests.helpers.factories.spatial_data.product_cache.read_products(path)
    assert tuple(row for row in rows if row[0] == "previous") == before
    assert tuple((row[0], row[4]) for row in rows) == (
        ("current", b"completed"),
        ("previous", b"retained"),
    )


def test_needs_compaction_leaves_small_unused_page_slack(
    tmp_path: pathlib.Path,
) -> None:
    path = tmp_path / "products.sqlite"
    tests.helpers.factories.spatial_data.product_cache.write_products(
        path,
        (
            ("current", "history", "key", b"retained"),
            ("obsolete", "history", "key", b"x" * 65536),
        ),
    )
    with contextlib.closing(sqlite3.connect(path)) as connection:
        spatial_data.product_cache.retire_contexts(connection, frozenset({"current"}))
        connection.commit()

        assert not spatial_data.product_cache.needs_compaction(
            connection,
            retired=False,
        )


def test_maintain_store_retries_busy_compaction_after_the_reader_closes(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "products.sqlite"
    tests.helpers.factories.spatial_data.product_cache.write_products(
        path,
        (
            ("current", "history", "key", b"retained"),
            (
                "obsolete",
                "history",
                "key",
                b"x" * (2 * spatial_data.product_cache.MINIMUM_COMPACTION_BYTES),
            ),
        ),
    )
    before = path.stat().st_size
    with (
        contextlib.closing(sqlite3.connect(path)) as reader,
        monkeypatch.context() as patch,
    ):
        patch.setattr(
            spatial_data.product_cache,
            "needs_compaction",
            functools.partial(
                tests.helpers.doubles.spatial_data.product_cache.hold_compaction_reader,
                reader,
            ),
        )
        with spatial_data.product_cache.scope(path, "current"):
            assert spatial_data.product_cache.get("history", "key") == b"retained"

        assert tuple(reader.execute("SELECT context, value FROM products")) == (
            ("current", b"retained"),
        )
        assert path.stat().st_size == before

    with spatial_data.product_cache.scope(path, "current"):
        assert spatial_data.product_cache.get("history", "key") == b"retained"

    assert path.stat().st_size < before / 10
