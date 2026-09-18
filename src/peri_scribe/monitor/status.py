"""Health projections explain freshness and recovery using recorded evidence."""

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
    """Recorded identity makes navigation independent of a table's current ordering."""

    run: str
    event: peri_scribe.monitor.events.Event

    @property
    def when(self) -> datetime.datetime:
        """Keep undated navigation targets sortable without asserting a known age."""
        return self.event.timestamp or datetime.datetime.min.replace(
            tzinfo=datetime.UTC,
        )


@dataclasses.dataclass(frozen=True, kw_only=True)
class Metric:
    """A labeled observation carries its health and optional supporting evidence."""

    label: str
    text: str
    health: Health
    target: Target | None = None


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
    path: str
    occurrences: int
    runs: frozenset[str]
    first: datetime.datetime
    latest: Target
    health: Health
    outcome: str


@dataclasses.dataclass(frozen=True, kw_only=True)
class View:
    """A presentation-neutral snapshot can serve terminal and future web consumers."""

    overview: Metric
    metrics: tuple[Metric, ...]
    exceptions: tuple[ExceptionSummary, ...]
    recent: tuple[Metric, ...]
    transitions: tuple[Metric, ...]
    coverage: Metric


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


def path_label(path: peri_scribe.phases.Path) -> str:
    """Keep every ancestor and source instance visible in the current activity.

    Args:
        path: The observed execution scope.

    Returns:
        A complete human-readable breadcrumb.
    """
    return " → ".join(
        segment.phase + (f" [{segment.branch}]" if segment.branch else "")
        for segment in path
    )


def age(timestamp: datetime.datetime | None, now: datetime.datetime) -> str:
    """Use stable compact ages without rounding across a freshness boundary.

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
    """Absolute timestamps make ages and observation coverage independently checkable.

    Args:
        timestamp: An optional recorded instant.

    Returns:
        Local time with its timezone, or an explicit unknown marker.
    """
    return (
        timestamp.astimezone().strftime("%b %d %H:%M:%S %Z") if timestamp else "unknown"
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
    label: str,
    phase: str,
    output: Output,
    observations: tuple[Target, ...],
    now: datetime.datetime,
) -> Metric:
    """Starting or failing a build cannot renew the last successful output's age.

    Args:
        label: The user-facing artifact name.
        phase: The stage that produces the artifact.
        output: Filesystem evidence about the actual artifact.
        observations: Chronological build evidence.
        now: The observation time.

    Returns:
        Freshness severity and the producing run when known.
    """
    target = next(
        (item for item in reversed(observations) if completed(item, phase)),
        None,
    )
    if output.error:
        return Metric(
            label=label,
            text=output.error,
            health=Health.BAD if output.missing else Health.WARNING,
            target=target,
        )
    timestamp = target.event.timestamp if target else output.modified
    if timestamp is None or timestamp > now:
        return Metric(
            label=label,
            text="Timestamp unknown or in the future",
            health=Health.WARNING,
        )
    elapsed = now - timestamp
    health = (
        Health.BAD
        if elapsed > datetime.timedelta(hours=6)
        else Health.WARNING
        if elapsed >= datetime.timedelta(hours=5)
        else Health.GOOD
    )
    qualifier = " · OVER 6 HOURS" if health == Health.BAD else ""
    basis = (
        "last successful build" if target else "file updated; build history unavailable"
    )
    return Metric(
        label=label,
        text=f"{age(timestamp, now)} old{qualifier}\n{local_time(timestamp)} · {basis}",
        health=health,
        target=target,
    )


def report_alignment(report: Metric, kmz: Metric, activity: Metric) -> Metric:
    """Reports normally follow KMZ publication without indicating a system problem.

    Args:
        report: Freshness of the last successful report.
        kmz: Freshness of the latest successful KMZ.
        activity: The current pipeline activity, independent of historical selection.

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
        text=report.text
        + (
            "\nReport generation in progress"
            if updating
            else "\nReport has not caught up with the latest KMZ"
        ),
        health=max(report.health, Health.ACTIVE if updating else Health.WARNING),
    )


def failure_metric(
    observations: tuple[Target, ...],
    now: datetime.datetime,
) -> Metric:
    """Retain historical failures while requiring matching work to prove recovery.

    Args:
        observations: Chronological observations across commands.
        now: The observation time.

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
        return Metric(
            label="Last failed run",
            text="None in available history",
            health=Health.GOOD,
        )
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
    description = (
        f"Recovered {age(recovered.event.timestamp, now)} ago"
        if recovered
        else "Recovery not yet recorded"
    )
    return Metric(
        label="Last failed run",
        text=(
            f"{age(failure.event.timestamp, now)} ago · {description}\n"
            f"{path_label(origin.event.path)}"
        ),
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
    groups: dict[tuple[str, str], ExceptionSummary] = {}
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
        scope = path_label(event.path) or str(
            event.fields.get("feed") or event.fields.get("source") or "Command",
        )
        key = (description, scope)
        prior_group = groups.get(key)
        recovered = recovery(item, observations)
        failed = runs[item.run].status == peri_scribe.monitor.model.Status.FAILED
        health = Health.GOOD if recovered else Health.BAD if failed else Health.WARNING
        outcome = (
            "Recovered"
            if recovered
            else "Failed run"
            if failed
            else "Recovery unconfirmed"
        )
        if prior_group and prior_group.health > health:
            health = prior_group.health
            outcome = prior_group.outcome
        groups[key] = ExceptionSummary(
            description=description,
            path=scope,
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
    now: datetime.datetime,
) -> Metric:
    """A lock-skipped invocation cannot conceal the run doing the actual work.

    Args:
        history: Available run observations.
        now: The current observation time.

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
        return Metric(
            label="Current activity",
            text="Waiting for pipeline evidence",
            health=Health.WARNING,
        )
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
    text = (
        (
            f"{path_label(run.open_path) or 'Command started'}\n"
            f"Elapsed {age(started, now)} · last recorded progress "
            f"{age(latest.timestamp, now)} ago · completion not yet recorded"
        )
        if active
        else f"Latest run {run.status} · {age(latest.timestamp, now)} ago"
    )
    return Metric(
        label="Current activity",
        text=text,
        health=Health.ACTIVE
        if active
        else Health.BAD
        if run.status == peri_scribe.monitor.model.Status.FAILED
        else Health.GOOD,
        target=Target(run=run.identifier, event=latest),
    )


def publication_metric(files: Files, observations: tuple[Target, ...]) -> Metric:
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
        return Metric(
            label="Publication",
            text=files.error,
            health=Health.WARNING,
            target=gate,
        )
    if files.pending:
        return Metric(
            label="Publication",
            text="Rebuild pending: " + " → ".join(files.pending),
            health=Health.WARNING,
            target=gate,
        )
    if gate:
        reason = str(gate.event.fields.get("reason", "Unknown reason"))
        return Metric(
            label="Publication",
            text=f"Last decision: {reason}",
            health=Health.GOOD,
            target=gate,
        )
    built = next(
        (item for item in reversed(observations) if completed(item, "kmz")),
        None,
    )
    if built:
        return Metric(
            label="Publication",
            text="Latest build completed",
            health=Health.GOOD,
            target=built,
        )
    return Metric(
        label="Publication",
        text="No publication decision recorded",
        health=Health.WARNING,
    )


def coverage_metric(
    history: peri_scribe.monitor.history.History,
    now: datetime.datetime,
) -> Metric:
    """Never equate missing or unreadable history with an absence of exceptions.

    Args:
        history: Evidence and its collection diagnostics.
        now: The observation time.

    Returns:
        Explicit availability of the requested 48-hour window.
    """
    if not history.caught_up:
        text = "Loading history · counts are incomplete"
    elif history.errors:
        text = "History incomplete · " + "; ".join(history.errors)
    elif not any(period.start <= now <= period.end for period in history.coverage):
        return Metric(
            label="History",
            text="No log entries in the last 48 hours",
            health=Health.BAD,
        )
    elif history.undated:
        text = (
            f"History incomplete · {history.undated} undated records "
            "excluded from timed metrics"
        )
    else:
        return Metric(
            label="History",
            text="48-hour window loaded from available logs",
            health=Health.GOOD,
        )
    return Metric(label="History", text=text, health=Health.WARNING)


def recent_metrics(history: peri_scribe.monitor.history.History) -> tuple[Metric, ...]:
    """Distinct run outcomes make normal checks and lock contention recognizable.

    Args:
        history: Compact run evidence.

    Returns:
        The twelve most recent command outcomes.
    """
    results: list[Metric] = []
    for run in reversed(history.state.runs[-12:]):
        last = run.events[-1]
        messages = {event.message for event in run.events}
        outcome = str(run.status)
        health = Health.WARNING
        if run.status == peri_scribe.monitor.model.Status.COMPLETED:
            health = Health.GOOD
            outcome = (
                "Built outputs"
                if any(
                    completed(Target(run=run.identifier, event=event), "kmz")
                    for event in run.events
                )
                else "Completed"
            )
            if "Another run owns this year; skipping invocation" in messages:
                outcome = "Skipped · another run held the lock"
                health = Health.WARNING
            elif "Publication gate skipped" in messages:
                outcome = "Checked · publication deferred"
        elif run.status == peri_scribe.monitor.model.Status.FAILED:
            health = Health.BAD
        elif run.status == peri_scribe.monitor.model.Status.ACTIVE:
            health = Health.ACTIVE
        results.append(
            Metric(
                label=local_time(last.timestamp),
                text=f"{run.command} · {outcome}",
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
    tables: View | None = None,
) -> View:
    """Derive a live overview independently of whichever historical run is selected.

    Args:
        history: Compact diagnostic evidence.
        files: Current artifact and recovery snapshots.
        now: The observation time for ages and the exception window.
        observations: Previously sorted evidence from the same history state.
        tables: Tables from the same evidence and exception window, when unchanged.

    Returns:
        All Status content and links without terminal-specific formatting.
    """
    if observations is None:
        observations = evidence(history)
    if observations and observations[-1].when > now:
        observations = tuple(item for item in observations if item.when <= now)
    activity = activity_metric(history, now)
    kmz = output_metric("KMZ", "kmz", files.kmz, observations, now)
    report = output_metric("Report", "reports", files.report, observations, now)
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
        label="Last successful source check",
        text=f"{age(check.when, now)} ago · {local_time(check.when)}"
        if check
        else "No successful check recorded",
        health=Health.GOOD
        if check and now - check.when <= datetime.timedelta(hours=6)
        else Health.WARNING,
        target=check,
    )
    failure = failure_metric(observations, now)
    publication = publication_metric(files, observations)
    if files.pending and activity.health == Health.ACTIVE and not files.error:
        publication = dataclasses.replace(
            publication,
            text="Build in progress · pending: " + " → ".join(files.pending),
            health=Health.ACTIVE,
        )
    metrics = (kmz, report, activity, source, publication, failure)
    coverage = coverage_metric(history, now)
    groups = (
        tables.exceptions if tables else exception_groups(history, observations, now)
    )
    exceptions = Metric(
        label="Exceptions",
        text=(
            f"{sum(group.health >= Health.WARNING for group in groups)} groups "
            "without confirmed recovery"
        ),
        health=max((group.health for group in groups), default=Health.GOOD),
    )
    problems = sorted(
        (
            item
            for item in (*metrics, coverage, exceptions)
            if item.health >= Health.WARNING
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
        health=problems[0].health if problems else Health.GOOD,
    )
    return View(
        overview=overview,
        metrics=metrics,
        exceptions=groups,
        recent=tables.recent if tables else recent_metrics(history),
        transitions=tables.transitions
        if tables
        else transition_metrics(observations, failure),
        coverage=coverage,
    )


def transition_metrics(
    observations: tuple[Target, ...],
    failure: Metric,
) -> tuple[Metric, ...]:
    """Retain meaningful changes after the current state has moved on.

    Args:
        observations: Chronological diagnostic evidence.
        failure: The latest failed run and its recovery state.

    Returns:
        The eight most recent publication, failure, and recovery transitions.
    """
    transitions: list[tuple[Target, str, Health]] = []
    for item in observations:
        event = item.event
        label = ""
        health = Health.GOOD
        if completed(item, "kmz"):
            label = "KMZ updated"
        elif completed(item, "reports"):
            label = "Report updated"
        elif event.message.startswith("Publication gate "):
            label = str(event.fields.get("reason", event.message))
        elif (
            event.message == "Finished command"
            and event.fields.get("status") == "failed"
        ):
            label = "Run failed"
            health = Health.BAD
        if label:
            transitions.append((item, label, health))
    recovered = recovery(failure.target, observations) if failure.target else None
    if recovered:
        transitions.append((recovered, "Failed work recovered", Health.GOOD))
    return tuple(
        Metric(
            label=local_time(item.event.timestamp),
            text=label,
            health=health,
            target=item,
        )
        for item, label, health in heapq.nlargest(
            8,
            transitions,
            key=lambda transition: transition[0].when,
        )
    )
