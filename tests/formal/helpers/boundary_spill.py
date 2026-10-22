"""Replay every checked disposable-spool prefix against actual private files."""

import contextlib
from unittest.mock import patch

import kml_io.fragments
import tests.formal.helpers.ordered_workers


PAYLOADS = {0: None, 1: b"a", 2: b"b", 3: b"long"}
FAILED_WRITE = 2
READ = 3
DAMAGE = 4
CLOSE = 2


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
        with patch.object(spool.stream, "write", side_effect=OSError):
            spool.put(str(key), payload)
    elif family == READ:
        actual = spool.get(str(key))
        return next(token for token, expected in PAYLOADS.items() if actual == expected)
    else:
        entry = spool.entries[str(key)]
        spool.stream.seek(entry.offset + 1)
        spool.stream.write(b"x")
    return None


def replay(state: dict[str, str]) -> None:
    """Retain the whole operation prefix before checking its concrete observation.

    Args:
        state: A checked state containing its complete action prefix and expected state.
    """
    cache = kml_io.fragments.BoundaryCache()
    trace = tests.formal.helpers.ordered_workers.numbers(state["trace"])
    actual_result = 0
    owner = "new"
    corrupt: set[int] = set()
    disabled = False
    with contextlib.ExitStack() as resources:
        for action in trace:
            if action == 1:
                resources.enter_context(cache.spill())
                assert cache.spool is not None
                cache.spool.limit = int(state["limit"])
                cache.spool.budget = 4
                owner = "active"
            elif action == CLOSE:
                assert cache.spool is not None
                stream = cache.spool.stream
                disabled = cache.spool.disabled
                resources.close()
                assert cache.spool is None
                assert stream.closed
                owner = "closed"
                corrupt.clear()
                actual_result = 0
            else:
                assert cache.spool is not None
                value = apply(action, cache.spool)
                if value is not None:
                    actual_result = value
                if action // 10 == DAMAGE:
                    corrupt.add(action % 10)
        assert owner == state["scope"].strip('"')
        assert actual_result == int(state["result"])
        assert corrupt == set(
            tests.formal.helpers.ordered_workers.numbers(state["corrupt"]),
        )
        if cache.spool is None:
            entries: set[int] = set()
            used = 0
        else:
            entries = set(map(int, cache.spool.entries))
            used = cache.spool.size
            disabled = cache.spool.disabled
            cache.spool.stream.seek(0, 2)
            assert cache.spool.stream.tell() <= used <= cache.spool.budget
        assert entries == set(
            tests.formal.helpers.ordered_workers.numbers(state["stored"]),
        )
        assert used == int(state["used"])
        assert disabled == (state["disabled"] == "TRUE")
