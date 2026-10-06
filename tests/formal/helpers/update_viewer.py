"""Follow retained update history through serialized snapshots and actual DOM rows."""

import compression.zstd
import dataclasses
import datetime
import itertools
import json
import pathlib
import shutil

import peri_scribe.updates
import tests.formal.helpers.oracle
import tests.formal.helpers.process


NOW = datetime.datetime(2026, 9, 23, 12, tzinfo=datetime.UTC)
WINDOW = 172_800_000
NAMES = ("Alpha", "Beta", "Gamma", "Fire 2", "Fire 10")
NAME_ORDER = (0, 1, 4, 2, 3)
KINDS = ("id", "name", "local", "component")
LOCAL_IDENTITY = 2
NAMED_IDENTITY = 3


@dataclasses.dataclass(frozen=True, kw_only=True)
class Observation:
    """Keep comparison policy separate from float rounding with exact eighth acres."""

    serial: int
    time: int
    name: int
    area: int
    identifier: int | None = None
    logged: tuple[int, int] | None = None

    def text(self) -> str:
        """Keep stable identity fields independent until the proved policy runs.

        Returns:
            An oracle row containing the unprocessed observation fields.
        """
        kind, key = self.logged or ("-", "-")
        identifier = "-" if self.identifier is None else self.identifier
        return (
            f"{self.serial},{self.time},{identifier},{self.name},"
            f"{kind},{key},{self.area}"
        )

    def record(self) -> peri_scribe.updates.LogEntry:
        """Create the validated production record at the same exact timestamp.

        Returns:
            An ordinary log record; the serial travels only as nonidentity batch data.
        """
        logged = None
        if self.logged is not None:
            kind, key = self.logged
            logged = (KINDS[kind], NAMES[key] if kind == 1 else str(key))
        return peri_scribe.updates.LogEntry.model_validate({
            "timestamp": NOW + datetime.timedelta(milliseconds=self.time),
            "identifier": str(self.identifier) if self.identifier is not None else None,
            "name": NAMES[self.name],
            "location": "County, CA" if self.serial % 2 else None,
            "mapped_area": {"value": self.area / 8, "units": "acre"},
            "batch_id": str(self.serial),
            "log_identity": logged,
        })


def histories() -> tuple[tuple[Observation, ...], ...]:
    """Cross cutoff timing, decreases, first zeroes, ties, and typed stable identity.

    Returns:
        Complete retained histories, including permutations and repeated input records.
    """
    result = [()]
    for times, areas, identity in itertools.product(
        itertools.product((-WINDOW - 1, -WINDOW, -WINDOW + 1, -1, 0, 1), repeat=2),
        itertools.product((0, 1, 24), repeat=2),
        range(4),
    ):
        first = Observation(
            serial=0,
            time=times[0],
            name=0,
            area=areas[0],
            identifier=0,
        )
        second = Observation(
            serial=1,
            time=times[1],
            name=1 if identity == 0 else 0,
            area=areas[1],
            identifier=1 if identity == 1 else 0,
            logged=(2, 0)
            if identity == LOCAL_IDENTITY
            else ((1, 0) if identity == NAMED_IDENTITY else None),
        )
        result.append((first, second))
    for areas, names, kind in itertools.product(
        itertools.product((0, 8, 24), repeat=3),
        ((0, 1, 0), (0, 0, 0)),
        range(3),
    ):
        history = tuple(
            Observation(
                serial=index,
                time=(-WINDOW, -1, 0)[index],
                name=names[index],
                area=area,
                logged=(kind, 0),
            )
            for index, area in enumerate(areas)
        )
        result.extend(itertools.permutations(history))
    return tuple(result)


def compare_histories(histories: tuple[tuple[Observation, ...], ...]) -> int:
    """Check real quantity comparisons and the entire serialized selected record.

    Args:
        histories: Complete retained input records before sorting or identity selection.

    Returns:
        Number of histories whose selected rows and actual baselines matched Lean.
    """
    expected = tests.formal.helpers.oracle.evaluate(
        [
            f"snapshot 0 {WINDOW}" + "".join(f" {row.text()}" for row in history)
            for history in histories
        ],
        executable="oraclePresentationFlow",
    )
    for history, answer in zip(histories, expected, strict=True):
        records = tuple(row.record() for row in history)
        original = {record.batch_id: record for record in records}
        snapshot = peri_scribe.updates.snapshot_from_entries(iter(records), NOW)
        observed = []
        for update in snapshot.updates:
            assert update.batch_id is not None
            observed.extend((
                int(update.batch_id),
                -1
                if update.previous_mapped_area is None
                else int(update.previous_mapped_area.value * 8),
            ))
            assert (
                update.model_dump(exclude={"previous_mapped_area", "history_identity"})
                == original[update.batch_id].model_dump()
            )
            assert update.history_identity is None
        assert tuple(observed) == answer, history
        assert snapshot.generated_at == NOW
        assert (
            peri_scribe.updates.Snapshot.model_validate_json(
                snapshot.model_dump_json(),
            )
            == snapshot
        )
    return len(histories)


def retained_snapshot(
    directory: pathlib.Path,
) -> tuple[peri_scribe.updates.Update, ...]:
    """Carry rotated plain and compressed logs into the actual snapshot serializer.

    Args:
        directory: Temporary year directory containing both retained log formats.

    Returns:
        Verified selected updates for the browser bridge to render unchanged.
    """
    history = (
        Observation(serial=0, time=-WINDOW - 1, name=0, area=80, identifier=0),
        Observation(serial=1, time=-3_600_000, name=1, area=16, identifier=0),
        Observation(serial=2, time=-1, name=1, area=0, identifier=0),
        Observation(serial=3, time=-1, name=0, area=8, logged=(2, 0)),
        Observation(serial=4, time=1, name=1, area=160, identifier=0),
    )
    compare_histories((history,))
    logs = directory / "logs"
    logs.mkdir()
    (logs / "2026-08-fire-updates.jsonl.zst").write_bytes(
        compression.zstd.compress(
            (history[0].record().model_dump_json() + "\n").encode(),
        ),
    )
    (logs / "2026-09-fire-updates.jsonl").write_text(
        "\n".join(row.record().model_dump_json() for row in reversed(history[1:]))
        + "\n",
        encoding="utf-8",
    )
    result = peri_scribe.updates.snapshot_from_entries(
        peri_scribe.updates.read_entries(directory),
        NOW,
    )
    expected = peri_scribe.updates.snapshot_from_entries(
        [row.record() for row in (history[0], *reversed(history[1:]))],
        NOW,
    )
    assert result == expected
    return result.updates


def signature(record: peri_scribe.updates.Update) -> str:
    """Define displayed record equality independently of unrendered batch metadata.

    Args:
        record: A serialized snapshot row accepted by the production viewer.

    Returns:
        Complete visible-record signature used solely to assign equality tokens.
    """
    return json.dumps((
        record.history_identity or record.identity(),
        record.identifier,
        record.name,
        record.location,
        record.timestamp.timestamp(),
        record.mapped_area.value,
        None
        if record.previous_mapped_area is None
        else record.previous_mapped_area.value,
    ))


@dataclasses.dataclass(frozen=True, kw_only=True)
class Step:
    """Exercise state retained across refreshes and ordinary browser controls."""

    records: tuple[peri_scribe.updates.Update, ...]
    query: str = ""
    name_order: tuple[bool, ...] = (False,) * 5
    collapsed: tuple[bool, ...] = (False,) * 5
    elapsed: int = 0
    timer: bool = False


def browser_commands(steps: tuple[Step, ...]) -> list[str]:
    """Keep signature and identity tokens local to one independent browser document.

    Args:
        steps: Consecutive full snapshots and control states to replay in one document.

    Returns:
        Occurrence matching and complete bucket requests for every document state.
    """
    keys: dict[tuple[str, str], int] = {}
    signatures: dict[str, int] = {}
    previous: tuple[peri_scribe.updates.Update, ...] = ()
    commands = []
    for step in steps:
        for record in (*previous, *step.records):
            keys.setdefault(record.history_identity or record.identity(), len(keys))
            signatures.setdefault(signature(record), len(signatures))
        old = " ".join(
            f"{signatures[signature(record)]},{index}"
            for index, record in enumerate(previous)
        )
        new = " ".join(str(signatures[signature(record)]) for record in step.records)
        commands.append(f"reuse {old} -- {new}".replace("  ", " ").strip())
        rows = []
        for index, record in enumerate(step.records):
            age = round((NOW - record.timestamp).total_seconds() * 1000) + step.elapsed
            owner = keys[record.history_identity or record.identity()]
            matching = int(step.query.lower() in record.name.lower())
            rank = NAME_ORDER[NAMES.index(record.name)]
            rows.append(f"{index},0,{owner},{rank},{age},{matching}")
        commands.extend(
            f"group {index} {int(step.name_order[index])}"
            + "".join(f" {row}" for row in rows)
            for index in range(5)
        )
        previous = step.records
    return commands


def browser_cases(cases: tuple[tuple[Step, ...], ...]) -> list[list[dict[str, object]]]:
    """Batch checked browser decisions while retaining independent document histories.

    Args:
        cases: Complete consecutive snapshots and control states for each document.

    Returns:
        Transports with expected reuse indices, exact row order, and identity counts.
    """
    expected = tests.formal.helpers.oracle.evaluate_batches(
        [browser_commands(steps) for steps in cases],
        executable="oraclePresentationFlow",
    )
    return list(map(browser_transport, cases, expected, strict=True))


def browser_case(steps: tuple[Step, ...]) -> list[dict[str, object]]:
    """Retain the same checked transport for scenarios with one browser document.

    Args:
        steps: Consecutive full snapshots and control states to replay in one document.

    Returns:
        Transport with expected reuse indices, exact row order, and identity counts.
    """
    return browser_cases((steps,))[0]


def browser_transport(
    steps: tuple[Step, ...],
    expected: list[tuple[int, ...]],
) -> list[dict[str, object]]:
    """Attach actual compiled decisions to the full unmodified browser input records.

    Args:
        steps: The document's consecutive snapshots and control states.
        expected: Complete ordered reuse and grouping answers for those states.

    Returns:
        One browser replay state for each checked input step.
    """
    answers = iter(expected)
    result: list[dict[str, object]] = []
    for step in steps:
        reuse = next(answers)
        result.append({
            "records": [record.model_dump(mode="json") for record in step.records],
            "query": step.query,
            "nameOrder": step.name_order,
            "collapsed": step.collapsed,
            "elapsed": step.elapsed,
            "timer": step.timer,
            "reuse": reuse[1::2],
            "groups": [next(answers) for _ in range(5)],
        })
    return result


def projection_steps(
    identities: tuple[peri_scribe.updates.HistoryIdentity, ...],
    owners: tuple[int | None, ...],
    projected: tuple[int, ...],
) -> tuple[Step, ...]:
    """Pass oracle-checked current ownership into the shipped viewer's full adapter.

    Args:
        identities: Three distinct typed bucket identities represented by oracle tokens.
        owners: Partial one-hop ownership assignments, including chains and cycles.
        projected: Ordered owner/event token pairs returned by IdentityTransfer.

    Returns:
        Independent, projected, and restored snapshots with immutable evidence checked.
    """
    entries = tuple(
        Observation(
            serial=index,
            time=-age * 60_000,
            name=index % len(identities),
            area=(index + 1) * 8,
        )
        .record()
        .model_copy(update={"log_identity": identities[index % len(identities)]})
        for index, age in enumerate((80, 75, 70, 30, 20, 10))
    )
    original = peri_scribe.updates.snapshot_from_entries(entries, NOW).updates
    snapshot = peri_scribe.updates.snapshot_from_entries(
        entries,
        NOW,
        owners={
            json.dumps(identities[bucket]): json.dumps(identities[owner])
            for bucket, owner in enumerate(owners)
            if owner is not None
        },
    )
    assert projected[1::2] == tuple(range(len(entries)))
    assert len(snapshot.updates) == len(entries)
    for entry, update, owner in zip(
        entries,
        snapshot.updates,
        projected[::2],
        strict=True,
    ):
        assert (update.history_identity or update.identity()) == identities[owner]
        assert (
            update.model_dump(
                exclude={"history_identity", "previous_mapped_area"},
            )
            == entry.model_dump()
        )
    return (
        Step(records=original),
        Step(records=snapshot.updates),
        Step(records=original),
    )


def ownership_cases() -> list[list[dict[str, object]]]:
    """Compose checked one-hop ownership with observed DOM counts, order, and reuse.

    Returns:
        Every partial map over three buckets for four typed identity layouts.
    """
    assignments = tuple(itertools.product((None, 0, 1, 2), repeat=3))
    layouts: tuple[tuple[peri_scribe.updates.HistoryIdentity, ...], ...] = (
        tuple(("id", str(index)) for index in range(3)),
        tuple(("name", str(index)) for index in range(3)),
        tuple(("local", str(index)) for index in range(3)),
        (("id", "same"), ("name", "same"), ("local", "same")),
    )
    projected = tests.formal.helpers.oracle.evaluate(
        [
            "|".join((
                "project",
                " ".join(
                    f"{bucket},{owner}"
                    for bucket, owner in enumerate(owners)
                    if owner is not None
                ),
                " ".join(f"{index % 3},{index}" for index in range(6)),
            ))
            for owners in assignments
        ],
        executable="oracleIdentityTransfer",
    )
    return browser_cases(
        tuple(
            projection_steps(identities, owners, expected)
            for identities in layouts
            for owners, expected in zip(assignments, projected, strict=True)
        ),
    )


def run_browser(cases: list[list[dict[str, object]]]) -> int:
    """Use the shipped inline viewer against the existing full DOM double.

    Args:
        cases: Oracle-backed snapshot and interaction traces.

    Returns:
        Number of independently asserted display states.
    """
    node = shutil.which("node")
    assert node is not None, "Run mise formal-conformance to provide Node"
    result = tests.formal.helpers.process.run(
        [node, str(pathlib.Path(__file__).with_suffix(".mjs"))],
        standard_input=json.dumps(cases),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    count = sum(map(len, cases))
    assert json.loads(result.stdout) == {"checked": count}
    return count
