"""Connect checked cache generations to real SQLite and row-index operations."""

import contextlib
import enum
import hashlib
import pathlib
import re
import sqlite3

import spatial_data.cache_values
import spatial_data.product_cache
import spatial_data.row_index


COLUMNS = ("derivation_key", "value")
READ_CASE_COUNT = 3 * 8 * 4 * 8 * 2 * 2 * 2 * 2
ARTIFACT = pathlib.Path("history.gpkg")
MANIFEST_NAMESPACE, PAYLOAD_NAMESPACE = spatial_data.row_index.namespaces(
    ARTIFACT,
    "history",
)


class Action(enum.IntEnum):
    """Bind trace tokens to observable transaction boundaries."""

    BEGIN = 1
    NEW_PAYLOAD = 2
    SHARED_PAYLOAD = 3
    MANIFEST = 4
    PRUNE = 5
    FAILURE = 6
    COMMIT = 7
    ABORT = 8


def numbers(value: str) -> tuple[int, ...]:
    """Decode the model's small sets and sequences without executing text.

    Args:
        value: TLC's numeric set or sequence representation.

    Returns:
        The numbers in their printed order.
    """
    return tuple(map(int, re.findall(r"\d+", value)))


def rows(key: int) -> spatial_data.row_index.Rows:
    """Keep within-group ordering observable in the implementation bridge.

    Args:
        key: One symbolic group in the formal model.

    Returns:
        Distinct ordered rows represented by that group.
    """
    return [
        {"derivation_key": str(key), "value": key * 10 + offset} for offset in (2, 1)
    ]


def payload(key: int) -> bytes:
    """Use production serialization at the content-addressed boundary.

    Args:
        key: The formal row-group token.

    Returns:
        Its serialized rows.
    """
    return spatial_data.cache_values.dumps(rows(key))


def digest(key: int) -> str:
    """Bind symbolic tokens to actual stored payload checksums.

    Args:
        key: The formal row-group token.

    Returns:
        The production content-addressing digest.
    """
    return hashlib.sha256(payload(key)).hexdigest()


def groups(generation: int) -> dict[str, spatial_data.row_index.Rows]:
    """Make publication ordering differ from numeric key ordering.

    Args:
        generation: One of the two complete formal generations.

    Returns:
        The concrete generation's groups in published order.
    """
    return {str(key): rows(key) for key in ((1, 2) if generation == 1 else (3, 2))}


def manifest(generation: int) -> bytes:
    """Supply the same document used by the production generation writer.

    Args:
        generation: One of the two publication generations.

    Returns:
        A typed manifest of ordered content-addressed groups.
    """
    return spatial_data.cache_values.dumps((
        str(generation),
        COLUMNS,
        tuple((key, digest(int(key))) for key in groups(generation)),
    ))


def read_configuration(state: dict[str, str]) -> tuple[str, ...]:
    """Share expensive storage setup across all queries of the same checked contents.

    Args:
        state: A CacheRead valuation.

    Returns:
        The fields that determine physical storage, excluding query parameters.
    """
    return tuple(
        state[key] for key in ("generation", "payloads", "damaged", "validManifest")
    )


def prepare_read(state: dict[str, str]) -> None:
    """Represent checked storage contents through the real generation writer.

    Args:
        state: A valuation exported by CacheRead.
    """
    generation = int(state["generation"])
    if generation:
        spatial_data.row_index.store_generation(
            (MANIFEST_NAMESPACE, PAYLOAD_NAMESPACE),
            str(generation),
            COLUMNS,
            groups(generation),
        )
    else:
        spatial_data.product_cache.prune(MANIFEST_NAMESPACE, ())
    available = numbers(state["payloads"])
    spatial_data.product_cache.prune(
        PAYLOAD_NAMESPACE,
        tuple(digest(key) for key in available),
    )
    for key in available:
        spatial_data.product_cache.put(
            PAYLOAD_NAMESPACE,
            digest(key),
            b"damaged" if key == int(state["damaged"]) else payload(key),
        )
    if state["validManifest"] == "FALSE":
        spatial_data.product_cache.put(MANIFEST_NAMESPACE, "current", b"invalid")


def replay_read(state: dict[str, str], path: pathlib.Path) -> None:
    """Compare every checked selection with the actual authenticated index reader.

    Args:
        state: A valuation whose physical storage was prepared by the caller.
        path: The isolated SQLite store owned by the caller.
    """
    context = "policy" if state["contextMatches"] == "TRUE" else "other policy"
    with (
        spatial_data.product_cache.scope(
            path,
            context,
            unconditional=state["forced"] == "TRUE",
        ),
        spatial_data.product_cache.scope(path, context),
    ):
        actual = spatial_data.row_index.read(
            ARTIFACT,
            "history",
            state["artifact"],
            tuple(str(key) for key in numbers(state["requested"])),
        )
    expected = numbers(state["answer"])
    if expected == (0,):
        assert actual is None, state
    else:
        assert actual == {str(key): rows(key) for key in expected}, state
        assert actual is not None
        assert tuple(actual) == tuple(str(key) for key in expected), state


def connection_state(connection: sqlite3.Connection) -> tuple[int, frozenset[int]]:
    """Inspect transaction visibility through an independent SQL read.

    Args:
        connection: Either the writer connection or a distinct committed reader.

    Returns:
        Manifest generation and all retained symbolic payload identities.
    """
    document = connection.execute(
        "SELECT value FROM products WHERE context = ? AND namespace = ? AND key = ?",
        ("policy", MANIFEST_NAMESPACE, "current"),
    ).fetchone()
    assert document is not None
    generation = int(spatial_data.row_index.read_manifest(document[0]).checksum)
    retained = {
        key
        for (key,) in connection.execute(
            "SELECT key FROM products WHERE context = ? AND namespace = ?",
            ("policy", PAYLOAD_NAMESPACE),
        )
    }
    return generation, frozenset(key for key in (1, 2, 3) if digest(key) in retained)


def expected_state(value: str) -> tuple[int, frozenset[int]]:
    """Keep the checked record independent of Python's cache implementation.

    Args:
        value: The exported TLA+ cache record.

    Returns:
        Its generation and payload identities.
    """
    match = re.fullmatch(
        r"\[generation \|-> (\d+),\s*payloads \|-> (\{[\d,\s]*\})\]",
        value,
    )
    assert match is not None, value
    return int(match[1]), frozenset(numbers(match[2]))


def write_action(action: Action, writer: sqlite3.Connection, previous: Action) -> None:
    """Exercise the statement named by the checked trace on a real transaction.

    Args:
        action: One write or injected statement failure.
        writer: The open publication transaction.
        previous: The completed prefix determines which statement can fail next.

    Raises:
        AssertionError: If the trace supplies a lifecycle action here.
    """
    match action:
        case Action.NEW_PAYLOAD | Action.SHARED_PAYLOAD:
            key = 3 if action is Action.NEW_PAYLOAD else 2
            spatial_data.product_cache.put(PAYLOAD_NAMESPACE, digest(key), payload(key))
        case Action.MANIFEST:
            spatial_data.product_cache.put(MANIFEST_NAMESPACE, "current", manifest(2))
        case Action.PRUNE:
            spatial_data.product_cache.prune(PAYLOAD_NAMESPACE, (digest(3), digest(2)))
        case Action.FAILURE:
            writer.execute("PRAGMA query_only = ON")
            if previous is Action.MANIFEST:
                spatial_data.product_cache.prune(
                    PAYLOAD_NAMESPACE,
                    (digest(3), digest(2)),
                )
            else:
                spatial_data.product_cache.put("failure", "key", b"rejected")
            assert not spatial_data.product_cache.active()
        case _:
            raise AssertionError(action)


def replay_transaction(state: dict[str, str], path: pathlib.Path) -> None:
    """Replay interruption prefixes against real transactions, including SQL errors.

    Args:
        state: A ProductCache state retaining its complete action prefix.
        path: A fresh isolated database for this prefix.
    """
    with spatial_data.product_cache.scope(path, "policy"):
        spatial_data.row_index.store_generation(
            (MANIFEST_NAMESPACE, PAYLOAD_NAMESPACE),
            "1",
            COLUMNS,
            groups(1),
        )
    owner: contextlib.ExitStack | None = None
    writer: sqlite3.Connection | None = None
    previous = Action.BEGIN
    try:
        for token in numbers(state["trace"]):
            action = Action(token)
            match action:
                case Action.BEGIN:
                    owner = contextlib.ExitStack()
                    owner.enter_context(
                        spatial_data.product_cache.scope(path, "policy"),
                    )
                    store = spatial_data.product_cache.CURRENT.get()
                    assert store is not None
                    writer = store.connection
                case Action.COMMIT | Action.ABORT:
                    assert owner is not None
                    if action is Action.ABORT:
                        error = RuntimeError("interrupted publication")
                        owner.__exit__(RuntimeError, error, None)
                    else:
                        owner.close()
                    owner = None
                    writer = None
                case _:
                    assert writer is not None
                    write_action(action, writer, previous)
            previous = action
        with contextlib.closing(sqlite3.connect(path)) as reader:
            assert connection_state(reader) == expected_state(state["durable"]), state
        if writer is not None:
            assert connection_state(writer) == expected_state(state["pending"]), state
    finally:
        if owner is not None:
            error = RuntimeError("end of checked prefix")
            owner.__exit__(RuntimeError, error, None)
