"""Persistent preparation stays optional, isolated, and transactionally complete."""

import contextlib
import pathlib
import sqlite3

import pytest

import spatial_data.product_cache
import tests.helpers.doubles.errors
import tests.helpers.doubles.spatial_data.product_cache


def test_active_is_false_outside_scope() -> None:
    assert not spatial_data.product_cache.active()


def test_get_misses_outside_scope() -> None:
    assert spatial_data.product_cache.get("history", "fire") is None


def test_put_has_no_effect_outside_scope(tmp_path: pathlib.Path) -> None:
    spatial_data.product_cache.put("history", "fire", b"unowned")

    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "policy"):
        assert spatial_data.product_cache.get("history", "fire") is None


def test_scope_restores_inactive_state_after_success(tmp_path: pathlib.Path) -> None:
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "policy"):
        assert spatial_data.product_cache.active()

    assert not spatial_data.product_cache.active()


def test_scope_restores_inactive_state_after_failure(tmp_path: pathlib.Path) -> None:
    fail = tests.helpers.doubles.errors.raising_stub(
        RuntimeError("publication interrupted"),
    )
    with (
        pytest.raises(RuntimeError, match="publication interrupted"),
        spatial_data.product_cache.scope(tmp_path / "products.sqlite", "policy"),
    ):
        fail()

    assert not spatial_data.product_cache.active()


@pytest.mark.parametrize("value", [b"", b"fire\x00\xff", bytes(range(256))])
def test_put_preserves_binary_products_across_scopes(
    tmp_path: pathlib.Path,
    value: bytes,
) -> None:
    path = tmp_path / "nested" / "products.sqlite"
    with spatial_data.product_cache.scope(path, "policy"):
        spatial_data.product_cache.put("history", "fire", value)

    with spatial_data.product_cache.scope(path, "policy"):
        assert spatial_data.product_cache.get("history", "fire") == value


def test_put_replaces_only_the_selected_key(tmp_path: pathlib.Path) -> None:
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "policy"):
        spatial_data.product_cache.put("history", "first", b"original")
        spatial_data.product_cache.put("history", "second", b"preserved")
        spatial_data.product_cache.put("history", "first", b"corrected")

        assert (
            spatial_data.product_cache.get("history", "first"),
            spatial_data.product_cache.get("history", "second"),
        ) == (b"corrected", b"preserved")


def test_put_does_not_write_an_unchanged_product(tmp_path: pathlib.Path) -> None:
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "policy"):
        spatial_data.product_cache.put("history", "fire", b"unchanged")
        store = spatial_data.product_cache.CURRENT.get()
        assert store is not None
        before = store.connection.total_changes

        spatial_data.product_cache.put("history", "fire", b"unchanged")

        assert store.connection.total_changes == before


@pytest.mark.parametrize("column", ["checksum", "value"])
def test_put_repairs_corruption_even_when_other_stored_field_is_unchanged(
    tmp_path: pathlib.Path,
    column: str,
) -> None:
    path = tmp_path / "products.sqlite"
    with spatial_data.product_cache.scope(path, "policy"):
        spatial_data.product_cache.put("history", "fire", b"authenticated")
    with contextlib.closing(sqlite3.connect(path)) as connection:
        if column == "checksum":
            connection.execute("UPDATE products SET checksum = ?", (b"corrupted",))
        else:
            connection.execute("UPDATE products SET value = ?", (b"corrupted",))
        connection.commit()

    with spatial_data.product_cache.scope(path, "policy"):
        spatial_data.product_cache.put("history", "fire", b"authenticated")

        assert spatial_data.product_cache.get("history", "fire") == b"authenticated"


@pytest.mark.parametrize("keep_keys", [[], ["keep"], ["keep", "keep", "obsolete"]])
def test_prune_removes_only_unretained_keys_in_current_namespace_and_context(
    tmp_path: pathlib.Path,
    keep_keys: list[str],
) -> None:
    path = tmp_path / "products.sqlite"
    with spatial_data.product_cache.scope(path, "other policy"):
        spatial_data.product_cache.put("history", "obsolete", b"other context")
    with spatial_data.product_cache.scope(path, "policy"):
        spatial_data.product_cache.put("history", "keep", b"retained")
        spatial_data.product_cache.put("history", "obsolete", b"superseded")
        spatial_data.product_cache.put("chart", "obsolete", b"other namespace")

        spatial_data.product_cache.prune("history", keep_keys)

        assert (
            spatial_data.product_cache.get("history", "keep"),
            spatial_data.product_cache.get("history", "obsolete"),
            spatial_data.product_cache.get("chart", "obsolete"),
        ) == (
            b"retained" if "keep" in keep_keys else None,
            b"superseded" if "obsolete" in keep_keys else None,
            b"other namespace",
        )
    with spatial_data.product_cache.scope(path, "other policy"):
        assert spatial_data.product_cache.get("history", "obsolete") == b"other context"


def test_prune_can_replace_multiple_product_families_in_one_scope(
    tmp_path: pathlib.Path,
) -> None:
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "policy"):
        spatial_data.product_cache.put("history", "obsolete", b"old history")
        spatial_data.product_cache.put("chart", "obsolete", b"old chart")

        spatial_data.product_cache.prune("history", [])
        spatial_data.product_cache.prune("chart", [])

        assert spatial_data.product_cache.get("history", "obsolete") is None
        assert spatial_data.product_cache.get("chart", "obsolete") is None


def test_prune_treats_keys_as_literal_data(tmp_path: pathlib.Path) -> None:
    key = "fire'); DROP TABLE products; --"
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "policy"):
        spatial_data.product_cache.put("history", key, b"retained")
        spatial_data.product_cache.put("history", "ordinary", b"superseded")

        spatial_data.product_cache.prune("history", [key])

        assert spatial_data.product_cache.get("history", key) == b"retained"
        assert spatial_data.product_cache.get("history", "ordinary") is None


def test_prune_rolls_back_when_publication_fails(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "products.sqlite"
    with spatial_data.product_cache.scope(path, "policy"):
        spatial_data.product_cache.put("history", "previous", b"previous publication")

    with pytest.raises(RuntimeError, match="interrupted"):
        tests.helpers.doubles.spatial_data.product_cache.interrupt_pruned_publication(
            path,
        )

    with spatial_data.product_cache.scope(path, "policy"):
        assert spatial_data.product_cache.get("history", "previous") == (
            b"previous publication"
        )
        assert spatial_data.product_cache.get("history", "replacement") is None


def test_prune_does_nothing_without_an_active_store(tmp_path: pathlib.Path) -> None:
    spatial_data.product_cache.prune("history", ["retained"])

    assert not spatial_data.product_cache.active()


def test_prune_database_failure_disables_remaining_reuse(
    tmp_path: pathlib.Path,
) -> None:
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "policy"):
        store = spatial_data.product_cache.CURRENT.get()
        assert store is not None
        store.connection.close()

        spatial_data.product_cache.prune("history", ["retained"])

        assert not spatial_data.product_cache.active()


def test_get_separates_namespaces_with_the_same_key(tmp_path: pathlib.Path) -> None:
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "policy"):
        spatial_data.product_cache.put("history", "fire", b"observations")
        spatial_data.product_cache.put("classification", "fire", b"inside")

        assert (
            spatial_data.product_cache.get("history", "fire"),
            spatial_data.product_cache.get("classification", "fire"),
            spatial_data.product_cache.get("chart", "fire"),
        ) == (b"observations", b"inside", None)


def test_get_treats_namespace_and_key_as_literal_data(tmp_path: pathlib.Path) -> None:
    namespace = "chart'; DROP TABLE products; --"
    key = "fire' OR 1 = 1"
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "policy"):
        spatial_data.product_cache.put(namespace, key, b"literal")
        spatial_data.product_cache.put("history", "fire", b"ordinary")

        assert (
            spatial_data.product_cache.get(namespace, key),
            spatial_data.product_cache.get("history", "fire"),
        ) == (b"literal", b"ordinary")


def test_scope_isolates_changed_dependency_contexts(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "products.sqlite"
    with spatial_data.product_cache.scope(path, "original policy"):
        spatial_data.product_cache.put("history", "fire", b"old product")

    with spatial_data.product_cache.scope(path, "changed policy"):
        assert spatial_data.product_cache.get("history", "fire") is None


def test_scope_rolls_back_all_products_after_failure(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "products.sqlite"
    with spatial_data.product_cache.scope(path, "policy"):
        spatial_data.product_cache.put("history", "existing", b"published")

    with pytest.raises(RuntimeError, match="publication interrupted"):
        (
            tests.helpers.doubles.spatial_data.product_cache
        ).interrupt_product_replacement(path)

    with spatial_data.product_cache.scope(path, "policy"):
        assert (
            spatial_data.product_cache.get("history", "existing"),
            spatial_data.product_cache.get("history", "new"),
        ) == (b"published", None)


def test_scope_nested_same_database_joins_the_outer_transaction(
    tmp_path: pathlib.Path,
) -> None:
    path = tmp_path / "products.sqlite"
    with pytest.raises(RuntimeError, match="outer publication interrupted"):
        (tests.helpers.doubles.spatial_data.product_cache).interrupt_nested_publication(
            path,
        )

    with spatial_data.product_cache.scope(path, "policy"):
        assert (
            spatial_data.product_cache.get("history", "outer"),
            spatial_data.product_cache.get("history", "inner"),
        ) == (None, None)


def test_get_nested_consumer_sees_uncommitted_products(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "products.sqlite"
    with spatial_data.product_cache.scope(path, "policy"):
        spatial_data.product_cache.put("history", "fire", b"pending")
        with spatial_data.product_cache.scope(path, "policy"):
            assert spatial_data.product_cache.get("history", "fire") == b"pending"


def test_scope_nested_context_restores_the_outer_context(
    tmp_path: pathlib.Path,
) -> None:
    path = tmp_path / "products.sqlite"
    with spatial_data.product_cache.scope(path, "outer policy"):
        spatial_data.product_cache.put("history", "fire", b"outer")
        with spatial_data.product_cache.scope(path, "inner policy"):
            assert spatial_data.product_cache.get("history", "fire") is None
            spatial_data.product_cache.put("history", "fire", b"inner")
        assert spatial_data.product_cache.get("history", "fire") == b"outer"

    with spatial_data.product_cache.scope(path, "inner policy"):
        assert spatial_data.product_cache.get("history", "fire") == b"inner"


def test_scope_nested_database_restores_the_outer_store(tmp_path: pathlib.Path) -> None:
    outer = tmp_path / "outer.sqlite"
    inner = tmp_path / "inner.sqlite"
    with spatial_data.product_cache.scope(outer, "policy"):
        spatial_data.product_cache.put("history", "fire", b"outer")
        with spatial_data.product_cache.scope(inner, "policy"):
            assert spatial_data.product_cache.get("history", "fire") is None
            spatial_data.product_cache.put("history", "fire", b"inner")
        assert spatial_data.product_cache.get("history", "fire") == b"outer"

    with spatial_data.product_cache.scope(inner, "policy"):
        assert spatial_data.product_cache.get("history", "fire") == b"inner"


def test_scope_failed_nested_database_restores_the_outer_store(
    tmp_path: pathlib.Path,
) -> None:
    path = tmp_path / "unusable.sqlite"
    path.write_bytes(b"not a database")
    with spatial_data.product_cache.scope(tmp_path / "outer.sqlite", "policy"):
        spatial_data.product_cache.put("history", "fire", b"outer")
        with spatial_data.product_cache.scope(path, "policy"):
            assert not spatial_data.product_cache.active()
            spatial_data.product_cache.put("history", "fire", b"discarded")
        assert spatial_data.product_cache.get("history", "fire") == b"outer"


def test_scope_unconditional_refreshes_products_without_reading_them(
    tmp_path: pathlib.Path,
) -> None:
    path = tmp_path / "products.sqlite"
    with spatial_data.product_cache.scope(path, "policy"):
        spatial_data.product_cache.put("history", "fire", b"old")

    with spatial_data.product_cache.scope(path, "policy", unconditional=True):
        assert spatial_data.product_cache.get("history", "fire") is None
        spatial_data.product_cache.put("history", "fire", b"recomputed")
        assert spatial_data.product_cache.get("history", "fire") is None

    with spatial_data.product_cache.scope(path, "policy"):
        assert spatial_data.product_cache.get("history", "fire") == b"recomputed"


def test_scope_nested_consumer_inherits_unconditional_recomputation(
    tmp_path: pathlib.Path,
) -> None:
    path = tmp_path / "products.sqlite"
    with spatial_data.product_cache.scope(path, "policy", unconditional=True):
        spatial_data.product_cache.put("history", "fire", b"new")
        with spatial_data.product_cache.scope(path, "policy"):
            assert spatial_data.product_cache.get("history", "fire") is None


def test_scope_nested_unconditional_consumer_restores_outer_read_policy(
    tmp_path: pathlib.Path,
) -> None:
    path = tmp_path / "products.sqlite"
    with spatial_data.product_cache.scope(path, "policy"):
        spatial_data.product_cache.put("history", "fire", b"outer")
        with spatial_data.product_cache.scope(path, "policy", unconditional=True):
            assert spatial_data.product_cache.get("history", "fire") is None
        assert spatial_data.product_cache.get("history", "fire") == b"outer"


@pytest.mark.parametrize("damaged_value", [b"changed bytes", "wrong SQLite type"])
def test_get_rejects_corrupt_products(
    tmp_path: pathlib.Path,
    damaged_value: bytes | str,
) -> None:
    path = tmp_path / "products.sqlite"
    with spatial_data.product_cache.scope(path, "policy"):
        spatial_data.product_cache.put("history", "fire", b"authenticated")
    with contextlib.closing(sqlite3.connect(path)) as connection:
        connection.execute("UPDATE products SET value = ?", (damaged_value,))
        connection.commit()

    with spatial_data.product_cache.scope(path, "policy"):
        assert spatial_data.product_cache.get("history", "fire") is None


def test_put_repairs_a_corrupt_product(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "products.sqlite"
    with spatial_data.product_cache.scope(path, "policy"):
        spatial_data.product_cache.put("history", "fire", b"authenticated")
    with contextlib.closing(sqlite3.connect(path)) as connection:
        connection.execute("UPDATE products SET checksum = ?", (b"corrupted",))
        connection.commit()

    with spatial_data.product_cache.scope(path, "policy"):
        spatial_data.product_cache.put("history", "fire", b"recomputed")
        assert spatial_data.product_cache.get("history", "fire") == b"recomputed"


@pytest.mark.parametrize("failure", [OSError("denied"), sqlite3.Error("unavailable")])
def test_scope_database_open_failure_keeps_publication_running(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
) -> None:
    monkeypatch.setattr(
        spatial_data.product_cache.sqlite3,
        "connect",
        tests.helpers.doubles.errors.raising_stub(failure),
    )

    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "policy"):
        assert not spatial_data.product_cache.active()
        assert spatial_data.product_cache.get("history", "fire") is None
        spatial_data.product_cache.put("history", "fire", b"uncached")


def test_scope_corrupt_database_keeps_publication_running(
    tmp_path: pathlib.Path,
) -> None:
    path = tmp_path / "products.sqlite"
    path.write_bytes(b"interrupted database bytes")

    with spatial_data.product_cache.scope(path, "policy"):
        assert not spatial_data.product_cache.active()


@pytest.mark.parametrize("operation", ["get", "put"])
def test_scope_database_operation_failure_disables_remaining_reuse(
    tmp_path: pathlib.Path,
    operation: str,
) -> None:
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "policy"):
        store = spatial_data.product_cache.CURRENT.get()
        assert store is not None
        store.connection.close()
        if operation == "get":
            assert spatial_data.product_cache.get("history", "fire") is None
        else:
            spatial_data.product_cache.put("history", "fire", b"unavailable")
        assert not spatial_data.product_cache.active()


def test_scope_failed_commit_preserves_previous_products(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "products.sqlite"
    with spatial_data.product_cache.scope(path, "policy"):
        spatial_data.product_cache.put("history", "fire", b"published")

    with monkeypatch.context() as replacement:
        replacement.setattr(
            spatial_data.product_cache.sqlite3,
            "connect",
            (
                tests.helpers.doubles.spatial_data.product_cache
            ).connect_with_commit_failure,
        )
        with spatial_data.product_cache.scope(path, "policy"):
            spatial_data.product_cache.put("history", "fire", b"uncommitted")

    with spatial_data.product_cache.scope(path, "policy"):
        assert spatial_data.product_cache.get("history", "fire") == b"published"


def test_open_store_bounds_sqlite_page_cache_memory(tmp_path: pathlib.Path) -> None:
    maximum_cache_kibibytes = 8 * 1024
    connection = spatial_data.product_cache.open_store(tmp_path / "products.sqlite")
    try:
        (cache_size,) = connection.execute("PRAGMA cache_size").fetchone()
        assert -maximum_cache_kibibytes <= cache_size < 0
    finally:
        connection.close()
