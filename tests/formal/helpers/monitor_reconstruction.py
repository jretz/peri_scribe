"""Real monitor reducers replay the checked run, phase and retention policies."""

from __future__ import annotations

import dataclasses
import itertools
import typing

import peri_scribe.monitor.model
import peri_scribe.phases
import tests.formal.helpers.oracle


if typing.TYPE_CHECKING:
    import pytest


KINDS = (
    "Starting command",
    "Starting phase",
    "Finished phase",
    "Finished command",
    "ordinary",
    "Skipped phases",
    "Planned phases",
)
STATUSES = tuple(peri_scribe.monitor.model.Status)
SEGMENTS = (
    peri_scribe.phases.Segment(phase="fetch"),
    peri_scribe.phases.Segment(phase="collect-feed", branch="first"),
    peri_scribe.phases.Segment(phase="collect-feed", branch="second"),
    peri_scribe.phases.Segment(phase="query-features"),
    peri_scribe.phases.Segment(phase="geography"),
)


@dataclasses.dataclass(frozen=True, kw_only=True)
class Input:
    """The same event description supplies Python records and Lean protocol fields."""

    owner: int
    kind: int
    failed: bool = False
    explicit: tuple[int, ...] | None = None
    phase: int | None = None

    def encoded(self) -> str:
        """Keep optional context distinct from an explicitly empty path.

        Returns:
            The executable model's event representation.
        """
        return ",".join([
            str(self.owner),
            str(self.kind),
            str(int(self.failed)),
            "-" if self.explicit is None else path_text(self.explicit),
            "-" if self.phase is None else str(self.phase),
        ])

    def record(self) -> dict[str, object]:
        """Construct genuine structured records consumed by the monitor.

        Returns:
            A scoped event with optional explicit or inferred phase metadata.
        """
        fields: dict[str, object] = {
            "run_id": str(self.owner),
            "event": KINDS[self.kind],
            "status": "failed" if self.failed else "success",
            "command": "check",
        }
        if self.explicit is not None:
            fields["phase_segments"] = [
                dataclasses.asdict(SEGMENTS[index]) for index in self.explicit
            ]
        if self.phase is not None:
            fields["phase"] = SEGMENTS[self.phase].phase
            fields["feed"] = SEGMENTS[self.phase].branch
        return fields


def path_text(path: tuple[int, ...]) -> str:
    """Represent an empty path independently from missing explicit path metadata.

    Args:
        path: Segment identities preserving same-phase branches.

    Returns:
        The oracle's path token.
    """
    return ":".join(map(str, path)) or "_"


def histories() -> list[tuple[Input, ...]]:
    """Cover arbitrary short interleavings and longer complete nested commands.

    Returns:
        Scoped histories with explicit paths, inferred context and failed completions.
    """
    alphabet = (
        Input(owner=0, kind=0),
        Input(owner=1, kind=0),
        Input(owner=0, kind=1, phase=1),
        Input(owner=1, kind=1, phase=2),
        Input(owner=0, kind=2, phase=1),
        Input(owner=1, kind=2, phase=2, failed=True),
        Input(owner=0, kind=4, explicit=(0, 1, 3)),
        Input(owner=1, kind=3),
    )
    result = list(itertools.product(alphabet, repeat=3))
    for failure, branches in itertools.product((False, True), ((1, 2), (2, 1))):
        first = (
            Input(owner=0, kind=0),
            Input(owner=0, kind=1, explicit=(0, branches[0])),
            Input(owner=0, kind=2, phase=branches[0], failed=failure),
            Input(owner=0, kind=3, failed=failure),
        )
        second = (
            Input(owner=1, kind=0),
            Input(owner=1, kind=1, explicit=(0, branches[1])),
            Input(owner=1, kind=2, phase=branches[1], failed=not failure),
            Input(owner=1, kind=3, failed=not failure),
        )
        for positions in itertools.combinations(range(8), 4):
            first_iterator = iter(first)
            second_iterator = iter(second)
            result.append(
                tuple(
                    next(first_iterator)
                    if index in positions
                    else next(second_iterator)
                    for index in range(8)
                ),
            )
    return result


def decode_paths(values: tuple[int, ...]) -> list[tuple[int, ...]]:
    """Preserve order and empty paths in the Lean variable-length path response.

    Args:
        values: Concatenated length-prefixed paths.

    Returns:
        One path for every supplied record.
    """
    result = []
    index = 0
    while index < len(values):
        length = values[index]
        result.append(values[index + 1 : index + 1 + length])
        index += length + 1
    assert index == len(values)
    return result


def segment_indexes(path: peri_scribe.phases.Path) -> tuple[int, ...]:
    """Keep branch identity when comparing actual monitor paths with the model.

    Args:
        path: The monitor's resolved phase instance path.

    Returns:
        Abstract segment identifiers.
    """
    return tuple(SEGMENTS.index(segment) for segment in path)


def encoded_observation(event: Input, path: tuple[int, ...]) -> str:
    """Use the proved context result as input to the phase-evidence policy.

    Args:
        event: The incoming event classification.
        path: Its Lean-resolved phase instance.

    Returns:
        An executable phase-observation token.
    """
    return f"{event.kind},{path_text(path)},{int(event.failed)}"


def replay_history(
    events: tuple[Input, ...],
    responses: list[tuple[int, ...]],
) -> tuple[list[str], list[int]]:
    """Compare one scoped history before submitting its phase observations to Lean.

    Args:
        events: Complete scoped records in observed order.
        responses: Two final run states and every model-resolved event path.

    Returns:
        Phase-policy requests and corresponding actual displayed statuses.
    """
    phase_commands: list[str] = []
    actual_phases: list[int] = []
    state = peri_scribe.monitor.model.append_records(
        peri_scribe.monitor.model.State(),
        tuple(event.record() for event in events),
        bounded=False,
    )
    streamed = peri_scribe.monitor.model.State()
    for event in events:
        streamed = peri_scribe.monitor.model.append_records(
            streamed,
            (event.record(),),
            bounded=False,
        )
    assert state == streamed
    paths = decode_paths(responses[2])
    assert len(paths) == len(events)
    for run in state.runs:
        owner = int(run.identifier)
        expected = responses[owner]
        assert STATUSES.index(run.status) == expected[0]
        assert segment_indexes(run.open_path) == expected[2:]
        owned = [
            (event, path)
            for event, path in zip(events, paths, strict=True)
            if event.owner == owner
        ]
        assert [segment_indexes(event.path) for event in run.events] == [
            path for _, path in owned
        ]
        observations = " ".join(itertools.starmap(encoded_observation, owned))
        tree = peri_scribe.monitor.model.phase_tree(
            run,
            peri_scribe.phases.Branches(),
        )
        assert not tree.omissions
        for phase in tree.phases:
            selected = path_text(segment_indexes(phase.path))
            phase_commands.append(f"phase {expected[0]} {selected} {observations}")
            actual_phases.append(STATUSES.index(phase.status))
    return phase_commands, actual_phases


def replay_histories() -> None:
    """Compare run correlation, every event scope and complete observed phase trees."""
    cases = histories()
    commands = []
    for events in cases:
        suffix = " ".join(event.encoded() for event in events)
        commands.extend([f"runs 0 {suffix}", f"runs 1 {suffix}", f"paths {suffix}"])
    responses = tests.formal.helpers.oracle.evaluate(
        commands,
        executable="oracleObservers",
    )
    phase_commands = []
    actual_phases = []
    for index, events in enumerate(cases):
        commands, actual = replay_history(events, responses[index * 3 : index * 3 + 3])
        phase_commands.extend(commands)
        actual_phases.extend(actual)
    phase_responses = tests.formal.helpers.oracle.evaluate(
        phase_commands,
        executable="oracleObservers",
    )
    assert actual_phases == [response[1] for response in phase_responses]


def omission_code(reason: str) -> int:
    """Normalize explanations by their evidence, leaving prose outside the formal claim.

    Args:
        reason: The monitor's explanation for an unentered branch.

    Returns:
        The formal omission category.
    """
    if not reason:
        return 0
    if reason == "explicit control":
        return 1
    if reason == "Not reached: command failed":
        return 2
    if reason == "No start recorded before command completed":
        return 3
    return 4 if reason.endswith("completed") else 5


def replay_omissions() -> None:
    """Compare every run/ancestor combination and explicit-decision precedence."""
    cases = list(itertools.product(range(5), (False, True), range(5), range(5)))
    expected = tests.formal.helpers.oracle.evaluate(
        [
            f"omission {run} {int(explicit)} {first} {second}"
            for run, explicit, first, second in cases
        ],
        executable="oracleObservers",
    )
    selected = SEGMENTS[:3]
    for (run, explicit, first, second), outcome in zip(cases, expected, strict=True):
        parents: dict[peri_scribe.phases.Path, peri_scribe.monitor.model.PhaseView] = {
            selected[:1]: peri_scribe.monitor.model.PhaseView(
                path=selected[:1],
                status=STATUSES[first],
            ),
            selected[:2]: peri_scribe.monitor.model.PhaseView(
                path=selected[:2],
                status=STATUSES[second],
            ),
        }
        reason = peri_scribe.monitor.model.omission_reason(
            selected,
            parents,
            peri_scribe.monitor.model.Run(identifier="0", status=STATUSES[run]),
            {selected[:1]: "explicit control"} if explicit else {},
        )
        assert omission_code(reason) == outcome[0]


def replay_retention(monkeypatch: pytest.MonkeyPatch, limit: int) -> None:
    """Check bounded event windows retain actual structural identities and outcomes.

    Args:
        monkeypatch: Per-test override of the monitor's interactive retention bound.
        limit: Positive ordinary event suffix length.
    """
    events = (
        Input(owner=0, kind=0),
        Input(owner=0, kind=1, explicit=(0, 1)),
        Input(owner=0, kind=4),
        Input(owner=0, kind=2, phase=1),
        Input(owner=0, kind=1, explicit=(0, 2)),
        Input(owner=0, kind=2, phase=2, failed=True),
        *(Input(owner=0, kind=4) for _ in range(8)),
        Input(owner=0, kind=3, failed=True),
    )
    suffix = " ".join(event.encoded() for event in events)
    paths = decode_paths(
        tests.formal.helpers.oracle.evaluate(
            [f"paths {suffix}"],
            executable="oracleObservers",
        )[0],
    )
    observations = " ".join(
        map(encoded_observation, events, paths, strict=True),
    )
    expected = tests.formal.helpers.oracle.evaluate(
        [f"retain {limit} {observations}"],
        executable="oracleObservers",
    )[0]
    monkeypatch.setattr(peri_scribe.monitor.model, "MAXIMUM_EVENTS_PER_RUN", limit)
    records = tuple(event.record() for event in events)
    state = peri_scribe.monitor.model.append_records(
        peri_scribe.monitor.model.State(),
        records,
    )
    run = state.runs[0]
    assert len(run.events) <= limit
    actual = tuple(
        value
        for event in peri_scribe.monitor.model.evidence(run)
        for value in (
            KINDS.index(event.message),
            int(event.fields.get("status") == "failed"),
            len(event.path),
            *segment_indexes(event.path),
        )
    )
    assert actual == expected
    full = peri_scribe.monitor.model.append_records(
        peri_scribe.monitor.model.State(),
        records,
        bounded=False,
    ).runs[0]
    assert peri_scribe.monitor.model.phase_tree(run, peri_scribe.phases.Branches()) == (
        peri_scribe.monitor.model.phase_tree(full, peri_scribe.phases.Branches())
    )


def replay_run_retention(monkeypatch: pytest.MonkeyPatch, limit: int) -> None:
    """Bounded runs retain insertion order and require archives for evicted history.

    Args:
        monkeypatch: Per-test run retention override.
        limit: Positive run count bound.
    """
    monkeypatch.setattr(peri_scribe.monitor.model, "MAXIMUM_RUNS", limit)
    records = tuple(Input(owner=owner, kind=0).record() for owner in range(8))
    state = peri_scribe.monitor.model.append_records(
        peri_scribe.monitor.model.State(),
        records,
    )
    expected = tests.formal.helpers.oracle.evaluate(
        [f"retained-runs {limit} " + " ".join(map(str, range(8)))],
        executable="oracleObservers",
    )[0]
    assert tuple(int(run.identifier) for run in state.runs) == expected


def planned_records(
    *,
    completed: bool,
    failed: bool,
    explicit_skip: bool,
) -> tuple[dict[str, object], ...]:
    """Vary missing branches independently of observed parent and command completion.

    Args:
        completed: Whether the command and its geography phase have ended.
        failed: Whether those completions recorded failure.
        explicit_skip: Whether an unentered child has its own explicit skip evidence.

    Returns:
        Ordinary structured records for the actual configured pipeline catalogue.
    """
    records: list[dict[str, object]] = [
        {"event": "Starting command", "run_id": "0", "command": "run"},
        {"event": "Starting phase", "run_id": "0", "phase_path": "geography"},
    ]
    if explicit_skip:
        records.append({
            "event": "Skipped phases",
            "run_id": "0",
            "phase_path": "geography",
            "phases": ["full-history"],
            "reason": "explicit control",
        })
    if completed:
        records.extend([
            {
                "event": "Finished phase",
                "run_id": "0",
                "phase_path": "geography",
                "status": "failed" if failed else "success",
            },
            {
                "event": "Finished command",
                "run_id": "0",
                "status": "failed" if failed else "success",
            },
        ])
    return tuple(records)


def expected_planned_tree(
    run: peri_scribe.monitor.model.Run,
    *,
    explicit_skip: bool,
) -> tuple[dict[peri_scribe.phases.Path, int], dict[peri_scribe.phases.Path, int]]:
    """Compose proved observation and omission policies over the real catalogue input.

    Args:
        run: A run whose input records have already passed through the real reducer.
        explicit_skip: The independent scenario's declaration of an explicit child skip.

    Returns:
        Expected visible phase statuses and topmost omitted branch categories.
    """
    planned = peri_scribe.phases.planned_paths(
        peri_scribe.phases.Branches(),
        gated=False,
    )
    segments = tuple(dict.fromkeys(segment for path in planned for segment in path))
    encoded = {
        path: path_text(tuple(segments.index(segment) for segment in path))
        for path in planned
    }
    observations = " ".join(
        f"{KINDS.index(event.message)},{encoded.get(event.path, '_')},"
        f"{int(event.fields.get('status') == 'failed')}"
        for event in run.events
    )
    run_status = STATUSES.index(run.status)
    phase_states = tests.formal.helpers.oracle.evaluate(
        [f"phase {run_status} {encoded[path]} {observations}" for path in planned],
        executable="oracleObservers",
    )
    phases = dict(zip(planned, phase_states, strict=True))
    commands = []
    for path in planned:
        skipped = (
            explicit_skip
            and len(path) > 1
            and (path[0].phase == "geography" and path[1].phase == "full-history")
        )
        parents = " ".join(
            str(phases[path[:index]][0]) for index in range(1, len(path))
        )
        suffix = f" {parents}" if parents else ""
        commands.append(f"omission {run_status} {int(skipped)}{suffix}")
    omitted = tests.formal.helpers.oracle.evaluate(
        commands,
        executable="oracleObservers",
    )
    visible = {}
    omissions = {}
    for path, omission in zip(planned, omitted, strict=True):
        if any(path[: len(parent)] == parent for parent in omissions):
            continue
        if phases[path][0] == 0 and omission[0]:
            omissions[path] = omission[0]
        else:
            visible[path] = phases[path][1]
    return visible, omissions


def replay_planned_trees() -> None:
    """Require the complete real phase tree to preserve explicit skip provenance."""
    for completed, failed, skipped in itertools.product((False, True), repeat=3):
        run = peri_scribe.monitor.model.append_records(
            peri_scribe.monitor.model.State(),
            planned_records(completed=completed, failed=failed, explicit_skip=skipped),
            bounded=False,
        ).runs[0]
        expected, omissions = expected_planned_tree(run, explicit_skip=skipped)
        actual = peri_scribe.monitor.model.phase_tree(
            run,
            peri_scribe.phases.Branches(),
        )
        assert {
            phase.path: STATUSES.index(phase.status) for phase in actual.phases
        } == expected
        assert {
            omission.path: omission_code(omission.reason)
            for omission in actual.omissions
        } == omissions
