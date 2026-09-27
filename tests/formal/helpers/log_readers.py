"""Read authenticated rotation states from the checked reader specification."""

import collections
import compression.zstd
import concurrent.futures
import contextlib
import datetime
import fcntl
import hashlib
import json
import pathlib
import threading
import typing

import pytest

import peri_scribe.log_reading
import peri_scribe.logging
import peri_scribe.monitor.history
import tests.formal.helpers.log_rotation
import tests.formal.helpers.tlc


LINES = {
    1: b'{"run_id":"same","event":"one","exception":"retained"}\n',
    2: b'{"run_id":"same","event":"two","exception":"retained"}\n',
}
FIELDS = ("plain", "archive", "source", "base", "target", "snapshot")


def content(sequence: tuple[int, ...], lines: dict[int, bytes] | None = None) -> bytes:
    """Preserve every occurrence rather than treating equal diagnostics as one event.

    Args:
        sequence: Ordered occurrence values from a checked TLC state.
        lines: Concrete payload per formal value, or the diagnostic fixture records.

    Returns:
        Concrete diagnostic bytes with repeated records intact.
    """
    payloads = LINES if lines is None else lines
    return b"".join(payloads[value] for value in sequence)


def checksum(
    sequence: tuple[int, ...],
    *,
    archive: bool,
    lines: dict[int, bytes] | None = None,
) -> str:
    """Authenticate concrete bytes corresponding to a formal content token.

    Args:
        sequence: Records selected by TLC's writer protocol.
        archive: Whether the token represents compressed file bytes.
        lines: Concrete payload per formal value, or the diagnostic fixture records.

    Returns:
        The real receipt checksum of those physical bytes.
    """
    payload = content(sequence, lines)
    return hashlib.sha256(
        compression.zstd.compress(payload) if archive else payload,
    ).hexdigest()


def install(
    state: dict[str, str],
    directory: pathlib.Path,
    *,
    lines: dict[int, bytes] | None = None,
    filename: str = "2026-01.jsonl",
) -> tuple[bytes, ...]:
    """Materialize writer-owned files without running a second selection algorithm.

    Args:
        state: A checked state after the reader acquired the shared lock.
        directory: This isolated month's log directory.
        lines: Concrete payload per formal value, or the diagnostic fixture records.
        filename: The plain filename of the log series under test.

    Returns:
        Exactly the expected observation supplied by the TLA+ specification.
    """
    directory.mkdir(parents=True, exist_ok=True)
    (directory / ".rotation.lock").touch()
    sequences = {
        name: tests.formal.helpers.log_rotation.numbers(state[name]) for name in FIELDS
    }
    plain = directory / filename
    archive = plain.with_suffix(".jsonl.zst")
    payloads = {}
    if sequences["plain"]:
        payloads[plain] = content(sequences["plain"], lines)
    if sequences["archive"]:
        payloads[archive] = compression.zstd.compress(
            content(sequences["archive"], lines),
        )
    receipt_path = peri_scribe.logging.rotation_receipt_path(plain)
    if state["receipt"] == "TRUE":
        receipt = peri_scribe.logging.RotationReceipt(
            source_checksum=checksum(sequences["source"], archive=False, lines=lines),
            archive_checksum=(
                checksum(sequences["base"], archive=True, lines=lines)
                if sequences["base"]
                else None
            ),
            target_checksum=checksum(sequences["target"], archive=True, lines=lines),
        )
        payloads[receipt_path] = receipt.model_dump_json().encode()
    for path in (plain, archive, receipt_path):
        if path not in payloads:
            path.unlink(missing_ok=True)
        elif not path.exists() or path.read_bytes() != payloads[path]:
            path.write_bytes(payloads[path])
    encoded = LINES if lines is None else lines
    return tuple(encoded[value] for value in sequences["snapshot"])


def replay(states: list[dict[str, str]], directory: pathlib.Path) -> int:
    """Exercise whole-month reads and the monitor's archive-to-follower handoff.

    Args:
        states: Every state exported by TLC after successful exhaustive checking.
        directory: Isolated replay root.

    Returns:
        Number of distinct reader-visible durable states exercised.
    """
    selected = {
        tuple(state[name] for name in (*FIELDS, "receipt")): state
        for state in states
        if state["owner"] == '"reader"' and state["reading"] == '"archive"'
    }
    for number, state in enumerate(selected.values()):
        root = directory / str(number)
        expected = install(state, root)
        before = {path.name: path.read_bytes() for path in root.iterdir()}
        for suffix in (".jsonl", ".jsonl.zst"):
            assert (
                tuple(
                    peri_scribe.log_reading.complete_lines(root / ("2026-01" + suffix)),
                )
                == expected
            ), "monthly reader disagrees with the checked observation"
        with contextlib.closing(peri_scribe.monitor.history.Reader(root)) as reader:
            history = reader.poll(datetime.datetime(2026, 1, 15, tzinfo=datetime.UTC))
            assert not history.errors
            observed = tuple(
                event.message for run in history.state.runs for event in run.events
            )
            assert observed == tuple(json.loads(line)["event"] for line in expected)
            assert (
                reader.poll(
                    datetime.datetime(2026, 1, 15, tzinfo=datetime.UTC),
                ).state
                == history.state
            )
        assert {path.name: path.read_bytes() for path in root.iterdir()} == before
    return len(selected)


def concurrent_replay(states: list[dict[str, str]], directory: pathlib.Path) -> None:
    """Compare a read racing a real monthly writer with the model's two snapshots.

    Args:
        states: Reader states exported after successful TLC checking.
        directory: Isolated log directory for the concurrent production execution.
    """
    before = next(
        state
        for state in states
        if state["owner"] == '"reader"'
        and state["reading"] == '"archive"'
        and state["receipt"] == "FALSE"
        and tests.formal.helpers.log_rotation.numbers(state["archive"]) == (2,)
        and tests.formal.helpers.log_rotation.numbers(state["plain"]) == (1, 1)
    )
    after = next(
        state
        for state in states
        if state["owner"] == '"reader"'
        and state["reading"] == '"archive"'
        and state["receipt"] == "FALSE"
        and tests.formal.helpers.log_rotation.numbers(state["archive"]) == (2, 1, 1)
        and tests.formal.helpers.log_rotation.numbers(state["plain"]) == (1,)
    )
    expected = install(before, directory)
    path = directory / "2026-01.jsonl"
    waiting = threading.Event()
    original = fcntl.flock

    def acquire(descriptor: typing.IO[str] | typing.IO[bytes], operation: int) -> None:
        """Locate the real writer lock acquisition without replacing its semantics.

        Args:
            descriptor: Open lock file used by production readers or writers.
            operation: The production locking operation.
        """
        if operation == fcntl.LOCK_EX:
            waiting.set()
        original(descriptor, operation)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(fcntl, "flock", acquire)
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            with contextlib.closing(
                peri_scribe.log_reading.complete_lines(path),
            ) as lines:
                first = next(lines)
                future = executor.submit(
                    peri_scribe.logging.append_monthly_records,
                    directory,
                    (json.loads(LINES[1]),),
                    timestamp=datetime.datetime(2026, 1, 15, tzinfo=datetime.UTC),
                )
                assert waiting.wait(5), "writer never reached its actual exclusive lock"
                assert not future.done(), "writer crossed an active reader lock"
                assert (first, *lines) == expected
            future.result(timeout=10)
    observed = tuple(
        json.loads(line)["event"]
        for line in peri_scribe.log_reading.complete_lines(path)
    )
    expected_after = tuple(
        json.loads(LINES[value])["event"]
        for value in tests.formal.helpers.log_rotation.numbers(after["snapshot"])
    )
    assert observed == expected_after


def successive_replay(
    graph: tests.formal.helpers.tlc.Graph,
    directory: pathlib.Path,
) -> int:
    """Follow actual TLC successors between two observations by the same reader.

    Args:
        graph: Complete checked graph including its actual directed edges.
        directory: Isolated root for each two-poll implementation execution.

    Returns:
        Number of distinct durable observation pairs connected by checked paths.
    """
    pairs: dict[
        tuple[tuple[str, ...], tuple[str, ...]],
        tuple[dict[str, str], dict[str, str]],
    ] = {}
    for identifier, state in graph.states.items():
        if state["reading"] != '"release"' or state["completed"] != "0":
            continue
        first = tuple(state[name] for name in (*FIELDS, "receipt"))
        seen = {identifier}
        pending = collections.deque((identifier,))
        while pending:
            current = pending.popleft()
            candidate = graph.states[current]
            if candidate["reading"] == '"release"' and candidate["completed"] == "1":
                second = tuple(candidate[name] for name in (*FIELDS, "receipt"))
                pairs[first, second] = state, candidate
                continue
            for edge in graph.outgoing.get(current, ()):
                if edge.target not in seen:
                    seen.add(edge.target)
                    pending.append(edge.target)
    for number, (first_state, second_state) in enumerate(pairs.values()):
        root = directory / str(number)
        first_expected = install(first_state, root)
        with contextlib.closing(peri_scribe.monitor.history.Reader(root)) as reader:
            for state, initial in (
                (first_state, first_expected),
                (second_state, None),
            ):
                expected = install(state, root) if initial is None else initial
                before = {path.name: path.read_bytes() for path in root.iterdir()}
                history = reader.catch_up(
                    datetime.datetime(2026, 1, 15, tzinfo=datetime.UTC),
                )
                assert not history.errors
                observed = tuple(
                    event.message for run in history.state.runs for event in run.events
                )
                assert observed == tuple(
                    json.loads(line)["event"] for line in expected
                ), (
                    "successive monitor polls disagree with the checked path",
                    first_state,
                    second_state,
                )
                assert {
                    path.name: path.read_bytes() for path in root.iterdir()
                } == before
    return len(pairs)
