"""Independent timestamped scenarios for health and historical navigation."""

import datetime

import peri_scribe.monitor.history
import peri_scribe.monitor.status
import peri_scribe.phases
import tests.helpers.factories.peri_scribe.monitor.events


NOW = datetime.datetime(2026, 9, 16, 9, tzinfo=datetime.UTC)


def record(
    message: str,
    *,
    phase: str = "",
    when: datetime.datetime = NOW,
    run_id: str = "run-1",
    **fields: object,
) -> dict[str, object]:
    """Keep scenario timestamps explicit and independent of the machine clock.

    Args:
        message: The observation to record.
        phase: A dot-separated execution path.
        when: The observation timestamp.
        run_id: The owning command.
        fields: Other structured evidence.

    Returns:
        One serializable record.
    """
    return tests.helpers.factories.peri_scribe.monitor.events.record(
        message,
        path=tuple(
            peri_scribe.phases.Segment(phase=name) for name in phase.split(".") if name
        ),
        run_id=run_id,
        timestamp=when.isoformat(),
        **fields,
    )


def history(*records: dict[str, object]) -> peri_scribe.monitor.history.History:
    """Build real compact history from a scenario's independent records.

    Args:
        records: Chronological observations.

    Returns:
        Health evidence at the fixed observation time.
    """
    return peri_scribe.monitor.history.append(
        peri_scribe.monitor.history.History(),
        records,
        NOW,
    )


def finished(
    phase: str,
    *,
    run_id: str = "run-1",
    when: datetime.datetime = NOW,
) -> dict[str, object]:
    """A completed phase supplies evidence that the work actually succeeded.

    Args:
        phase: The completed execution path.
        run_id: Its owning command.
        when: Its completion time.

    Returns:
        One successful phase completion record.
    """
    return record(
        "Finished phase",
        phase=phase,
        run_id=run_id,
        when=when,
        status="completed",
    )


def failed_run(
    *,
    when: datetime.datetime = NOW,
    run_id: str = "failed",
    phase: str = "reports.prepare-fire-histories",
) -> tuple[dict[str, object], ...]:
    """Represent one exception propagating through a phase, stage, and command.

    Args:
        when: The failure timestamp.
        run_id: Its command identity.
        phase: The originating execution path.

    Returns:
        A complete failed run with one underlying exception.
    """
    return (
        record("Starting command", when=when, run_id=run_id, command="run"),
        record("Starting phase", when=when, run_id=run_id, phase=phase),
        record(
            "Finished phase",
            when=when,
            run_id=run_id,
            phase=phase,
            status="failed",
            exception="ValueError: invalid geometry",
            level="error",
        ),
        record(
            "Finished phase",
            when=when,
            run_id=run_id,
            phase=phase.split(".", maxsplit=1)[0],
            status="failed",
            exception="ValueError: invalid geometry",
            level="error",
        ),
        record(
            "Finished command",
            when=when,
            run_id=run_id,
            command="run",
            status="failed",
            exception="ValueError: invalid geometry",
            level="error",
        ),
    )


def files() -> peri_scribe.monitor.status.Files:
    """Supply current artifact timestamps for scenarios about other health signals.

    Returns:
        Two present, fresh artifacts.
    """
    output = peri_scribe.monitor.status.Output(modified=NOW)
    return peri_scribe.monitor.status.Files(kmz=output, report=output)


def report_build(
    *,
    phase: str = "reports",
    report_age: datetime.timedelta = datetime.timedelta(minutes=2),
) -> peri_scribe.monitor.history.History:
    """Represent the normal interval between publishing a KMZ and its new report.

    Args:
        phase: Current report work, or an empty string before the stage starts.
        report_age: The age of the previously successful report.

    Returns:
        Complete history with current sources, an updated KMZ, and unfinished reports.
    """
    return history(
        record(
            "Starting command",
            command="run",
            when=NOW - datetime.timedelta(days=3),
        ),
        finished("reports", when=NOW - report_age),
        record(
            "Finished command",
            command="run",
            status="completed",
            when=NOW - report_age,
        ),
        record(
            "Starting command",
            command="run",
            run_id="building",
            when=NOW - datetime.timedelta(minutes=1),
        ),
        finished(
            "fetch",
            run_id="building",
            when=NOW - datetime.timedelta(minutes=1),
        ),
        finished(
            "kmz",
            run_id="building",
            when=NOW - datetime.timedelta(seconds=30),
        ),
        *((record("Starting phase", phase=phase, run_id="building"),) if phase else ()),
    )
