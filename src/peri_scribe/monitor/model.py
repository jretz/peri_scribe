"""Immutable run and phase projections shared by terminal and future web consumers.

Algorithm reasoning and contracts:
[Monitor evidence](../../../docs/algorithms/monitor-evidence.md)
"""

import collections.abc
import dataclasses
import datetime
import enum
import functools
import json
import typing

import pint

import peri_scribe.monitor.events
import peri_scribe.phases
import peri_scribe.pipeline_stages
from measurement_units import units


MAXIMUM_RUNS = 100
MAXIMUM_EVENTS_PER_RUN = 10000
PROGRESS_MESSAGES = {
    "Starting command",
    "Finished command",
    "Starting phase",
    "Finished phase",
    "Planned phases",
    "Skipped phases",
    "Another run owns this year; skipping invocation",
}


class Status(enum.StrEnum):
    """The evidence in the log determines status without claiming process liveness."""

    WAITING = "waiting"
    ACTIVE = "open"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "unfinished"


@dataclasses.dataclass(frozen=True, kw_only=True)
class Run:
    """One command's records remain independent even when commands overlap."""

    identifier: str
    command: str = "unattributed"
    events: tuple[peri_scribe.monitor.events.Event, ...] = ()
    progress: tuple[peri_scribe.monitor.events.Event, ...] = ()
    open_path: peri_scribe.phases.Path = ()
    status: Status = Status.ACTIVE

    @functools.cached_property
    def last_timestamp(self) -> datetime.datetime:
        """Reuse the latest observation while this immutable event tuple survives."""
        return max(
            (event.timestamp for event in self.events if event.timestamp),
            default=datetime.datetime.min.replace(tzinfo=datetime.UTC),
        )


@dataclasses.dataclass(frozen=True, kw_only=True)
class State:
    """A bounded stream can be replaced atomically by any presentation adapter."""

    runs: tuple[Run, ...] = ()
    sequence: int = 0
    unscoped_run: str = "unattributed"


@dataclasses.dataclass(frozen=True, kw_only=True)
class PhaseState:
    """Pending, observed, and completed work share a presentation-neutral identity."""

    path: peri_scribe.phases.Path
    status: Status = Status.WAITING
    duration: pint.Quantity = dataclasses.field(
        default_factory=lambda: 0 * units.seconds,
    )
    started_at: datetime.datetime | None = None


@dataclasses.dataclass(frozen=True, kw_only=True)
class Omission:
    """A trimmed branch retains its identity and the evidence for its removal."""

    path: peri_scribe.phases.Path
    reason: str


@dataclasses.dataclass(frozen=True, kw_only=True)
class PhaseTree:
    """A hierarchy retains phase states, omissions, and their evidence-based reasons."""

    phases: tuple[PhaseState, ...]
    omissions: tuple[Omission, ...] = ()
    reasons: tuple[str, ...] = ()


@dataclasses.dataclass(kw_only=True, slots=True)
class PendingRun:
    """Batch-local mutable work never changes a published immutable run."""

    original: Run
    command: str
    open_path: peri_scribe.phases.Path
    status: Status
    events: list[peri_scribe.monitor.events.Event] = dataclasses.field(
        default_factory=list,
    )
    progress: list[peri_scribe.monitor.events.Event] = dataclasses.field(
        default_factory=list,
    )


def reduce_record(
    pending: PendingRun,
    fields: dict[str, object],
    sequence: int,
) -> None:
    """Keep each record's phase context local to its owning batch accumulator.

    Args:
        pending: Private unpublished work for the record's run.
        fields: The complete original fields.
        sequence: The record's stable global observation position.
    """
    event = peri_scribe.monitor.events.make_event(fields, sequence, pending.open_path)
    message = event.message
    if message == "Starting command":
        pending.command = str(fields.get("command", "unknown"))
        pending.open_path = ()
    elif message == "Starting phase":
        pending.open_path = event.path
    elif message == "Finished phase":
        pending.open_path = event.path[:-1]
    elif message == "Finished command":
        pending.status = (
            Status.FAILED if fields.get("status") == "failed" else Status.COMPLETED
        )
        pending.command = str(fields.get("command", pending.command))
        pending.open_path = ()
    pending.events.append(event)
    if message.startswith("Publication gate ") or message in PROGRESS_MESSAGES:
        pending.progress.append(event)


def append_records(
    state: State,
    records: tuple[dict[str, object], ...],
    *,
    bounded: bool = True,
) -> State:
    """Correlate a batch without mutating the state retained by another consumer.

    Args:
        state: The previously published stream state.
        records: Newly completed JSON records in file order.
        bounded: Whether to apply the diagnostic event retention limits.

    Returns:
        Updated bounded run history with stable event sequence numbers.
    """
    runs = {run.identifier: run for run in state.runs}
    pending: dict[str, PendingRun] = {}
    unscoped = state.unscoped_run
    sequence = state.sequence
    for fields in records:
        sequence += 1
        if fields.get("event") == "Starting command" and not fields.get("run_id"):
            unscoped = f"observed-{sequence}"
        identifier = str(fields.get("run_id") or unscoped)
        current = pending.get(identifier)
        if current is None:
            run = runs.get(identifier)
            if run is None:
                run = Run(identifier=identifier)
                runs[identifier] = run
            current = PendingRun(
                original=run,
                command=run.command,
                open_path=run.open_path,
                status=run.status,
            )
            pending[identifier] = current
        reduce_record(current, fields, sequence)
    for identifier, current in pending.items():
        run = current.original
        retained = (*run.events, *current.events)
        runs[identifier] = dataclasses.replace(
            run,
            command=current.command,
            open_path=current.open_path,
            status=current.status,
            events=retained[-MAXIMUM_EVENTS_PER_RUN:] if bounded else retained,
            progress=(*run.progress, *current.progress),
        )
    return State(
        runs=tuple(runs.values())[-MAXIMUM_RUNS:] if bounded else tuple(runs.values()),
        sequence=sequence,
        unscoped_run=unscoped,
    )


def evidence(run: Run) -> tuple[peri_scribe.monitor.events.Event, ...]:
    """Keep phase history complete after verbose event rows leave the retention window.

    Args:
        run: A command with retained log rows and its structural progress records.

    Returns:
        Unique observations in original order, including earlier phase boundaries.
    """
    records = {event.sequence: event for event in (*run.progress, *run.events)}
    return tuple(records[sequence] for sequence in sorted(records))


def plan_for_run(
    run: Run,
    branches: peri_scribe.phases.Branches,
) -> tuple[peri_scribe.phases.Path, ...]:
    """Use the run's recorded configuration when available to reconstruct its plan.

    Args:
        run: The command whose possible work should be shown.
        branches: Current configuration, used when the run did not record a plan.

    Returns:
        Planned phase instances, or an empty plan for other commands.
    """
    if run.command != "run":
        return ()
    gated = any(
        event.path
        and any(
            segment.phase == peri_scribe.phases.Phase.PUBLICATION_GATE
            for segment in event.path
        )
        for event in evidence(run)
    )
    for event in evidence(run):
        parameters = event.fields.get("parameters")
        if (
            isinstance(parameters, dict)
            and parameters.get("publish_threshold") is not None
        ):
            gated = True
        if event.message == "Planned phases":
            gated = bool(event.fields.get("gated"))
            values = event.fields.get("branches")
            if isinstance(values, dict):
                branches = peri_scribe.phases.Branches(
                    feeds=tuple(str(name) for name in values.get("feeds", ())),
                    sources=tuple(str(name) for name in values.get("sources", ())),
                    evacuations=str(values.get("evacuations", "")),
                    cities=str(values.get("cities", "")),
                )
    return peri_scribe.phases.planned_paths(branches, gated=gated)


def recorded_duration(event: peri_scribe.monitor.events.Event) -> pint.Quantity:
    """Reject damaged duration metadata while retaining the event itself.

    Args:
        event: A phase completion record with optional duration metadata.

    Returns:
        A nonnegative duration in seconds, or zero if the metadata is unusable.
    """
    value = event.fields.get("duration")
    if isinstance(value, dict):
        try:
            return typing.cast(
                "pint.Quantity",
                max(
                    0 * units.seconds,
                    units.Quantity(value["value"], value["units"]).to("seconds"),
                ),
            )
        except KeyError, TypeError, ValueError, pint.errors.PintError:
            pass
    return 0 * units.seconds


def omission_reason(
    path: peri_scribe.phases.Path,
    phases: collections.abc.Mapping[peri_scribe.phases.Path, PhaseState],
    run: Run,
    skipped: collections.abc.Mapping[peri_scribe.phases.Path, str],
) -> str:
    """Distinguish an explicit skip decision from merely absent execution records.

    Args:
        path: An unentered planned phase.
        phases: Work already observed in this run.
        run: The command's latest known outcome.
        skipped: Explicitly skipped branches and their reasons.

    Returns:
        The reason for trimming, or an empty string while work remains possible.
    """
    for prefix, reason in skipped.items():
        if path[: len(prefix)] == prefix:
            return reason
    if run.status != Status.ACTIVE:
        return (
            "Not reached: command failed"
            if run.status == Status.FAILED
            else "No start recorded before command completed"
        )
    for index in range(1, len(path)):
        parent = phases.get(path[:index])
        if parent and parent.status in {Status.COMPLETED, Status.FAILED}:
            return f"No start recorded before {parent.path[-1].phase} {parent.status}"
    return ""


def skipped_paths(
    events: tuple[peri_scribe.monitor.events.Event, ...],
    phases: collections.abc.Mapping[peri_scribe.phases.Path, PhaseState],
) -> dict[peri_scribe.phases.Path, str]:
    """Keep explicit execution decisions separate from missing phase observations.

    Args:
        events: The run's retained records.
        phases: Planned and observed phase instances.

    Returns:
        Explicitly skipped paths with their reasons.
    """
    skipped: dict[peri_scribe.phases.Path, str] = {}
    for event in events:
        fields = event.fields
        reason = str(fields.get("reason", ""))
        if event.message == "Skipped phases":
            names = fields.get("phases", [])
            if isinstance(names, list):
                skipped.update({
                    (*event.path, peri_scribe.phases.Segment(phase=str(name))): reason
                    for name in names
                })
        if event.message == "Publication gate skipped":
            for path in phases:
                if path[0].phase != peri_scribe.pipeline_stages.Stage.FETCH or any(
                    segment.phase == peri_scribe.phases.Phase.DEFERRED_FETCH
                    for segment in path
                ):
                    skipped[path] = reason
        selected = fields.get("stages")
        if event.message == "Planned phases" and isinstance(selected, list):
            for path in phases:
                if path[0].phase not in selected:
                    skipped[path] = "Stage not selected"
        if event.message == "Another run owns this year; skipping invocation":
            skipped.update(dict.fromkeys(phases, "Another run owns this year"))
    return skipped


def phase_tree(run: Run, branches: peri_scribe.phases.Branches) -> PhaseTree:
    """Derive the live or final hierarchy entirely from the catalogue and log evidence.

    Args:
        run: The selected command's retained records.
        branches: Source names available before new work starts.

    Returns:
        Visible phase states, trimmed branches, and decision explanations.
    """
    phases = {path: PhaseState(path=path) for path in plan_for_run(run, branches)}
    reasons = [
        f"{event.message}: {event.fields.get('reason', '')}"
        for event in evidence(run)
        if event.message.startswith("Publication gate ")
    ]
    for event in evidence(run):
        fields = event.fields
        for index in range(1, len(event.path) + 1):
            path = event.path[:index]
            current = phases.get(path, PhaseState(path=path))
            if current.status == Status.WAITING:
                phases[path] = dataclasses.replace(
                    current,
                    status=Status.ACTIVE,
                    started_at=event.timestamp,
                )
        if event.message in {"Starting phase", "Finished phase"} and event.path:
            current = phases[event.path]
            status = Status.ACTIVE
            elapsed = current.duration
            if event.message == "Finished phase":
                status = (
                    Status.FAILED
                    if fields.get("status") == "failed"
                    else Status.COMPLETED
                )
                elapsed = current.duration + recorded_duration(event)
            phases[event.path] = dataclasses.replace(
                current,
                status=status,
                duration=elapsed,
                started_at=event.timestamp
                if status == Status.ACTIVE
                else current.started_at,
            )
    skipped = skipped_paths(evidence(run), phases)
    included: list[PhaseState] = []
    omissions: list[Omission] = []
    for path, phase in phases.items():
        if any(path[: len(omitted.path)] == omitted.path for omitted in omissions):
            continue
        reason = (
            omission_reason(path, phases, run, skipped)
            if phase.status == Status.WAITING
            else ""
        )
        if reason:
            omissions.append(Omission(path=path, reason=reason))
        elif run.status != Status.ACTIVE and phase.status == Status.ACTIVE:
            included.append(dataclasses.replace(phase, status=Status.STOPPED))
        else:
            included.append(phase)
    return PhaseTree(
        phases=tuple(included),
        omissions=tuple(omissions),
        reasons=tuple(dict.fromkeys(reasons)),
    )


def filter_events(
    run: Run,
    *,
    minimum_level: str,
    query: str,
    path: peri_scribe.phases.Path = (),
) -> tuple[peri_scribe.monitor.events.Event, ...]:
    """Filter a retained stream without dropping events from the underlying run.

    Args:
        run: The selected run.
        minimum_level: The minimum included severity.
        query: Case-insensitive text matched against every original JSON field.
        path: A selected phase and its descendants, or the entire run.

    Returns:
        Matching events in their original order.
    """
    levels = {"debug": 0, "info": 1, "warning": 2, "error": 3, "critical": 4}
    return tuple(
        event
        for event in run.events
        if event.path[: len(path)] == path
        and levels.get(event.level, 1) >= levels.get(minimum_level, 0)
        and query.casefold()
        in json.dumps(dict(event.fields), ensure_ascii=False).casefold()
    )
