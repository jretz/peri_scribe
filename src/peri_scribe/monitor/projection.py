"""Reuse status until evidence or a displayed time boundary changes."""

import dataclasses
import datetime

import peri_scribe.monitor.history
import peri_scribe.monitor.status


@dataclasses.dataclass(frozen=True, kw_only=True)
class Snapshot:
    """One observer owns bounded cached calculations and their validity interval."""

    history: peri_scribe.monitor.history.History
    files: peri_scribe.monitor.status.Files
    observed_at: datetime.datetime
    observations: tuple[peri_scribe.monitor.status.Target, ...]
    view: peri_scribe.monitor.status.View
    changes_at: datetime.datetime | None
    evidence_changes_at: datetime.datetime | None


def evidence_deadline(
    observations: tuple[peri_scribe.monitor.status.Target, ...],
    now: datetime.datetime,
) -> datetime.datetime | None:
    """Account for future observations and inclusive exception-window expiry.

    Args:
        observations: Sorted evidence, including any future-dated records.
        now: The beginning of the cached evidence's validity.

    Returns:
        The first instant that time alone changes the evidence tables.
    """
    deadlines = []
    for item in observations:
        if item.when > now:
            deadlines.append(item.when)
        elif item.event.fields.get("exception"):
            expires = item.when + peri_scribe.monitor.history.WINDOW
            if expires >= now:
                deadlines.append(expires + datetime.timedelta(microseconds=1))
    return min(deadlines, default=None)


def display_deadline(
    history: peri_scribe.monitor.history.History,
    files: peri_scribe.monitor.status.Files,
    observations: tuple[peri_scribe.monitor.status.Target, ...],
    view: peri_scribe.monitor.status.View,
    now: datetime.datetime,
) -> datetime.datetime | None:
    """Keep ages, freshness warnings, and coverage exact between evidence changes.

    Args:
        history: Run details used by the live activity and coverage metrics.
        files: Artifact timestamps, including timestamps without build evidence.
        observations: Sorted evidence used to explain failure and recovery.
        view: The displayed metrics and their navigation targets.
        now: The beginning of this display's validity.

    Returns:
        The earliest possible change to a displayed age or severity.
    """
    timestamps = {metric.target.when for metric in view.metrics if metric.target}
    timestamps.update(
        output.modified for output in (files.kmz, files.report) if output.modified
    )
    active, failure = view.metrics[2], view.metrics[-1]
    if active.target:
        run = next(
            run for run in history.state.runs if run.identifier == active.target.run
        )
        timestamps.update(
            event.timestamp
            for event in run.events
            if event.timestamp and event.message == "Starting command"
        )
    if failure.target:
        # Failure ages describe completion; navigation identifies the earlier origin.
        timestamps.update(
            item.when
            for item in observations
            if item.run == failure.target.run
            and item.event.message == "Finished command"
        )
        recovered = peri_scribe.monitor.status.recovery(failure.target, observations)
        if recovered:
            timestamps.add(recovered.when)
    deadlines = []
    for timestamp in timestamps:
        if timestamp > now:
            deadlines.append(timestamp)
        else:
            elapsed = now - timestamp
            step = (
                datetime.timedelta(hours=1)
                if elapsed >= datetime.timedelta(days=1)
                else datetime.timedelta(minutes=1)
            )
            deadlines.append(timestamp + (elapsed // step + 1) * step)
            strict_limit = timestamp + datetime.timedelta(hours=6, microseconds=1)
            if strict_limit > now:
                deadlines.append(strict_limit)
    maximum = datetime.datetime.max.replace(tzinfo=datetime.UTC)
    for period in history.coverage:
        if period.start > now:
            deadlines.append(period.start)
        elif now <= period.end < maximum:
            deadlines.append(period.end + datetime.timedelta(microseconds=1))
    return min(deadlines, default=None)


def refresh(
    history: peri_scribe.monitor.history.History,
    files: peri_scribe.monitor.status.Files,
    now: datetime.datetime,
    previous: Snapshot | None = None,
) -> Snapshot:
    """Reuse evidence tables and the display independently of advancing wall time.

    Args:
        history: Current evidence and collection diagnostics.
        files: Current artifact and recovery-state snapshots.
        now: The current wall-clock time.
        previous: This observer's last computed snapshot.

    Returns:
        The same snapshot while valid, or refreshed status and validity deadlines.
    """
    same_state = previous is not None and previous.history.state is history.state
    forward = previous is not None and now >= previous.observed_at
    same_metadata = previous is not None and (
        history.coverage,
        history.undated,
        history.errors,
        history.caught_up,
    ) == (
        previous.history.coverage,
        previous.history.undated,
        previous.history.errors,
        previous.history.caught_up,
    )
    unchanged = same_state and same_metadata and forward
    if (
        previous is not None
        and unchanged
        and files == previous.files
        and (previous.changes_at is None or now < previous.changes_at)
    ):
        return previous
    observations = (
        previous.observations
        if previous is not None and same_state
        else peri_scribe.monitor.status.evidence(history)
    )
    tables = (
        previous
        if (
            previous is not None
            and same_state
            and forward
            and (
                previous.evidence_changes_at is None
                or now < previous.evidence_changes_at
            )
        )
        else None
    )
    evidence_changes_at = (
        tables.evidence_changes_at if tables else evidence_deadline(observations, now)
    )
    view = peri_scribe.monitor.status.project(
        history,
        files,
        now,
        observations=observations,
        tables=tables.view if tables else None,
    )
    changes_at = min(
        (
            value
            for value in (
                evidence_changes_at,
                display_deadline(history, files, observations, view, now),
            )
            if value is not None
        ),
        default=None,
    )
    return Snapshot(
        history=history,
        files=files,
        observed_at=now,
        observations=observations,
        view=view,
        changes_at=changes_at,
        evidence_changes_at=evidence_changes_at,
    )
