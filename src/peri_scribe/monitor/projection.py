"""Reuse health findings until evidence or a policy boundary changes.

Algorithm reasoning and contracts:
[Monitor evidence](../../../docs/algorithms/monitor-evidence.md)
"""

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
    assessment: peri_scribe.monitor.status.Assessment
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
        The first instant that time alone changes the evidence classifications.
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


def policy_deadline(
    history: peri_scribe.monitor.history.History,
    files: peri_scribe.monitor.status.Files,
    assessment: peri_scribe.monitor.status.Assessment,
    now: datetime.datetime,
) -> datetime.datetime | None:
    """Refresh health only when time can change an evidence-based classification.

    Args:
        history: Inclusive coverage intervals and collection diagnostics.
        files: Artifact observations, including future timestamps.
        assessment: Current freshness and source-check findings.
        now: The beginning of the assessment's validity.

    Returns:
        The next freshness or coverage policy boundary.
    """
    kmz, report, _, source, _, _ = assessment.metrics
    timestamps = {
        kmz.timestamp,
        report.timestamp,
        source.target.when if source.target else None,
        *(output.modified for output in (files.kmz, files.report)),
    }
    deadlines = []
    for timestamp in timestamps:
        if timestamp is None:
            continue
        if timestamp > now:
            deadlines.append(timestamp)
        else:
            for elapsed in (
                datetime.timedelta(hours=5),
                datetime.timedelta(hours=6, microseconds=1),
            ):
                boundary = timestamp + elapsed
                if boundary > now:
                    deadlines.append(boundary)
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
    """Reuse evidence classifications and health independently of advancing wall time.

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
    reusable = (
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
        reusable.evidence_changes_at
        if reusable
        else evidence_deadline(observations, now)
    )
    assessment = peri_scribe.monitor.status.project(
        history,
        files,
        now,
        observations=observations,
        previous=reusable.assessment if reusable else None,
    )
    changes_at = min(
        (
            value
            for value in (
                evidence_changes_at,
                policy_deadline(history, files, assessment, now),
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
        assessment=assessment,
        changes_at=changes_at,
        evidence_changes_at=evidence_changes_at,
    )
