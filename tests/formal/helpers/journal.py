"""Replay TLC's crash recovery relations through real durable journal files."""

import collections
import compression.zstd
import dataclasses
import datetime
import json
import pathlib
import re

import time_machine

import peri_scribe.fire_updates
import peri_scribe.publication
import peri_scribe.updates
import tests.formal.helpers.corpus


EPOCH = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
LOG_NAME = "2026-01-fire-updates.jsonl"


@dataclasses.dataclass(frozen=True)
class Durable:
    """Represent the observable durable fields in a checked journal state."""

    journal: int
    checkpoint: int
    journal_time: int
    plain: tuple[int, ...]
    archive: tuple[int, ...]
    logged_times: tuple[int, ...]


@dataclasses.dataclass(frozen=True)
class Recovery:
    """Pair a reachable crash state with its checked uninterrupted recovery."""

    before: Durable
    after: Durable
    old_month: bool
    has_records: tuple[bool, ...]


def durable(text: str) -> Durable:
    """Decode observable fields without implementing the model's transitions.

    Args:
        text: A durable record exported verbatim by TLC.

    Returns:
        Fields needed to construct and compare actual filesystem state.
    """
    scalars = dict(re.findall(r"(\w+) \|-> (\d+)", text))
    vectors = {
        key: tuple(map(int, values.split(", ")))
        for key, values in re.findall(r"(\w+) \|-> <<([\d, ]+)>>", text)
    }
    return Durable(
        journal=int(scalars["journal"]),
        checkpoint=int(scalars["checkpoint"]),
        journal_time=int(scalars["journalTime"]),
        plain=vectors["plain"],
        archive=vectors["archive"],
        logged_times=vectors["loggedTimes"],
    )


def recoveries(directory: pathlib.Path) -> tuple[Recovery, ...]:
    """Obtain expected recovery outcomes from the checked TLA+ relation.

    Args:
        directory: An isolated directory for the TLC graph export.

    Returns:
        Every distinct observable recovery relation, including empty batches.
    """
    records = {}
    for fields in tests.formal.helpers.corpus.states(
        "JournalReplay",
        "JournalReplay",
        directory,
    ):
        if fields["recovered"] != "TRUE":
            continue
        outcome = Recovery(
            before=durable(fields["recoveryInput"]),
            after=durable(fields["durable"]),
            old_month=fields["recoveryAge"] == "TRUE",
            has_records=tuple(
                item == "TRUE"
                for item in re.findall(r"TRUE|FALSE", fields["hasRecords"])
            ),
        )
        records[outcome] = None
    assert {record.before.journal for record in records} == {1, 2}
    assert {record.old_month for record in records} == {False, True}
    assert {record.has_records for record in records} == {
        (False, False),
        (False, True),
        (True, False),
        (True, True),
    }
    assert any(
        any(
            plain and archive
            for plain, archive in zip(
                record.before.plain,
                record.before.archive,
                strict=True,
            )
        )
        for record in records
    )
    return tuple(records)


def checkpoint(batch: int) -> peri_scribe.fire_updates.State:
    """Give each batch a distinct cumulative checkpoint payload.

    Args:
        batch: The abstract completed mapping generation.

    Returns:
        A real serialized checkpoint retaining earlier generations.
    """
    return peri_scribe.fire_updates.State(
        perimeters={
            json.dumps(("id", "fire")): frozenset(
                str(index) for index in range(1, batch + 1)
            ),
        },
    )


def records(batch: int) -> tuple[dict[str, object], ...]:
    """Exercise atomic batches with multiple independently identified fire records.

    Args:
        batch: The generation supplying measured acreage.

    Returns:
        Two valid log payloads whose batch membership must remain intact.
    """
    return tuple(
        {
            "identifier": f"fire-{number}",
            "log_identity": ["id", f"fire-{number}"],
            "name": f"Fire {number}",
            "location": None,
            "mapped_area": {"value": batch * 10 + number, "units": "acre"},
        }
        for number in range(2)
    )


def entries(counts: tuple[int, ...], times: tuple[int, ...]) -> str:
    """Serialize the exact batch multiplicities and original timestamps from TLC.

    Args:
        counts: Per-batch multiplicities in one physical representation.
        times: The saved original completion time for each batch.

    Returns:
        Valid JSONL bytes represented as text for plain and Zstandard files.
    """
    return "".join(
        json.dumps({
            **record,
            "batch_id": f"batch-{batch}",
            "timestamp": (
                EPOCH + datetime.timedelta(seconds=times[batch - 1])
            ).isoformat(),
        })
        + "\n"
        for batch, count in enumerate(counts, 1)
        for _ in range(count)
        for record in records(batch)
    )


def seed(directory: pathlib.Path, outcome: Recovery) -> None:
    """Materialize a reachable interrupted journal state using real encodings.

    Args:
        directory: The isolated year directory.
        outcome: The checked recovery input, age, and record-presence choices.
    """
    before = outcome.before
    logs = directory / "logs"
    logs.mkdir(parents=True)
    for counts, path, compressed in (
        (before.plain, logs / LOG_NAME, False),
        (before.archive, logs / (LOG_NAME + ".zst"), True),
    ):
        if any(counts):
            opener = compression.zstd.open if compressed else open
            with opener(path, "wt", encoding="utf-8") as stream:
                stream.write(entries(counts, before.logged_times))
    if before.checkpoint:
        peri_scribe.publication.write_state(
            peri_scribe.fire_updates.state_path(directory),
            checkpoint(before.checkpoint),
        )
    peri_scribe.publication.write_state(
        peri_scribe.fire_updates.pending_path(directory),
        peri_scribe.fire_updates.PendingUpdates(
            records=records(before.journal)
            if outcome.has_records[before.journal - 1]
            else (),
            state=checkpoint(before.journal),
            timestamp=EPOCH + datetime.timedelta(seconds=before.journal_time),
            batch_id=f"batch-{before.journal}",
        ),
    )


def assert_logs(directory: pathlib.Path, expected: Durable) -> None:
    """Compare physical copies, entire batch payloads, and preserved timestamps.

    Args:
        directory: The recovered year directory.
        expected: The durable state computed by TLC's recovery transitions.
    """
    for counts, path, compressed in (
        (expected.plain, directory / "logs" / LOG_NAME, False),
        (expected.archive, directory / "logs" / (LOG_NAME + ".zst"), True),
    ):
        actual = ""
        if path.exists():
            opener = compression.zstd.open if compressed else open
            with opener(path, "rt", encoding="utf-8") as stream:
                actual = stream.read()
        assert collections.Counter(
            peri_scribe.updates.LogEntry.model_validate_json(line).model_dump_json()
            for line in actual.splitlines()
        ) == collections.Counter(
            peri_scribe.updates.LogEntry.model_validate_json(line).model_dump_json()
            for line in entries(counts, expected.logged_times).splitlines()
        )


def replay(outcome: Recovery, directory: pathlib.Path) -> None:
    """Run recovery twice and publish a viewer from its actual log files.

    Args:
        outcome: The checked input/output relation, with explicit clock age.
        directory: A separate filesystem location for this replay.
    """
    seed(directory, outcome)
    now = EPOCH + datetime.timedelta(days=60 if outcome.old_month else 0, seconds=10)
    with time_machine.travel(now, tick=False):
        for _ in range(2):
            peri_scribe.fire_updates.recover_updates(directory)
            assert not peri_scribe.fire_updates.pending_path(directory).exists()
            assert peri_scribe.publication.read_state(
                peri_scribe.fire_updates.state_path(directory),
                peri_scribe.fire_updates.State,
            ) == checkpoint(outcome.after.checkpoint)
            assert_logs(directory, outcome.after)
        peri_scribe.updates.write_updates_page(directory)
    snapshot = peri_scribe.updates.Snapshot.model_validate_json(
        (directory / "maps" / "updates.json").read_bytes(),
    )
    assert snapshot.generated_at == now
    assert snapshot.updates == viewer_records(outcome.after, now)
    assert (directory / "maps" / "updates.html").is_file()


def viewer_records(
    expected: Durable,
    now: datetime.datetime,
) -> tuple[peri_scribe.updates.Update, ...]:
    """Specify per-fire viewer payloads from TLC's acknowledged log generations.

    Args:
        expected: The checked durable log contents and original timestamps.
        now: The current or expired-month viewer generation time.

    Returns:
        Every visible modeled batch with its complete payload and prior acreage.
    """
    counts = tuple(
        plain + archive
        for plain, archive in zip(expected.plain, expected.archive, strict=True)
    )
    result = []
    for batch, count in enumerate(counts, 1):
        timestamp = EPOCH + datetime.timedelta(seconds=expected.logged_times[batch - 1])
        if not count or not now - datetime.timedelta(hours=48) < timestamp <= now:
            continue
        for number, record in enumerate(records(batch)):
            entry = peri_scribe.updates.LogEntry.model_validate({
                **record,
                "timestamp": timestamp,
                "batch_id": f"batch-{batch}",
            })
            previous = max(
                (earlier for earlier in range(1, batch) if counts[earlier - 1]),
                default=0,
            )
            result.append(
                peri_scribe.updates.Update(
                    **entry.model_dump(),
                    previous_mapped_area=(
                        peri_scribe.updates.Acreage(value=10 * previous + number)
                        if previous
                        else None
                    ),
                ),
            )
    return tuple(result)
