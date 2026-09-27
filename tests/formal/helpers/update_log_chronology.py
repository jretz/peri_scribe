"""Connect checked physical log representations to Lean's complete snapshot oracle."""

import concurrent.futures
import dataclasses
import datetime
import fcntl
import itertools
import json
import pathlib
import threading
import typing

import pytest
import time_machine

import peri_scribe.fire_updates
import peri_scribe.logging
import peri_scribe.publication
import peri_scribe.updates
import tests.formal.helpers.log_readers
import tests.formal.helpers.log_rotation
import tests.formal.helpers.oracle
import tests.formal.helpers.projected_snapshots
import tests.formal.helpers.tlc
import tests.formal.helpers.update_viewer
import tests.helpers.factories.peri_scribe.updates


NOW = tests.formal.helpers.update_viewer.NOW
OLD = -int(datetime.timedelta(days=23).total_seconds() * 1000)
PHYSICAL_STATES = 20
COMPOSED_CASES = 240
type Key = tuple[int, int]
Observation = tests.formal.helpers.update_viewer.Observation


@dataclasses.dataclass(frozen=True, kw_only=True)
class Case:
    """Keep physical input separate from the oracle's logical occurrence history."""

    state: dict[str, str]
    payloads: dict[int, Observation]
    current: Observation
    snapshot: tests.formal.helpers.projected_snapshots.Case


def cases(directory: pathlib.Path) -> tuple[Case, ...]:
    """Cross every reader-visible rotation state with time order and ownership changes.

    Args:
        directory: Isolated TLC output directory.

    Returns:
        Checked physical representations and raw logical inputs to the Lean oracle.
    """
    fields = (*tests.formal.helpers.log_readers.FIELDS, "receipt")
    states = {
        tuple(state[field] for field in fields): state
        for state in tests.formal.helpers.tlc.states(
            "LogReaders",
            "LogReaders",
            directory,
        )
        if state["owner"] == '"reader"' and state["reading"] == '"archive"'
    }
    assert len(states) == PHYSICAL_STATES
    layouts: tuple[tuple[Key, Key, tuple[tuple[Key, Key], ...]], ...] = (
        ((0, 0), (0, 0), ()),
        ((0, 0), (0, 1), ()),
        ((0, 0), (0, 1), (((0, 0), (2, 0)), ((0, 1), (2, 0)))),
        ((2, 0), (3, 0), (((2, 0), (3, 0)), ((3, 0), (2, 0)))),
    )
    result = []
    for state, times, (first, second, owners) in itertools.product(
        states.values(),
        ((OLD, OLD), (OLD - 1000, OLD), (OLD, OLD - 1000)),
        layouts,
    ):
        payloads = {
            number: Observation(
                serial=number,
                time=time,
                name=number - 1,
                identifier=number - 1,
                logged=identity,
                area=area * 8,
            )
            for number, time, identity, area in (
                (2, times[0], first, 100),
                (1, times[1], second, 200),
            )
        }
        current = Observation(serial=3, time=0, name=2, logged=second, area=150 * 8)
        logical = tuple(
            payloads[number]
            for number in tests.formal.helpers.log_rotation.numbers(state["snapshot"])
        )
        result.append(
            Case(
                state=state,
                payloads=payloads,
                current=current,
                snapshot=tests.formal.helpers.projected_snapshots.Case(
                    history=(*logical, current),
                    ownership=owners,
                ),
            ),
        )
    assert len(result) == COMPOSED_CASES
    return tuple(result)


def install(case: Case, directory: pathlib.Path) -> dict[str, str]:
    """Materialize physical overlap and receipts independently of logical selection.

    Args:
        case: One checked physical state and its typed observation payloads.
        directory: Isolated year holding the actual log and checkpoint files.

    Returns:
        The current owner map supplied independently to both implementations.
    """
    tests.formal.helpers.log_readers.install(
        case.state,
        directory / "logs",
        filename="2026-08-fire-updates.jsonl",
        lines={
            value: (row.record().model_dump_json() + "\n").encode()
            for value, row in case.payloads.items()
        },
    )
    tests.helpers.factories.peri_scribe.updates.write_log(
        directory / "logs" / "2026-09-fire-updates.jsonl",
        [case.current.record()],
    )
    owners = {
        json.dumps(tests.formal.helpers.projected_snapshots.identity(key)): json.dumps(
            tests.formal.helpers.projected_snapshots.identity(owner),
        )
        for key, owner in case.snapshot.ownership
    }
    peri_scribe.publication.write_state(
        peri_scribe.fire_updates.state_path(directory),
        peri_scribe.fire_updates.State(owners=owners),
    )
    return owners


def expected_snapshot(
    case: Case,
    answer: tuple[int, ...],
    owners: dict[str, str],
) -> peri_scribe.updates.Snapshot:
    """Decode oracle inclusion, order, grouping, and baselines without reselecting rows.

    Args:
        case: Original payloads whose immutable fields must be retained.
        answer: Flat complete-snapshot output from the compiled Lean definitions.
        owners: Independently supplied partial projection map.

    Returns:
        Exact expected publication including every original log field.
    """
    originals = {row.serial: row.record() for row in case.snapshot.history}
    result = []
    for serial, kind, key, owner_kind, owner_key, previous in itertools.batched(
        answer,
        6,
        strict=True,
    ):
        record = originals[serial]
        assert record.identity() == tests.formal.helpers.projected_snapshots.identity((
            kind,
            key,
        ))
        owner = tests.formal.helpers.projected_snapshots.identity((
            owner_kind,
            owner_key,
        ))
        projected = json.dumps(record.identity()) in owners
        result.append(
            peri_scribe.updates.Update(
                **record.model_dump(),
                history_identity=owner if projected else None,
                previous_mapped_area=(
                    peri_scribe.updates.Acreage(value=previous / 8)
                    if previous >= 0
                    else None
                ),
            ),
        )
    return peri_scribe.updates.Snapshot(generated_at=NOW, updates=tuple(result))


def replay(catalogue: tuple[Case, ...], directory: pathlib.Path) -> int:
    """Require whole filesystem-to-published-snapshot agreement with both references.

    Args:
        catalogue: Checked rotation projections crossed with raw snapshot scenarios.
        directory: Parent of the isolated real publication directories.

    Returns:
        Number of complete artifact compositions checked.
    """
    answers = tests.formal.helpers.oracle.evaluate(
        [case.snapshot.command() for case in catalogue],
        executable="oraclePresentationFlow",
    )
    for index, (case, answer) in enumerate(zip(catalogue, answers, strict=True)):
        root = directory / str(index)
        owners = install(case, root)
        retained = {
            path: path.read_bytes() for path in root.rglob("*") if path.is_file()
        }
        records = peri_scribe.updates.read_entries(root)
        assert records == tuple(row.record() for row in case.snapshot.history), (
            "update reader disagrees with checked logical occurrence order",
            case,
        )
        expected = expected_snapshot(case, answer, owners)
        assert (
            peri_scribe.updates.snapshot_from_entries(records, NOW, owners=owners)
            == expected
        )
        with time_machine.travel(NOW, tick=False):
            peri_scribe.updates.write_updates_page(root)
        actual = peri_scribe.updates.Snapshot.model_validate_json(
            (root / "maps" / "updates.json").read_bytes(),
        )
        assert actual == expected
        assert all(path.read_bytes() == content for path, content in retained.items())
    return len(catalogue)


def concurrent_read(catalogue: tuple[Case, ...], directory: pathlib.Path) -> None:
    """Keep a real writer outside the archive/plain discovery and read interval.

    Args:
        catalogue: Checked physical states with independent logical occurrence order.
        directory: Isolated year for the competing reader and monthly appender.
    """
    before = next(
        case
        for case in catalogue
        if case.state["receipt"] == "FALSE"
        and case.state["archive"] == "<<2>>"
        and case.state["plain"] == "<<1, 1>>"
    )
    after = next(
        case
        for case in catalogue
        if case.payloads == before.payloads
        and case.state["receipt"] == "FALSE"
        and case.state["archive"] == "<<2, 1, 1>>"
        and case.state["plain"] == "<<1>>"
    )
    install(before, directory)
    parsing = threading.Event()
    release = threading.Event()
    waiting = threading.Event()
    validate = peri_scribe.updates.LogEntry.model_validate_json
    flock = fcntl.flock

    def observe_parse(line: str) -> peri_scribe.updates.LogEntry:
        """Pause inside the real read interval to expose a competing writer.

        Args:
            line: An actual serialized update occurrence.

        Returns:
            The original schema's validated record.
        """
        if not parsing.is_set():
            parsing.set()
            assert release.wait(10), "reader was never released"
        return validate(line)

    def acquire(descriptor: typing.IO[str] | typing.IO[bytes], operation: int) -> None:
        """Observe a genuine lock attempt without changing its exclusion behavior.

        Args:
            descriptor: The production lock file descriptor.
            operation: The production shared or exclusive lock request.
        """
        if operation == fcntl.LOCK_EX:
            waiting.set()
        flock(descriptor, operation)

    late = before.payloads[1].record()
    with (
        pytest.MonkeyPatch.context() as patch,
        time_machine.travel(NOW, tick=False),
        concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor,
    ):
        patch.setattr(
            peri_scribe.updates.LogEntry,
            "model_validate_json",
            staticmethod(observe_parse),
        )
        patch.setattr(fcntl, "flock", acquire)
        reader = executor.submit(peri_scribe.updates.read_entries, directory)
        try:
            assert parsing.wait(5), "reader never began validating real records"
            writer = executor.submit(
                peri_scribe.logging.append_monthly_records,
                directory / "logs",
                (late.model_dump(mode="json", exclude={"timestamp"}),),
                suffix="-fire-updates",
                timestamp=late.timestamp,
            )
            assert waiting.wait(5), "writer never attempted its exclusive lock"
            assert not writer.done(), "writer crossed the active update reader lock"
        finally:
            release.set()
        assert reader.result(timeout=10) == tuple(
            row.record() for row in before.snapshot.history
        )
        writer.result(timeout=10)
    assert peri_scribe.updates.read_entries(directory) == tuple(
        row.record() for row in after.snapshot.history
    )
