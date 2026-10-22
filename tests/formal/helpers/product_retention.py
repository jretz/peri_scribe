"""Replay checked context-retirement prefixes against real SQLite transactions."""

import contextlib
import enum
import pathlib
import sqlite3

import pytest

import spatial_data.product_cache
import tests.formal.helpers.product_cache
import tests.helpers.factories.spatial_data.product_cache


class Action(enum.IntEnum):
    """Name the checked maintenance and reader transaction boundaries."""

    DELETE = 1
    COMMIT = 2
    ROLLBACK = 3
    DELETE_FAILURE = 4
    COMPACT = 5
    DEFER_COMPACT = 6
    OPEN_READER = 7
    CLOSE_READER = 8


def seed(path: pathlib.Path) -> None:
    """Make each symbolic row's context and exact binary payload observable.

    Args:
        path: The private cache used for one checked action prefix.
    """
    tests.helpers.factories.spatial_data.product_cache.write_products(
        path,
        (
            (f"context-{1 + (key - 1) // 2}", "history", str(key), payload(key))
            for key in range(1, 7)
        ),
    )


def payload(key: int) -> bytes:
    """Preserve arbitrary binary bytes while mapping one formal product token.

    Args:
        key: A row token from the model's finite domain.

    Returns:
        A distinct checksummed payload for that row.
    """
    return b"product\x00\xff" + bytes([key])


def rows(connection: sqlite3.Connection) -> frozenset[int]:
    """Inspect exact values and their identities without calling cache selection.

    Args:
        connection: A writer, an independent reader, or a recovered connection.

    Returns:
        The formal row tokens visible through that connection.
    """
    values = {}
    for key, value in connection.execute("SELECT key, value FROM products"):
        identifier = int(key)
        assert value == payload(identifier)
        values[identifier] = value
    return frozenset(values)


def apply(
    action: Action,
    writer: sqlite3.Connection,
    reader: sqlite3.Connection,
    retained: frozenset[str],
) -> None:
    """Execute actual production deletion and SQLite visibility boundaries.

    Args:
        action: One action exported by the checked model.
        writer: The maintenance connection, independent of the reader.
        reader: The connection whose explicit transaction pins a committed snapshot.
        retained: All contexts admitted by the owning application scope.
    """
    match action:
        case Action.DELETE:
            spatial_data.product_cache.retire_contexts(writer, retained)
        case Action.COMMIT:
            writer.commit()
        case Action.ROLLBACK:
            writer.rollback()
        case Action.DELETE_FAILURE:
            writer.execute("PRAGMA query_only = ON")
            with pytest.raises(sqlite3.OperationalError):
                spatial_data.product_cache.retire_contexts(writer, frozenset())
            writer.rollback()
        case Action.COMPACT:
            spatial_data.product_cache.compact_store(writer)
        case Action.DEFER_COMPACT:
            pass
        case Action.OPEN_READER:
            reader.execute("BEGIN")
            rows(reader)
        case Action.CLOSE_READER:
            reader.rollback()


def replay(state: dict[str, str], path: pathlib.Path) -> None:
    """Compare pending, durable, and reader observations with one checked prefix.

    Args:
        state: A complete ProductRetention state retaining its action trace.
        path: An independent database for this prefix.
    """
    seed(path)
    retained = frozenset(
        f"context-{context}"
        for context in tests.formal.helpers.product_cache.numbers(state["retained"])
    )
    with (
        contextlib.closing(spatial_data.product_cache.open_store(path)) as writer,
        contextlib.closing(sqlite3.connect(path)) as reader,
        contextlib.closing(sqlite3.connect(path)) as observer,
    ):
        for token in tests.formal.helpers.product_cache.numbers(state["trace"]):
            apply(Action(token), writer, reader, retained)
        assert rows(writer) == frozenset(
            tests.formal.helpers.product_cache.numbers(state["pending"]),
        ), state
        assert rows(observer) == frozenset(
            tests.formal.helpers.product_cache.numbers(state["durable"]),
        ), state
        if state["readerPhase"] == "1":
            assert rows(reader) == frozenset(
                tests.formal.helpers.product_cache.numbers(state["reader"]),
            ), state
