"""Format health facts without placing language or display timing in the domain.

Algorithm reasoning and contracts:
[Monitor presentation](../../../docs/algorithms/monitor-presentation.md)
"""

import dataclasses
import datetime

import peri_scribe.monitor.model
import peri_scribe.monitor.projection
import peri_scribe.monitor.status
import peri_scribe.phases


@dataclasses.dataclass(frozen=True, kw_only=True)
class Metric:
    """A formatted observation retains its domain evidence and health classification."""

    label: str
    text: str
    health: peri_scribe.monitor.status.Health
    target: peri_scribe.monitor.status.Target | None = None


@dataclasses.dataclass(frozen=True, kw_only=True)
class ExceptionSummary:
    """Formatted exception groups preserve their exact counts and evidence targets."""

    description: str
    path: str
    occurrences: int
    runs: frozenset[str]
    first: datetime.datetime
    latest: peri_scribe.monitor.status.Target
    health: peri_scribe.monitor.status.Health
    outcome: str


@dataclasses.dataclass(frozen=True, kw_only=True)
class View:
    """Prepared health content can be applied without further evidence calculations."""

    overview: Metric
    metrics: tuple[Metric, ...]
    exceptions: tuple[ExceptionSummary, ...]
    recent: tuple[Metric, ...]
    transitions: tuple[Metric, ...]
    coverage: Metric


def path_label(path: peri_scribe.phases.Path) -> str:
    """Preserve every ancestor and source instance in a readable breadcrumb.

    Args:
        path: The recorded execution scope.

    Returns:
        The complete scope in display order.
    """
    return " → ".join(
        segment.phase + (f" [{segment.branch}]" if segment.branch else "")
        for segment in path
    )


def age(timestamp: datetime.datetime | None, now: datetime.datetime) -> str:
    """Compact ages never round across a freshness boundary.

    Args:
        timestamp: The recorded observation time.
        now: The current aware time.

    Returns:
        An elapsed duration or an explicit unknown marker.
    """
    if timestamp is None:
        return "unknown"
    minutes = max(0, int((now - timestamp) / datetime.timedelta(minutes=1)))
    if minutes < 1:
        return "<1m"
    if datetime.timedelta(minutes=minutes) < datetime.timedelta(hours=1):
        return f"{minutes}m"
    hours, minutes = divmod(minutes, 60)
    if datetime.timedelta(hours=hours) < datetime.timedelta(days=1):
        return f"{hours}h {minutes}m"
    days, hours = divmod(hours, 24)
    return f"{days}d {hours}h"


def local_time(timestamp: datetime.datetime | None) -> str:
    """Absolute timestamps make ages independently checkable.

    Args:
        timestamp: An optional recorded instant.

    Returns:
        Local time with its timezone, or an explicit unknown marker.
    """
    return (
        timestamp.astimezone().strftime("%b %d %H:%M:%S %Z") if timestamp else "unknown"
    )


def output_metric(
    label: str,
    fact: peri_scribe.monitor.status.OutputMetric,
    now: datetime.datetime,
) -> Metric:
    """Explain the timestamp basis while preserving the domain's freshness policy.

    Args:
        label: The artifact's display name.
        fact: Its current freshness assessment.
        now: The observation time for age formatting.

    Returns:
        The artifact's formatted health and evidence.
    """
    if fact.issue == peri_scribe.monitor.status.OutputIssue.UNAVAILABLE:
        text = fact.error
    elif fact.issue == peri_scribe.monitor.status.OutputIssue.UNKNOWN_TIME:
        text = "Timestamp unknown or in the future"
    else:
        qualifier = (
            " · OVER 6 HOURS"
            if fact.health == peri_scribe.monitor.status.Health.BAD
            else ""
        )
        basis = (
            "last successful build"
            if fact.target
            else "file updated; build history unavailable"
        )
        text = (
            f"{age(fact.timestamp, now)} old{qualifier}\n"
            f"{local_time(fact.timestamp)} · {basis}"
        )
    if fact.alignment == peri_scribe.monitor.status.Alignment.UPDATING:
        text += "\nReport generation in progress"
    elif fact.alignment == peri_scribe.monitor.status.Alignment.LAGGING:
        text += "\nReport has not caught up with the latest KMZ"
    return Metric(label=label, text=text, health=fact.health, target=fact.target)


def activity_metric(
    fact: peri_scribe.monitor.status.ActivityMetric,
    now: datetime.datetime,
) -> Metric:
    """Explain recorded activity without adding a process-liveness claim.

    Args:
        fact: The current pipeline activity.
        now: The observation time for elapsed durations.

    Returns:
        Activity text carrying the domain's unchanged evidence target.
    """
    if fact.target is None:
        text = "Waiting for pipeline evidence"
    elif fact.status == peri_scribe.monitor.model.Status.ACTIVE:
        text = (
            f"{path_label(fact.path) or 'Command started'}\n"
            f"Elapsed {age(fact.started, now)} · last recorded progress "
            f"{age(fact.target.event.timestamp, now)} ago · completion not yet recorded"
        )
    else:
        text = f"Latest run {fact.status} · {age(fact.target.event.timestamp, now)} ago"
    return Metric(
        label="Current activity",
        text=text,
        health=fact.health,
        target=fact.target,
    )


def failure_metric(
    fact: peri_scribe.monitor.status.FailureMetric,
    now: datetime.datetime,
) -> Metric:
    """Failure age and recovery age refer to their own recorded completions.

    Args:
        fact: Failure origin, completion, and recovery evidence.
        now: The observation time for age formatting.

    Returns:
        The latest failure description and original evidence target.
    """
    if fact.finished is None:
        text = "None in available history"
    else:
        description = (
            f"Recovered {age(fact.recovered.event.timestamp, now)} ago"
            if fact.recovered
            else "Recovery not yet recorded"
        )
        text = (
            f"{age(fact.finished.event.timestamp, now)} ago · {description}\n"
            f"{path_label(fact.target.event.path) if fact.target else ''}"
        )
    return Metric(
        label="Last failed run",
        text=text,
        health=fact.health,
        target=fact.target,
    )


def publication_metric(fact: peri_scribe.monitor.status.PublicationMetric) -> Metric:
    """Describe publication facts without inferring new health classifications.

    Args:
        fact: Recorded publication state and recovery requirements.

    Returns:
        A readable decision or pending-work description.
    """
    match fact.state:
        case peri_scribe.monitor.status.PublicationState.UNAVAILABLE:
            text = fact.error
        case peri_scribe.monitor.status.PublicationState.PENDING:
            text = "Rebuild pending: " + " → ".join(fact.pending)
        case peri_scribe.monitor.status.PublicationState.ACTIVE:
            text = "Build in progress · pending: " + " → ".join(fact.pending)
        case peri_scribe.monitor.status.PublicationState.DECIDED:
            text = "Last decision: " + (
                "Unknown reason" if fact.reason is None else fact.reason
            )
        case peri_scribe.monitor.status.PublicationState.COMPLETED:
            text = "Latest build completed"
        case _:
            text = "No publication decision recorded"
    return Metric(
        label="Publication",
        text=text,
        health=fact.health,
        target=fact.target,
    )


def coverage_metric(fact: peri_scribe.monitor.status.CoverageMetric) -> Metric:
    """Collection limitations remain explicit alongside exception counts.

    Args:
        fact: Availability of the requested observation interval.

    Returns:
        The history coverage explanation.
    """
    match fact.state:
        case peri_scribe.monitor.status.CoverageState.LOADING:
            text = "Loading history · counts are incomplete"
        case peri_scribe.monitor.status.CoverageState.INCOMPLETE:
            text = "History incomplete · " + "; ".join(fact.errors)
        case peri_scribe.monitor.status.CoverageState.EMPTY:
            text = "No log entries in the last 48 hours"
        case peri_scribe.monitor.status.CoverageState.UNDATED:
            text = (
                f"History incomplete · {fact.undated} undated records "
                "excluded from timed metrics"
            )
        case _:
            text = "48-hour window loaded from available logs"
    return Metric(label="History", text=text, health=fact.health)


def recent_metrics(
    facts: tuple[peri_scribe.monitor.status.RunOutcome, ...],
) -> tuple[Metric, ...]:
    """Translate command outcomes without rescanning their event histories.

    Args:
        facts: Recent commands classified by the domain.

    Returns:
        Formatted rows retaining their timestamps and evidence.
    """
    names = {
        peri_scribe.monitor.status.Outcome.BUILT: "Built outputs",
        peri_scribe.monitor.status.Outcome.COMPLETED: "Completed",
        peri_scribe.monitor.status.Outcome.LOCKED: (
            "Skipped · another run held the lock"
        ),
        peri_scribe.monitor.status.Outcome.DEFERRED: "Checked · publication deferred",
        peri_scribe.monitor.status.Outcome.FAILED: "failed",
        peri_scribe.monitor.status.Outcome.ACTIVE: "open",
        peri_scribe.monitor.status.Outcome.STOPPED: "unfinished",
        peri_scribe.monitor.status.Outcome.WAITING: "waiting",
    }
    return tuple(
        Metric(
            label=local_time(fact.target.event.timestamp if fact.target else None),
            text=f"{fact.command} · {names[fact.outcome]}",
            health=fact.health,
            target=fact.target,
        )
        for fact in facts
    )


def transition_metrics(
    facts: tuple[peri_scribe.monitor.status.Transition, ...],
) -> tuple[Metric, ...]:
    """Format only the already-selected significant transitions.

    Args:
        facts: Domain-selected publication, failure, and recovery changes.

    Returns:
        Chronological labels and literal descriptions for the selected changes.
    """
    names = {
        peri_scribe.monitor.status.TransitionKind.KMZ: "KMZ updated",
        peri_scribe.monitor.status.TransitionKind.REPORT: "Report updated",
        peri_scribe.monitor.status.TransitionKind.FAILURE: "Run failed",
        peri_scribe.monitor.status.TransitionKind.RECOVERY: "Failed work recovered",
    }
    return tuple(
        Metric(
            label=local_time(fact.target.event.timestamp if fact.target else None),
            text=names.get(fact.kind, fact.reason),
            health=fact.health,
            target=fact.target,
        )
        for fact in facts
    )


def present(
    assessment: peri_scribe.monitor.status.Assessment,
    now: datetime.datetime,
) -> View:
    """Keep summary precedence and formatting separate from health decisions.

    Args:
        assessment: Current domain findings and supporting observations.
        now: The display's current clock observation.

    Returns:
        Complete health content ready for a presentation adapter.
    """
    kmz, report, activity, source, publication, failure = assessment.metrics
    source_metric = Metric(
        label="Last successful source check",
        text=(f"{age(source.target.when, now)} ago · {local_time(source.target.when)}")
        if source.target
        else "No successful check recorded",
        health=source.health,
        target=source.target,
    )
    metrics = (
        output_metric("KMZ", kmz, now),
        output_metric("Report", report, now),
        activity_metric(activity, now),
        source_metric,
        publication_metric(publication),
        failure_metric(failure, now),
    )
    coverage = coverage_metric(assessment.coverage)
    outcomes = {
        peri_scribe.monitor.status.RecoveryState.RECOVERED: "Recovered",
        peri_scribe.monitor.status.RecoveryState.FAILED: "Failed run",
        peri_scribe.monitor.status.RecoveryState.UNCONFIRMED: "Recovery unconfirmed",
    }
    groups = tuple(
        ExceptionSummary(
            description=group.description,
            path=path_label(group.path) or group.context or "Command",
            occurrences=group.occurrences,
            runs=group.runs,
            first=group.first,
            latest=group.latest,
            health=group.health,
            outcome=outcomes[group.outcome],
        )
        for group in assessment.exceptions
    )
    unresolved = sum(
        group.health >= peri_scribe.monitor.status.Health.WARNING for group in groups
    )
    exceptions = Metric(
        label="Exceptions",
        text=f"{unresolved} groups without confirmed recovery",
        health=max(
            (group.health for group in groups),
            default=peri_scribe.monitor.status.Health.GOOD,
        ),
    )
    problems = sorted(
        (
            item
            for item in (*metrics, coverage, exceptions)
            if item.health >= peri_scribe.monitor.status.Health.WARNING
        ),
        key=lambda item: item.health,
        reverse=True,
    )
    overview = Metric(
        label="Needs attention" if problems else "System okay",
        text=" · ".join(
            f"{item.label}: {item.text.splitlines()[0]}" for item in problems[:3]
        )
        if problems
        else "Outputs are current · no unresolved run failure recorded",
        health=assessment.overview.health,
    )
    return View(
        overview=overview,
        metrics=metrics,
        exceptions=groups,
        recent=recent_metrics(assessment.recent),
        transitions=transition_metrics(assessment.transitions),
        coverage=coverage,
    )


def prepare(
    snapshot: peri_scribe.monitor.projection.Snapshot,
    now: datetime.datetime,
) -> View:
    """Prepare the current complete assessment without rereading its evidence.

    Args:
        snapshot: A complete version received from the monitoring session.
        now: The presentation clock observation.

    Returns:
        The formatted health content for this observation time.
    """
    return present(snapshot.assessment, now)


def deadline(
    snapshot: peri_scribe.monitor.projection.Snapshot,
    now: datetime.datetime,
) -> datetime.datetime | None:
    """Schedule cosmetic age updates without invalidating cached domain evidence.

    Args:
        snapshot: Current domain facts and their original timestamps.
        now: The beginning of the formatted content's validity.

    Returns:
        The next minute or hour boundary affecting a displayed duration.
    """
    kmz, report, activity, source, _, failure = snapshot.assessment.metrics
    timestamps = {
        kmz.timestamp,
        report.timestamp,
        activity.started,
        activity.target.event.timestamp if activity.target else None,
        source.target.event.timestamp if source.target else None,
        failure.finished.event.timestamp if failure.finished else None,
        failure.recovered.event.timestamp if failure.recovered else None,
    }
    deadlines = []
    for timestamp in timestamps:
        if timestamp is None:
            continue
        if timestamp > now:
            deadlines.append(timestamp)
            continue
        elapsed = now - timestamp
        step = (
            datetime.timedelta(hours=1)
            if elapsed >= datetime.timedelta(days=1)
            else datetime.timedelta(minutes=1)
        )
        deadlines.append(timestamp + (elapsed // step + 1) * step)
    return min(deadlines, default=None)
