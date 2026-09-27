"""Replay each checked validation path through real journals, logs, and snapshots."""

import collections.abc
import dataclasses
import datetime
import pathlib
import re

import pydantic
import pytest
import time_machine

import peri_scribe.fire_updates
import peri_scribe.logging
import peri_scribe.publication
import peri_scribe.updates
import tests.formal.helpers.tlc
import tests.helpers.factories.peri_scribe.durable_updates


NOW = tests.helpers.factories.peri_scribe.durable_updates.NOW
INITIAL_CASES = 252
type Effect = tuple[str, int]


@dataclasses.dataclass(frozen=True)
class Case:
    """Keep a terminal result attached to its actual initial TLC execution."""

    initial: dict[str, str]
    terminal: dict[str, str]


def cases(directory: pathlib.Path) -> tuple[Case, ...]:
    """Follow the exported edges instead of combining unrelated reachable states.

    Args:
        directory: An isolated location for the complete checked graph.

    Returns:
        One complete execution per distinct initial input combination.
    """
    graph = tests.formal.helpers.tlc.graph(
        "DurableUpdateValidation",
        "DurableUpdateValidation",
        directory,
    )
    result = []
    for initial in graph.initial:
        node = initial
        visited = set()
        while graph.states[node]["phase"] not in {'"done"', '"rejected"'}:
            assert node not in visited
            visited.add(node)
            edges = graph.outgoing[node]
            assert len(edges) == 1
            node = edges[0].target
        result.append(Case(graph.states[initial], graph.states[node]))
    assert len(result) == INITIAL_CASES
    return tuple(result)


def numbers(value: str) -> tuple[int, ...]:
    """Decode a TLC set of generation numbers without interpreting transitions.

    Args:
        value: An exported TLC set.

    Returns:
        Its elements in publication order.
    """
    return tuple(sorted(map(int, re.findall(r"\d+", value))))


def records(generation: int) -> tuple[dict[str, object], ...]:
    """Keep two distinct occurrences so whole-batch append is observable.

    Args:
        generation: The durable publication generation.

    Returns:
        Two raw log payloads whose values distinguish both batch and position.
    """
    return tuple(
        tests.helpers.factories.peri_scribe.durable_updates.record()
        | {
            "name": f"Fire {position}",
            "mapped_area": {"value": generation * 100 + position, "units": "acre"},
        }
        for position in (1, 2)
    )


def entries(generations: tuple[int, ...]) -> tuple[peri_scribe.updates.LogEntry, ...]:
    """Attach independently known completion metadata to the expected occurrences.

    Args:
        generations: Logged generations exported by TLC.

    Returns:
        The exact immutable records required after replay.
    """
    return tuple(
        peri_scribe.updates.LogEntry.model_validate(
            record
            | {
                "timestamp": NOW - datetime.timedelta(seconds=2 - generation),
                "batch_id": f"batch-{generation}",
            },
        )
        for generation in generations
        for record in records(generation)
    )


def seed(case: Case, directory: pathlib.Path) -> None:
    """Install raw invalid evidence without letting setup validation erase the case.

    Args:
        case: The checked initial durable inputs.
        directory: An isolated real year directory.
    """
    for kind, path, valid in (
        (
            "checkpointKind",
            peri_scribe.fire_updates.state_path(directory),
            tests.helpers.factories.peri_scribe.durable_updates.state(0).model_dump(
                mode="json",
            ),
        ),
        (
            "journalKind",
            peri_scribe.fire_updates.pending_path(directory),
            {
                "records": records(1) if case.initial["hasRecords"] == "TRUE" else (),
                "state": tests.helpers.factories.peri_scribe.durable_updates.state(
                    1,
                ).model_dump(mode="json"),
                "timestamp": (NOW - datetime.timedelta(seconds=1)).isoformat(),
                "batch_id": "batch-1",
            },
        ),
    ):
        if case.initial[kind] != '"missing"':
            tests.helpers.factories.peri_scribe.durable_updates.write(
                path,
                valid if case.initial[kind] == '"valid"' else b"{",
            )
    original = entries(numbers(case.initial["logged"]))
    if original:
        path = directory / "logs" / "2026-09-fire-updates.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(entry.model_dump_json() + "\n" for entry in original))


def generation(state: peri_scribe.fire_updates.State) -> int:
    """Read the opaque evidence marker used only by these filesystem fixtures.

    Args:
        state: The actual checkpoint about to be written.

    Returns:
        Its independently encoded publication generation.
    """
    (marker,) = state.perimeters[
        tests.helpers.factories.peri_scribe.durable_updates.IDENTITY
    ]
    return int(marker.removeprefix("generation-"))


def observe(
    monkeypatch: pytest.MonkeyPatch,
    directory: pathlib.Path,
    effects: list[Effect],
) -> None:
    """Observe completed real operations; no persistence or validation is replaced.

    Args:
        monkeypatch: Scope of the pass-through observation wrappers.
        directory: The isolated year whose journal retirement matters.
        effects: Completed durable boundaries in their actual order.
    """
    append = peri_scribe.logging.append_monthly_records
    write = peri_scribe.publication.write_state
    unlink = pathlib.Path.unlink

    def append_records(
        path: pathlib.Path,
        payloads: collections.abc.Iterable[collections.abc.Mapping[str, object]],
        *,
        suffix: str = "",
        timestamp: datetime.datetime | None = None,
        batch_id: str | None = None,
    ) -> None:
        append(path, payloads, suffix=suffix, timestamp=timestamp, batch_id=batch_id)
        effects.append(
            ("rotate", 0) if batch_id is None else ("append", int(batch_id[-1])),
        )

    def write_state(path: pathlib.Path, document: pydantic.BaseModel) -> None:
        write(path, document)
        match document:
            case peri_scribe.fire_updates.PendingUpdates():
                effects.append(("publish", generation(document.state)))
            case peri_scribe.fire_updates.State():
                effects.append(("acknowledge", generation(document)))
            case peri_scribe.updates.Snapshot():
                effects.append(("view", 0))
            case _:
                raise AssertionError(type(document))

    def remove(path: pathlib.Path, *, missing_ok: bool = False) -> None:
        pending = (
            peri_scribe.fire_updates.PendingUpdates.model_validate_json(
                path.read_bytes(),
            )
            if path == peri_scribe.fire_updates.pending_path(directory)
            else None
        )
        unlink(path, missing_ok=missing_ok)
        if pending is not None:
            effects.append(("retire", generation(pending.state)))

    monkeypatch.setattr(peri_scribe.logging, "append_monthly_records", append_records)
    monkeypatch.setattr(peri_scribe.publication, "write_state", write_state)
    monkeypatch.setattr(pathlib.Path, "unlink", remove)
    monkeypatch.setattr(peri_scribe.fire_updates.uuid, "uuid4", lambda: "batch-2")


def invoke(case: Case, directory: pathlib.Path) -> None:
    """Call the actual owner for this checked input and equality branch.

    Args:
        case: A single exported input combination.
        directory: The seeded real publication directory.

    Raises:
        AssertionError: The exported operation is outside the checked domain.
    """
    match case.initial["operation"]:
        case '"recover"':
            peri_scribe.fire_updates.recover_updates(directory)
        case '"view"':
            peri_scribe.updates.write_updates_page(directory)
        case '"write"':
            current = 1 if case.initial["journalKind"] == '"valid"' else 0
            payloads = records(2) if case.initial["hasRecords"] == "TRUE" else ()
            peri_scribe.fire_updates.write_updates(
                directory,
                peri_scribe.fire_updates.PreparedUpdates(
                    records=({},)
                    if case.initial["requestKind"] == '"invalid"'
                    else payloads,
                    state=tests.helpers.factories.peri_scribe.durable_updates.state(
                        current if case.initial["same"] == "TRUE" else 2,
                    ),
                ),
            )
        case _:
            raise AssertionError(case.initial["operation"])


def replay(case: Case, directory: pathlib.Path) -> None:
    """Compare exact side effects, retained bytes, and complete final log payloads.

    Args:
        case: A checked initial-to-terminal path from the actual TLC graph.
        directory: An isolated real filesystem publication directory.
    """
    seed(case, directory)
    before = tests.helpers.factories.peri_scribe.durable_updates.contents(directory)
    effects: list[Effect] = []
    with (
        pytest.MonkeyPatch.context() as monkeypatch,
        time_machine.travel(NOW, tick=False),
    ):
        observe(monkeypatch, directory, effects)
        if case.terminal["phase"] == '"rejected"':
            with pytest.raises(pydantic.ValidationError):
                invoke(case, directory)
            assert (
                tests.helpers.factories.peri_scribe.durable_updates.contents(directory)
                == before
            )
        else:
            invoke(case, directory)
    expected = tuple(
        (action, int(value))
        for action, value in re.findall(r'<<"(\w+)", (\d+)>>', case.terminal["effects"])
    )
    assert tuple(effects) == expected, (case, effects)
    assert peri_scribe.updates.read_entries(directory) == entries(
        numbers(case.terminal["logged"]),
    )
    if case.terminal["phase"] == '"rejected"':
        return
    checkpoint = int(case.terminal["checkpoint"])
    actual = peri_scribe.fire_updates.read_authoritative(
        peri_scribe.fire_updates.state_path(directory),
        peri_scribe.fire_updates.State,
    )
    expected_state = (
        tests.helpers.factories.peri_scribe.durable_updates.state(checkpoint)
        if checkpoint or case.initial["checkpointKind"] == '"valid"'
        else None
    )
    assert actual == expected_state
    journal = peri_scribe.fire_updates.pending_path(directory)
    assert journal.exists() == (
        case.initial["journalKind"] != '"missing"'
        if case.initial["operation"] == '"view"'
        else False
    )
    if case.initial["operation"] == '"view"':
        if journal.exists():
            assert journal.read_bytes() == before[journal.relative_to(directory)]
        snapshot = peri_scribe.updates.Snapshot.model_validate_json(
            (directory / "maps" / "updates.json").read_bytes(),
        )
        assert snapshot.generated_at == NOW
        assert len(snapshot.updates) == len(entries(numbers(case.terminal["logged"])))
        assert (directory / "maps" / "updates.html").is_file()
