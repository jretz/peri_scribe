"""Immutable run and phase projections shared by terminal and future web consumers."""

import collections.abc
import dataclasses
import datetime
import enum
import json
import typing

import pint

import peri_scribe.monitor.events
import peri_scribe.phases
import peri_scribe.pipeline_stages
from measurement_units import units


MAXIMUM_RUNS = 100
MAXIMUM_EVENTS_PER_RUN = 10000


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


@dataclasses.dataclass(frozen=True, kw_only=True)
class State:
    """A bounded stream can be replaced atomically by any presentation adapter."""

    runs: tuple[Run, ...] = ()
    sequence: int = 0
    unscoped_run: str = "unattributed"


@dataclasses.dataclass(frozen=True, kw_only=True)
class PhaseView:
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
    """A complete tree projection needs no widget or rendering-library objects."""

    phases: tuple[PhaseView, ...]
    omissions: tuple[Omission, ...] = ()
    reasons: tuple[str, ...] = ()


def append_records(
    state: State,
    records: tuple[dict[str, object], ...],
    *,
    bounded: bool = True,
) -> State:
    """Correlate a batch without mutating the state held by a reader or another view.

    Args:
        state: The previously published stream state.
        records: Newly completed JSON records in file order.
        bounded: Whether to apply the interactive log view's retention limits.

    Returns:
        Updated bounded run history with stable event sequence numbers.
    """
    runs = {run.identifier: run for run in state.runs}
    pending: dict[str, list[peri_scribe.monitor.events.Event]] = {}
    unscoped = state.unscoped_run
    sequence = state.sequence
    for fields in records:
        sequence += 1
        if fields.get("event") == "Starting command" and not fields.get("run_id"):
            unscoped = f"observed-{sequence}"
        identifier = str(fields.get("run_id") or unscoped)
        run = runs.get(identifier, Run(identifier=identifier))
        event = peri_scribe.monitor.events.make_event(fields, sequence, run.open_path)
        path = run.open_path
        status = run.status
        command = run.command
        if event.message == "Starting command":
            command = str(fields.get("command", "unknown"))
            path = ()
        elif event.message == "Starting phase":
            path = event.path
        elif event.message == "Finished phase":
            path = event.path[:-1]
        elif event.message == "Finished command":
            status = (
                Status.FAILED if fields.get("status") == "failed" else Status.COMPLETED
            )
            command = str(fields.get("command", command))
            path = ()
        pending.setdefault(identifier, []).append(event)
        runs[identifier] = dataclasses.replace(
            run,
            command=command,
            open_path=path,
            status=status,
        )
    for identifier, events in pending.items():
        run = runs[identifier]
        runs[identifier] = dataclasses.replace(
            run,
            events=(
                (*run.events, *events)[-MAXIMUM_EVENTS_PER_RUN:]
                if bounded
                else (*run.events, *events)
            ),
            progress=(
                *run.progress,
                *(
                    event
                    for event in events
                    if event.message.startswith("Publication gate ")
                    or event.message
                    in {
                        "Starting command",
                        "Finished command",
                        "Starting phase",
                        "Finished phase",
                        "Planned phases",
                        "Skipped phases",
                        "Another run owns this year; skipping invocation",
                    }
                ),
            ),
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
    views: collections.abc.Mapping[peri_scribe.phases.Path, PhaseView],
    run: Run,
    skipped: collections.abc.Mapping[peri_scribe.phases.Path, str],
) -> str:
    """Distinguish an explicit skip decision from merely absent execution records.

    Args:
        path: An unentered planned phase.
        views: Work already observed in this run.
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
        parent = views.get(path[:index])
        if parent and parent.status in {Status.COMPLETED, Status.FAILED}:
            return f"No start recorded before {parent.path[-1].phase} {parent.status}"
    return ""


def skipped_paths(
    events: tuple[peri_scribe.monitor.events.Event, ...],
    views: collections.abc.Mapping[peri_scribe.phases.Path, PhaseView],
) -> dict[peri_scribe.phases.Path, str]:
    """Keep explicit execution decisions separate from missing phase observations.

    Args:
        events: The run's retained records.
        views: Planned and observed phase instances.

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
            for path in views:
                if path[0].phase != peri_scribe.pipeline_stages.Stage.FETCH or any(
                    segment.phase == peri_scribe.phases.Phase.DEFERRED_FETCH
                    for segment in path
                ):
                    skipped[path] = reason
        selected = fields.get("stages")
        if event.message == "Planned phases" and isinstance(selected, list):
            for path in views:
                if path[0].phase not in selected:
                    skipped[path] = "Stage not selected"
        if event.message == "Another run owns this year; skipping invocation":
            skipped.update(dict.fromkeys(views, "Another run owns this year"))
    return skipped


def phase_tree(run: Run, branches: peri_scribe.phases.Branches) -> PhaseTree:
    """Derive the live or final hierarchy entirely from the catalogue and log evidence.

    Args:
        run: The selected command's retained records.
        branches: Source names available before new work starts.

    Returns:
        Visible phase states, trimmed branches, and decision explanations.
    """
    views = {path: PhaseView(path=path) for path in plan_for_run(run, branches)}
    reasons = [
        f"{event.message}: {event.fields.get('reason', '')}"
        for event in evidence(run)
        if event.message.startswith("Publication gate ")
    ]
    for event in evidence(run):
        fields = event.fields
        for index in range(1, len(event.path) + 1):
            path = event.path[:index]
            current = views.get(path, PhaseView(path=path))
            if current.status == Status.WAITING:
                views[path] = dataclasses.replace(
                    current,
                    status=Status.ACTIVE,
                    started_at=event.timestamp,
                )
        if event.message in {"Starting phase", "Finished phase"} and event.path:
            current = views[event.path]
            status = Status.ACTIVE
            elapsed = current.duration
            if event.message == "Finished phase":
                status = (
                    Status.FAILED
                    if fields.get("status") == "failed"
                    else Status.COMPLETED
                )
                elapsed = current.duration + recorded_duration(event)
            views[event.path] = dataclasses.replace(
                current,
                status=status,
                duration=elapsed,
                started_at=event.timestamp
                if status == Status.ACTIVE
                else current.started_at,
            )
    skipped = skipped_paths(evidence(run), views)
    visible: list[PhaseView] = []
    omissions: list[Omission] = []
    for path, view in views.items():
        if any(path[: len(omitted.path)] == omitted.path for omitted in omissions):
            continue
        reason = (
            omission_reason(path, views, run, skipped)
            if view.status == Status.WAITING
            else ""
        )
        if reason:
            omissions.append(Omission(path=path, reason=reason))
        elif run.status != Status.ACTIVE and view.status == Status.ACTIVE:
            visible.append(dataclasses.replace(view, status=Status.STOPPED))
        else:
            visible.append(view)
    return PhaseTree(
        phases=tuple(visible),
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
        minimum_level: The minimum severity to display.
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
