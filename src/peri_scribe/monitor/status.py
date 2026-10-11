"""Health projections explain freshness and recovery using recorded evidence.

Algorithm reasoning and contracts:
[Monitor evidence](../../../docs/algorithms/monitor-evidence.md)
"""

import dataclasses
import datetime
import enum
import heapq
import pathlib
import re

import peri_scribe.monitor.events
import peri_scribe.monitor.history
import peri_scribe.monitor.model
import peri_scribe.phases
import peri_scribe.pipeline_state


class Health(enum.IntEnum):
    """Severity ordering lets the overview retain the most important current problem."""

    GOOD = 0
    ACTIVE = 1
    WARNING = 2
    BAD = 3


@dataclasses.dataclass(frozen=True, kw_only=True)
class Target:
    """Recorded identity associates each finding with its command and event."""

    run: str
    event: peri_scribe.monitor.events.Event

    @property
    def when(self) -> datetime.datetime:
        """Keep undated evidence targets sortable without asserting a known age."""
        return self.event.timestamp or datetime.datetime.min.replace(
            tzinfo=datetime.UTC,
        )


class OutputIssue(enum.Enum):
    """Artifact evidence distinguishes read failures from unknown observation times."""

    NONE = "none"
    UNAVAILABLE = "unavailable"
    UNKNOWN_TIME = "unknown-time"


class Alignment(enum.Enum):
    """A report may lag a map while a related command is still producing it."""

    CURRENT = "current"
    UPDATING = "updating"
    LAGGING = "lagging"


class PublicationState(enum.Enum):
    """Recorded decisions and recovery requirements distinguish publication outcomes."""

    UNKNOWN = "unknown"
    UNAVAILABLE = "unavailable"
    PENDING = "pending"
    ACTIVE = "active"
    DECIDED = "decided"
    COMPLETED = "completed"


class CoverageState(enum.Enum):
    """Collection limitations remain distinct from an observed empty interval."""

    LOADING = "loading"
    INCOMPLETE = "incomplete"
    EMPTY = "empty"
    UNDATED = "undated"
    COMPLETE = "complete"


class RecoveryState(enum.Enum):
    """Only matching successful work can establish recovery."""

    RECOVERED = "recovered"
    FAILED = "failed"
    UNCONFIRMED = "unconfirmed"


class Outcome(enum.Enum):
    """Command outcomes distinguish useful checks from produced artifacts."""

    BUILT = "built"
    COMPLETED = "completed"
    LOCKED = "locked"
    DEFERRED = "deferred"
    FAILED = "failed"
    ACTIVE = "active"
    STOPPED = "stopped"
    WAITING = "waiting"


class TransitionKind(enum.Enum):
    """Recorded state changes retain their source evidence."""

    KMZ = "kmz"
    REPORT = "report"
    PUBLICATION = "publication"
    FAILURE = "failure"
    RECOVERY = "recovery"


@dataclasses.dataclass(frozen=True, kw_only=True)
class Metric:
    """A health classification retains the evidence supporting its conclusion."""

    health: Health
    target: Target | None = None


@dataclasses.dataclass(frozen=True, kw_only=True)
class OutputMetric(Metric):
    """Artifact freshness preserves its timestamp and the source of uncertainty."""

    timestamp: datetime.datetime | None = None
    issue: OutputIssue = OutputIssue.NONE
    error: str = ""
    alignment: Alignment = Alignment.CURRENT


@dataclasses.dataclass(frozen=True, kw_only=True)
class ActivityMetric(Metric):
    """Observed command activity does not establish process liveness."""

    started: datetime.datetime | None = None
    path: peri_scribe.phases.Path = ()
    status: peri_scribe.monitor.model.Status | None = None


@dataclasses.dataclass(frozen=True, kw_only=True)
class FailureMetric(Metric):
    """Failure origin, completion, and recovery are separate recorded observations."""

    finished: Target | None = None
    recovered: Target | None = None


@dataclasses.dataclass(frozen=True, kw_only=True)
class PublicationMetric(Metric):
    """Recovery state and publication decisions retain their original facts."""

    state: PublicationState
    pending: tuple[str, ...] = ()
    error: str = ""
    reason: str | None = None


@dataclasses.dataclass(frozen=True, kw_only=True)
class CoverageMetric(Metric):
    """Collection completeness identifies why evidence may be insufficient."""

    state: CoverageState
    errors: tuple[str, ...] = ()
    undated: int = 0


@dataclasses.dataclass(frozen=True, kw_only=True)
class RunOutcome(Metric):
    """Each command's recorded result remains distinct from other invocations."""

    command: str
    outcome: Outcome


@dataclasses.dataclass(frozen=True, kw_only=True)
class Transition(Metric):
    """A bounded history of significant changes retains recorded decision reasons."""

    kind: TransitionKind
    reason: str = ""


@dataclasses.dataclass(frozen=True, kw_only=True)
class Output:
    """Filesystem evidence distinguishes unavailable outputs from incomplete history."""

    modified: datetime.datetime | None = None
    error: str = ""
    missing: bool = False


@dataclasses.dataclass(frozen=True, kw_only=True)
class Files:
    """Small read-only snapshots keep filesystem errors out of health calculations."""

    kmz: Output
    report: Output
    pending: tuple[str, ...] = ()
    error: str = ""


@dataclasses.dataclass(frozen=True, kw_only=True)
class ExceptionSummary:
    """Counts describe occurrences, not repeated logging by enclosing phases."""

    description: str
    path: peri_scribe.phases.Path
    context: str
    occurrences: int
    runs: frozenset[str]
    first: datetime.datetime
    latest: Target
    health: Health
    outcome: RecoveryState


@dataclasses.dataclass(frozen=True, kw_only=True)
class Assessment:
    """Health facts remain independent of language, layout, and presentation timing."""

    overview: Metric
    metrics: tuple[
        OutputMetric,
        OutputMetric,
        ActivityMetric,
        Metric,
        PublicationMetric,
        FailureMetric,
    ]
    exceptions: tuple[ExceptionSummary, ...]
    recent: tuple[RunOutcome, ...]
    transitions: tuple[Transition, ...]
    coverage: CoverageMetric


def read_output(path: pathlib.Path) -> Output:
    """Check the actual artifact even if successful build logs remain available.

    Args:
        path: The expected output artifact.

    Returns:
        Its timestamp or an explicit unavailable state.
    """
    try:
        metadata = path.stat()
        if not metadata.st_size or not path.is_file():
            return Output(error="Output is empty or is not a file", missing=True)
        return Output(
            modified=datetime.datetime.fromtimestamp(metadata.st_mtime, datetime.UTC),
        )
    except FileNotFoundError:
        return Output(error="Missing output", missing=True)
    except (OSError, ValueError, OverflowError) as error:
        return Output(error=f"Unable to read output timestamp: {error}")


def read_files(
    directory: pathlib.Path,
    kmz_path: pathlib.Path,
    report_path: pathlib.Path,
) -> Files:
    """Read recovery state without invoking pipeline logging or modifying its files.

    Args:
        directory: The observed year directory.
        kmz_path: The expected map artifact.
        report_path: The expected report artifact.

    Returns:
        Output timestamps, pending work, and recovery-state read errors.
    """
    pending: tuple[str, ...] = ()
    error = ""
    try:
        state = peri_scribe.pipeline_state.PendingRun.model_validate_json(
            peri_scribe.pipeline_state.state_path(directory).read_bytes(),
        )
        pending = tuple(state.remaining)
    except FileNotFoundError:
        pass
    except (OSError, ValueError) as failure:
        error = f"Recovery state unavailable: {failure}"
    return Files(
        kmz=read_output(kmz_path),
        report=read_output(report_path),
        pending=pending,
        error=error,
    )


def evidence(history: peri_scribe.monitor.history.History) -> tuple[Target, ...]:
    """Sort historical and live records together before making recovery decisions.

    Args:
        history: Compact status evidence.

    Returns:
        Timestamped observations paired with their owning runs.
    """
    return tuple(
        sorted(
            (
                Target(run=run.identifier, event=event)
                for run in history.state.runs
                for event in run.events
                if event.timestamp
            ),
            key=lambda target: (target.when, target.event.sequence),
        ),
    )


def completed(target: Target, phase: str = "") -> bool:
    """Only recorded successful phase completion can acknowledge finished work.

    Args:
        target: A candidate observation.
        phase: An optional phase name to match.

    Returns:
        Whether this is a successful completion of the requested phase.
    """
    event = target.event
    return bool(
        event.message == "Finished phase"
        and event.fields.get("status") == "completed"
        and event.path
        and (not phase or event.path[-1].phase == phase),
    )


def recovery(target: Target, observations: tuple[Target, ...]) -> Target | None:
    """A successful containing phase proves recovery even after a retried exception.

    Args:
        target: The original failure with its most specific known scope.
        observations: Chronological successful and failed work.

    Returns:
        The first later completion of the failed work, when recorded.
    """
    after = False
    for candidate in observations:
        if candidate == target:
            after = True
        elif (
            after
            and completed(candidate)
            and target.event.path
            and target.event.path[: len(candidate.event.path)] == candidate.event.path
        ):
            return candidate
    return None


def output_metric(
    phase: str,
    output: Output,
    observations: tuple[Target, ...],
    now: datetime.datetime,
) -> OutputMetric:
    """Starting or failing a build cannot renew the last successful artifact's age.

    Args:
        phase: The stage that produces the artifact.
        output: Filesystem evidence about the actual artifact.
        observations: Chronological build evidence.
        now: The observation time.

    Returns:
        Freshness severity, timestamp, and the producing run when known.
    """
    target = next(
        (item for item in reversed(observations) if completed(item, phase)),
        None,
    )
    if output.error:
        return OutputMetric(
            issue=OutputIssue.UNAVAILABLE,
            error=output.error,
            health=Health.BAD if output.missing else Health.WARNING,
            target=target,
        )
    timestamp = target.event.timestamp if target else output.modified
    if timestamp is None or timestamp > now:
        return OutputMetric(issue=OutputIssue.UNKNOWN_TIME, health=Health.WARNING)
    elapsed = now - timestamp
    health = (
        Health.BAD
        if elapsed > datetime.timedelta(hours=6)
        else Health.WARNING
        if elapsed >= datetime.timedelta(hours=5)
        else Health.GOOD
    )
    return OutputMetric(timestamp=timestamp, health=health, target=target)


def report_alignment(
    report: OutputMetric,
    kmz: OutputMetric,
    activity: ActivityMetric,
) -> OutputMetric:
    """Reports normally follow KMZ publication without indicating a system problem.

    Args:
        report: Freshness of the last successful report.
        kmz: Freshness of the latest successful KMZ.
        activity: The latest recorded pipeline activity.

    Returns:
        Expected progress or an unresolved mismatch, preserving freshness severity.
    """
    if not (kmz.target and report.target and report.target.when < kmz.target.when):
        return report
    updating = (
        activity.health == Health.ACTIVE
        and activity.target is not None
        and activity.target.event.fields.get("status") != "failed"
        and (
            activity.target.run == kmz.target.run
            or (
                activity.target.event.path
                and activity.target.event.path[0].phase == "reports"
            )
        )
    )
    return dataclasses.replace(
        report,
        alignment=Alignment.UPDATING if updating else Alignment.LAGGING,
        health=max(report.health, Health.ACTIVE if updating else Health.WARNING),
    )


def failure_metric(
    observations: tuple[Target, ...],
) -> FailureMetric:
    """Retain historical failures while requiring matching work to prove recovery.

    Args:
        observations: Chronological observations across commands.

    Returns:
        The latest failed run and whether its failed work later succeeded.
    """
    failure = next(
        (
            item
            for item in reversed(observations)
            if item.event.message == "Finished command"
            and item.event.fields.get("status") == "failed"
        ),
        None,
    )
    if failure is None:
        return FailureMetric(health=Health.GOOD)
    origin = next(
        (
            item
            for item in observations
            if item.run == failure.run
            and item.event.message == "Finished phase"
            and item.event.fields.get("status") == "failed"
        ),
        failure,
    )
    recovered = recovery(origin, observations)
    return FailureMetric(
        finished=failure,
        recovered=recovered,
        health=Health.GOOD if recovered else Health.BAD,
        target=origin,
    )


def signature(exception: object) -> str:
    """Normalize incidental identifiers while preserving meaningful error codes.

    Args:
        exception: The logged traceback or exception description.

    Returns:
        A stable final exception line suitable for grouping repeated incidents.
    """
    lines = str(exception).strip().splitlines()
    message = lines[-1].strip() if lines else "Unknown exception"
    message = re.sub(
        r"\b[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\b",
        "<id>",
        message,
    )
    message = re.sub(r"\b\d{4}-\d{2}-\d{2}[T ][\d:.+Z-]+", "<time>", message)
    return re.sub(r"0x[0-9a-fA-F]+\b", "<address>", message)


def exception_groups(
    history: peri_scribe.monitor.history.History,
    observations: tuple[Target, ...],
    now: datetime.datetime,
) -> tuple[ExceptionSummary, ...]:
    """Count retry attempts once and suppress repeated exception propagation records.

    Args:
        history: Run outcomes for classifying exceptions.
        observations: Chronological diagnostic evidence.
        now: The end of the rolling 48-hour window.

    Returns:
        Groups ordered by their most recent occurrence, each linked to its origin.
    """
    groups: dict[tuple[str, peri_scribe.phases.Path, str], ExceptionSummary] = {}
    previous: dict[str, Target] = {}
    runs = {run.identifier: run for run in history.state.runs}
    for item in observations:
        event = item.event
        if not event.fields.get("exception"):
            continue
        description = signature(event.fields["exception"])
        prior = previous.get(item.run)
        if (
            prior
            and event.message in {"Finished phase", "Finished command"}
            and signature(prior.event.fields["exception"]) == description
            and prior.event.path[: len(event.path)] == event.path
        ):
            continue
        previous[item.run] = item
        timestamp = event.timestamp
        if (
            timestamp is None
            or not now - peri_scribe.monitor.history.WINDOW <= timestamp <= now
        ):
            continue
        context = (
            ""
            if event.path
            else str(
                event.fields.get("feed") or event.fields.get("source") or "",
            )
        )
        key = (description, event.path, context)
        prior_group = groups.get(key)
        recovered = recovery(item, observations)
        failed = runs[item.run].status == peri_scribe.monitor.model.Status.FAILED
        health = Health.GOOD if recovered else Health.BAD if failed else Health.WARNING
        outcome = (
            RecoveryState.RECOVERED
            if recovered
            else RecoveryState.FAILED
            if failed
            else RecoveryState.UNCONFIRMED
        )
        if prior_group and prior_group.health > health:
            health = prior_group.health
            outcome = prior_group.outcome
        groups[key] = ExceptionSummary(
            description=description,
            path=event.path,
            context=context,
            occurrences=(prior_group.occurrences if prior_group else 0) + 1,
            runs=(prior_group.runs if prior_group else frozenset()) | {item.run},
            first=prior_group.first if prior_group else timestamp,
            latest=item,
            health=health,
            outcome=outcome,
        )
    return tuple(
        sorted(
            groups.values(),
            key=lambda group: group.latest.when,
            reverse=True,
        ),
    )


def activity_metric(
    history: peri_scribe.monitor.history.History,
) -> ActivityMetric:
    """A lock-skipped invocation cannot conceal the run doing the actual work.

    Args:
        history: Available run observations.

    Returns:
        The latest pipeline activity with its complete phase path.
    """
    run = next(
        (
            run
            for run in reversed(history.state.runs)
            if run.command == "run"
            and not any(
                event.message == "Another run owns this year; skipping invocation"
                for event in run.events
            )
        ),
        None,
    )
    if run is None:
        return ActivityMetric(health=Health.WARNING)
    latest = run.events[-1]
    started = next(
        (
            event.timestamp
            for event in run.events
            if event.message == "Starting command"
        ),
        None,
    )
    active = run.status == peri_scribe.monitor.model.Status.ACTIVE
    return ActivityMetric(
        started=started,
        path=run.open_path,
        status=run.status,
        health=Health.ACTIVE
        if active
        else Health.BAD
        if run.status == peri_scribe.monitor.model.Status.FAILED
        else Health.GOOD,
        target=Target(run=run.identifier, event=latest),
    )


def publication_metric(
    files: Files,
    observations: tuple[Target, ...],
) -> PublicationMetric:
    """Explain waiting and unfinished work alongside unconditional output age limits.

    Args:
        files: Current recovery requirements.
        observations: Recorded publication decisions.

    Returns:
        The reason output work is pending or was last deferred.
    """
    gate = next(
        (
            item
            for item in reversed(observations)
            if item.event.message.startswith("Publication gate ")
        ),
        None,
    )
    if files.error:
        return PublicationMetric(
            state=PublicationState.UNAVAILABLE,
            error=files.error,
            health=Health.WARNING,
            target=gate,
        )
    if files.pending:
        return PublicationMetric(
            state=PublicationState.PENDING,
            pending=files.pending,
            health=Health.WARNING,
            target=gate,
        )
    if gate:
        reason = (
            str(gate.event.fields["reason"]) if "reason" in gate.event.fields else None
        )
        return PublicationMetric(
            state=PublicationState.DECIDED,
            reason=reason,
            health=Health.GOOD,
            target=gate,
        )
    built = next(
        (item for item in reversed(observations) if completed(item, "kmz")),
        None,
    )
    if built:
        return PublicationMetric(
            state=PublicationState.COMPLETED,
            health=Health.GOOD,
            target=built,
        )
    return PublicationMetric(
        state=PublicationState.UNKNOWN,
        health=Health.WARNING,
    )


def coverage_metric(
    history: peri_scribe.monitor.history.History,
    now: datetime.datetime,
) -> CoverageMetric:
    """Missing or unreadable history cannot establish the absence of exceptions.

    Args:
        history: Evidence and its collection diagnostics.
        now: The observation time.

    Returns:
        Availability and limitations of the inclusive 48-hour interval.
    """
    if not history.caught_up:
        state = CoverageState.LOADING
    elif history.errors:
        state = CoverageState.INCOMPLETE
    elif not any(period.start <= now <= period.end for period in history.coverage):
        return CoverageMetric(state=CoverageState.EMPTY, health=Health.BAD)
    elif history.undated:
        state = CoverageState.UNDATED
    else:
        return CoverageMetric(state=CoverageState.COMPLETE, health=Health.GOOD)
    return CoverageMetric(
        state=state,
        errors=history.errors,
        undated=history.undated,
        health=Health.WARNING,
    )


def recent_metrics(
    history: peri_scribe.monitor.history.History,
) -> tuple[RunOutcome, ...]:
    """Distinct run outcomes make normal checks and lock contention recognizable.

    Args:
        history: Compact run evidence.

    Returns:
        The twelve most recent command outcomes.
    """
    results: list[RunOutcome] = []
    for run in reversed(history.state.runs[-12:]):
        last = run.events[-1]
        messages = {event.message for event in run.events}
        outcome = {
            peri_scribe.monitor.model.Status.ACTIVE: Outcome.ACTIVE,
            peri_scribe.monitor.model.Status.FAILED: Outcome.FAILED,
            peri_scribe.monitor.model.Status.STOPPED: Outcome.STOPPED,
            peri_scribe.monitor.model.Status.WAITING: Outcome.WAITING,
        }.get(run.status, Outcome.COMPLETED)
        health = Health.WARNING
        if run.status == peri_scribe.monitor.model.Status.COMPLETED:
            health = Health.GOOD
            outcome = (
                Outcome.BUILT
                if any(
                    completed(Target(run=run.identifier, event=event), "kmz")
                    for event in run.events
                )
                else Outcome.COMPLETED
            )
            if "Another run owns this year; skipping invocation" in messages:
                outcome = Outcome.LOCKED
                health = Health.WARNING
            elif "Publication gate skipped" in messages:
                outcome = Outcome.DEFERRED
        elif run.status == peri_scribe.monitor.model.Status.FAILED:
            health = Health.BAD
        elif run.status == peri_scribe.monitor.model.Status.ACTIVE:
            health = Health.ACTIVE
        results.append(
            RunOutcome(
                command=run.command,
                outcome=outcome,
                health=health,
                target=Target(run=run.identifier, event=last),
            ),
        )
    return tuple(results)


def project(
    history: peri_scribe.monitor.history.History,
    files: Files,
    now: datetime.datetime,
    *,
    observations: tuple[Target, ...] | None = None,
    previous: Assessment | None = None,
) -> Assessment:
    """Assess current health from complete evidence and artifact observations.

    Args:
        history: Compact diagnostic evidence.
        files: Current artifact and recovery snapshots.
        now: The observation time for freshness and the exception interval.
        observations: Previously sorted evidence from the same history state.
        previous: Facts from the same evidence and exception interval, when unchanged.

    Returns:
        Health classifications and their recorded supporting facts.
    """
    if observations is None:
        observations = evidence(history)
    if observations and observations[-1].when > now:
        observations = tuple(item for item in observations if item.when <= now)
    activity = activity_metric(history)
    kmz = output_metric("kmz", files.kmz, observations, now)
    report = output_metric("reports", files.report, observations, now)
    report = report_alignment(report, kmz, activity)
    check = next(
        (
            item
            for item in reversed(observations)
            if completed(item, "fire-collection") or completed(item, "fetch")
        ),
        None,
    )
    source = Metric(
        health=Health.GOOD
        if check and now - check.when <= datetime.timedelta(hours=6)
        else Health.WARNING,
        target=check,
    )
    failure = failure_metric(observations)
    publication = publication_metric(files, observations)
    if files.pending and activity.health == Health.ACTIVE and not files.error:
        publication = dataclasses.replace(
            publication,
            state=PublicationState.ACTIVE,
            health=Health.ACTIVE,
        )
    metrics = (kmz, report, activity, source, publication, failure)
    coverage = coverage_metric(history, now)
    groups = (
        previous.exceptions
        if previous
        else exception_groups(history, observations, now)
    )
    overall = max(
        (item.health for item in (*metrics, coverage, *groups)),
        default=Health.GOOD,
    )
    return Assessment(
        overview=Metric(health=overall if overall >= Health.WARNING else Health.GOOD),
        metrics=metrics,
        exceptions=groups,
        recent=previous.recent if previous else recent_metrics(history),
        transitions=previous.transitions
        if previous
        else transition_metrics(observations, failure),
        coverage=coverage,
    )


def transition_metrics(
    observations: tuple[Target, ...],
    failure: FailureMetric,
) -> tuple[Transition, ...]:
    """Retain meaningful changes after the current state has moved on.

    Args:
        observations: Chronological diagnostic evidence.
        failure: The latest failed run and its recovery state.

    Returns:
        The eight most recent publication, failure, and recovery transitions.
    """
    transitions: list[Transition] = []
    for item in observations:
        event = item.event
        kind = None
        reason = ""
        health = Health.GOOD
        if completed(item, "kmz"):
            kind = TransitionKind.KMZ
        elif completed(item, "reports"):
            kind = TransitionKind.REPORT
        elif event.message.startswith("Publication gate "):
            kind = TransitionKind.PUBLICATION
            reason = str(event.fields.get("reason", event.message))
        elif (
            event.message == "Finished command"
            and event.fields.get("status") == "failed"
        ):
            kind = TransitionKind.FAILURE
            health = Health.BAD
        if kind is not None and (kind != TransitionKind.PUBLICATION or reason):
            transitions.append(
                Transition(target=item, kind=kind, reason=reason, health=health),
            )
    recovered = failure.recovered
    if recovered:
        transitions.append(
            Transition(
                target=recovered,
                kind=TransitionKind.RECOVERY,
                health=Health.GOOD,
            ),
        )
    return tuple(
        heapq.nlargest(
            8,
            transitions,
            key=lambda transition: (
                transition.target.when
                if transition.target
                else datetime.datetime.min.replace(tzinfo=datetime.UTC)
            ),
        ),
    )
