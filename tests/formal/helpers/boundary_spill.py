"""Check every spool prefix using native witnesses and immutable observations."""

import collections.abc
import contextlib
import dataclasses
import enum
import hashlib
import inspect
import io
import itertools
import os
import pathlib
import tempfile
import types
import typing
from unittest.mock import patch

import kml_io.fragments
import spatial_data.payload_codec
import tests.formal.helpers.ordered_workers


PAYLOADS = types.MappingProxyType({0: None, 1: b"a", 2: b"b", 3: b"long"})
FAILED_WRITE = 2
READ = 3
DAMAGE = 4
CLOSE = 2
OPEN = 1
BUDGET = 4

# A source change may add an observation that the shared image does not capture.
SOURCES = (
    (
        kml_io.fragments,
        "b42fca2fb1dc4b42b024111ef75a9250dbe5ebeb298b2b16e0a408c052487a64",
    ),
    (
        spatial_data.payload_codec,
        "a6f22e62a6d65b62c4bb40667deaa9642b6466744cabac7a6a1c85f268855f23",
    ),
)
BINDINGS = tuple(
    (owner, name, value, getattr(value, "__code__", None))
    for owner, names in (
        (
            kml_io.fragments,
            (
                "BoundaryCache",
                "BoundarySpool",
                "SpillEntry",
                "contextlib",
                "hashlib",
                "tempfile",
            ),
        ),
        (kml_io.fragments.BoundaryCache, ("__init__", "spill")),
        (kml_io.fragments.BoundarySpool, ("__init__", "get", "put")),
        (spatial_data, ("payload_codec",)),
        (
            spatial_data.payload_codec,
            (
                "encode",
                "decode",
                "decoded_size",
                "RAW_TAG",
                "MINIMUM_COMPRESSION_BYTES",
                "MAX_DECODED_BYTES",
            ),
        ),
        (contextlib, ("ExitStack",)),
        (hashlib, ("sha256",)),
        (io, ("open", "FileIO")),
        (os, ("open", "unlink", "close", "fstat")),
        (tempfile, ("TemporaryFile",)),
    )
    for name in names
    for value in (getattr(owner, name),)
)
SPILL_BODY = inspect.unwrap(kml_io.fragments.BoundaryCache.spill)
SPILL_CODE = getattr(SPILL_BODY, "__code__", None)


class Scope(enum.StrEnum):
    """Track whether the document still owns its native stream."""

    NEW = "new"
    ACTIVE = "active"
    CLOSED = "closed"


@dataclasses.dataclass(frozen=True, kw_only=True, slots=True)
class Image:
    """Keep the complete concrete state of the qualified operation boundary."""

    limit: int
    owner: Scope
    content: bytes = b""
    cursor: int = 0
    entries: tuple[tuple[str, kml_io.fragments.SpillEntry], ...] = ()
    used: int = 0
    disabled: bool = False
    result: int = 0
    corrupt: frozenset[int] = frozenset()


def shares_native_observations() -> bool:
    """Limit sharing to the reviewed spool, raw codec, and native file bindings.

    Returns:
        Whether exact prior images account for all inputs of the live operation.
    """
    if os.name != "posix" or not all(
        getattr(owner, name, None) is value and getattr(value, "__code__", None) is code
        for owner, name, value, code in BINDINGS
    ):
        return False
    try:
        return (
            inspect.unwrap(kml_io.fragments.BoundaryCache.spill) is SPILL_BODY
            and getattr(SPILL_BODY, "__code__", None) is SPILL_CODE
            and all(itertools.starmap(matches_source, SOURCES))
        )
    except OSError, ValueError:
        return False


def matches_source(module: types.ModuleType, digest: str) -> bool:
    """Identify the source used to establish the concrete image's completeness.

    Args:
        module: An application module supplying the spool or byte codec.
        digest: SHA-256 of the reviewed source file.

    Returns:
        Whether the module still points to that exact file content.
    """
    source = module.__file__
    return source is not None and (
        hashlib.sha256(pathlib.Path(source).read_bytes()).hexdigest() == digest
    )


def reject_write(_frame: bytes) -> typing.Never:
    """Interrupt the write before any bytes reach the spool.

    Raises:
        OSError: Always, to simulate a failed file write.
    """
    raise OSError


def apply(action: int, spool: kml_io.fragments.BoundarySpool) -> int | None:
    """Exercise actual append, authentication, capacity, and failure decisions.

    Args:
        action: Model operation token, including its requested key.
        spool: The production spool owned by the current document scope.

    Returns:
        An observed result token for reads, otherwise None.
    """
    family, key = divmod(action, 10)
    payload = PAYLOADS[key]
    assert payload is not None
    if family == 1:
        spool.put(str(key), payload)
    elif family == FAILED_WRITE:
        with patch.object(spool.stream, "write", new=reject_write):
            spool.put(str(key), payload)
    elif family == READ:
        actual = spool.get(str(key))
        return next(token for token, expected in PAYLOADS.items() if actual == expected)
    else:
        entry = spool.entries[str(key)]
        spool.stream.seek(entry.offset + 1)
        spool.stream.write(b"x")
    return None


def capture(
    spool: kml_io.fragments.BoundarySpool | None,
    *,
    limit: int,
    owner: Scope,
    disabled: bool,
    corrupt: set[int],
    result: int,
    exact: bool,
) -> Image:
    """Capture the observation and preserve the cursor when sharing the full image.

    Args:
        spool: The current native stream and its index, if the scope is active.
        limit: The configured entry limit for this history.
        owner: The scope reached by the actual native replay.
        disabled: The last write policy retained when a scope closed.
        corrupt: The entries with an injected corrupt byte.
        result: The last reported read result, or zero when there is no result.
        exact: Whether another qualified history may use these native bytes.

    Returns:
        A complete immutable observation of this prefix.
    """
    if spool is None:
        return Image(
            limit=limit,
            owner=owner,
            disabled=disabled,
            result=result,
            corrupt=frozenset(corrupt),
        )
    if exact:
        assert spool.limit == limit
        assert spool.budget == BUDGET
        cursor = spool.stream.tell()
        spool.stream.seek(0)
        content = spool.stream.read()
        spool.stream.seek(cursor)
        length = len(content)
    else:
        spool.stream.seek(0, os.SEEK_END)
        length = spool.stream.tell()
        content, cursor = b"", 0
    assert length <= spool.size <= spool.budget
    return Image(
        limit=limit,
        owner=owner,
        content=content,
        cursor=cursor,
        entries=tuple(spool.entries.items()),
        used=spool.size,
        disabled=spool.disabled,
        result=result,
        corrupt=frozenset(corrupt),
    )


def check(state: dict[str, str], image: Image) -> None:
    """Check every projected field from the model's complete operation prefix.

    Args:
        state: The checked model row for this prefix.
        image: The exact native observation associated with it.
    """
    numbers = tests.formal.helpers.ordered_workers.numbers
    assert image.owner == state["scope"].strip('"')
    assert image.result == int(state["result"]), (state["trace"], image.result)
    assert image.corrupt == frozenset(numbers(state["corrupt"]))
    assert {int(key) for key, _ in image.entries} == set(numbers(state["stored"]))
    assert image.used == int(state["used"])
    assert image.disabled == (state["disabled"] == "TRUE")
    assert image.limit == int(state["limit"])


def replay(
    state: dict[str, str],
    *,
    before: Image | None = None,
    exact: bool = True,
) -> Image:
    """Run a complete history in one private spool to witness its last action.

    Args:
        state: A checked state containing the full action prefix and expected state.
        before: The earlier exact image that this witness must reproduce, if shared.
        exact: Whether to retain the raw image or only check the model observation.

    Returns:
        The native after-image for the complete operation prefix.
    """
    cache = kml_io.fragments.BoundaryCache()
    trace = tests.formal.helpers.ordered_workers.numbers(state["trace"])
    limit = int(state["limit"])
    actual_result = 0
    owner = Scope.NEW
    corrupt: set[int] = set()
    disabled = False
    with contextlib.ExitStack() as resources:
        for index, action in enumerate(trace, start=1):
            if before is not None and index == len(trace):
                assert before == capture(
                    cache.spool,
                    limit=limit,
                    owner=owner,
                    disabled=disabled,
                    corrupt=corrupt,
                    result=actual_result,
                    exact=True,
                )
            if action == OPEN:
                resources.enter_context(cache.spill())
                assert cache.spool is not None
                cache.spool.limit = limit
                cache.spool.budget = BUDGET
                owner = Scope.ACTIVE
            elif action == CLOSE:
                assert cache.spool is not None
                stream = cache.spool.stream
                disabled = cache.spool.disabled
                resources.close()
                assert cache.spool is None
                assert stream.closed
                owner = Scope.CLOSED
                corrupt.clear()
                actual_result = 0
            else:
                assert cache.spool is not None
                value = apply(action, cache.spool)
                if value is not None:
                    actual_result = value
                if action // 10 == DAMAGE:
                    corrupt.add(action % 10)
        image = capture(
            cache.spool,
            limit=limit,
            owner=owner,
            disabled=disabled,
            corrupt=corrupt,
            result=actual_result,
            exact=exact,
        )
    check(state, image)
    return image


def replay_prefixes(states: collections.abc.Sequence[dict[str, str]]) -> None:
    """Check all prefixes, sharing a fresh native result for each exact next action.

    Args:
        states: The full checked inventory, including each prefix's predecessor.

    """
    if not shares_native_observations():
        for state in states:
            replay(state, exact=False)
        return

    numbers = tests.formal.helpers.ordered_workers.numbers
    ordered = sorted(
        ((numbers(state["trace"]), state) for state in states),
        key=lambda pair: len(pair[0]),
    )
    prefixes: dict[tuple[int, tuple[int, ...]], Image] = {}
    effects: dict[tuple[Image, int], Image] = {}
    for trace, state in ordered:
        limit = int(state["limit"])
        key = limit, trace
        assert key not in prefixes
        if not trace:
            image = replay(state)
        else:
            before = prefixes[limit, trace[:-1]]
            request = before, trace[-1]
            image = effects.get(request)
            if image is None:
                image = replay(state, before=before)
                effects[request] = image
            else:
                check(state, image)
        prefixes[key] = image
