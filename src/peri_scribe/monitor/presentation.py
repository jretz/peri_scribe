"""Rich formatting adapts plain monitor data for the terminal."""

import datetime
import json

import rich.text

import peri_scribe.monitor.events
import peri_scribe.monitor.model
import peri_scribe.monitor.storage
import peri_scribe.monitor.theme
from measurement_units import units


PHASE_STYLES = {
    peri_scribe.monitor.model.Status.WAITING: (
        "·",
        f"dim {peri_scribe.monitor.theme.MUTED}",
    ),
    peri_scribe.monitor.model.Status.ACTIVE: (
        ">",
        f"bold {peri_scribe.monitor.theme.CYAN}",
    ),
    peri_scribe.monitor.model.Status.COMPLETED: ("✓", peri_scribe.monitor.theme.GREEN),
    peri_scribe.monitor.model.Status.FAILED: (
        "x",
        f"bold {peri_scribe.monitor.theme.RED}",
    ),
    peri_scribe.monitor.model.Status.STOPPED: ("?", peri_scribe.monitor.theme.YELLOW),
}


def phase_label(view: peri_scribe.monitor.model.PhaseView) -> rich.text.Text:
    """Render every catalogue phase through the same state-based presentation.

    Args:
        view: A presentation-neutral phase instance.

    Returns:
        Literal text with state styling and recorded elapsed time.
    """
    symbol, style = PHASE_STYLES[view.status]
    segment = view.path[-1]
    label = f"{symbol} {segment.phase}"
    if segment.branch:
        label += f" · {segment.branch}"
    if view.status in {
        peri_scribe.monitor.model.Status.COMPLETED,
        peri_scribe.monitor.model.Status.FAILED,
    }:
        label += f"  {view.duration.m_as('seconds'):.1f}s"
    return rich.text.Text(label, style=style)


def event_cells(
    event: peri_scribe.monitor.events.Event,
) -> tuple[str, rich.text.Text, rich.text.Text]:
    """Keep untrusted log content literal while using severity as a visual cue.

    Args:
        event: The selected run's record.

    Returns:
        Timestamp, styled severity, and a concise event summary.
    """
    when = event.timestamp.astimezone().strftime("%H:%M:%S") if event.timestamp else "—"
    style = {
        "debug": f"dim {peri_scribe.monitor.theme.MUTED}",
        "warning": peri_scribe.monitor.theme.YELLOW,
        "error": peri_scribe.monitor.theme.RED,
        "critical": f"bold {peri_scribe.monitor.theme.RED}",
    }.get(event.level, "")
    context = next(
        (
            event.fields[name]
            for name in ("phase", "fire", "feed", "source")
            if name in event.fields
        ),
        "",
    )
    message = event.message + (f" · {context}" if context else "")
    return (
        when,
        rich.text.Text(event.level.upper(), style=style),
        rich.text.Text(message),
    )


def run_cells(
    run: peri_scribe.monitor.model.Run,
) -> tuple[str, rich.text.Text, rich.text.Text]:
    """Show run outcomes and gate reasons without hiding successful skipped invocations.

    Args:
        run: A retained command invocation.

    Returns:
        Start time, command name, and its latest outcome.
    """
    started = next(
        (
            event.timestamp
            for event in peri_scribe.monitor.model.evidence(run)
            if event.timestamp
        ),
        None,
    )
    when = started.astimezone().strftime("%m/%d %H:%M:%S") if started else "Unknown"
    reason = next(
        (
            str(event.fields.get("reason", ""))
            for event in reversed(peri_scribe.monitor.model.evidence(run))
            if event.message == "Publication gate skipped"
        ),
        "",
    )
    return (
        when,
        rich.text.Text(run.command),
        rich.text.Text(f"{run.status} · {reason}" if reason else str(run.status)),
    )


def details(event: peri_scribe.monitor.events.Event) -> str:
    """Expose every original field, including full tracebacks, for inspection.

    Args:
        event: The selected event.

    Returns:
        Readable JSON preserving the event's structured fields.
    """
    return json.dumps(dict(event.fields), indent=2, ensure_ascii=False)


def report_heading(report: peri_scribe.monitor.storage.Report) -> str:
    """Keep the report's actual filesystem timestamp distinct from viewing time.

    Args:
        report: The current stable report snapshot.

    Returns:
        The local modification time or the reason the file is unavailable.
    """
    if report.error:
        return report.error
    if report.modified is None:
        return "Waiting for report"
    return report.modified.strftime("Report written %Y-%m-%d %H:%M:%S %Z (UTC%z)")


def activity(run: peri_scribe.monitor.model.Run, now: datetime.datetime) -> str:
    """Show elapsed silence without inferring that a quiet process has stopped.

    Args:
        run: The selected command's observed state.
        now: The current aware time.

    Returns:
        A concise command status and age of its last timestamped event.
    """
    latest = next(
        (
            event.timestamp
            for event in reversed(peri_scribe.monitor.model.evidence(run))
            if event.timestamp
        ),
        None,
    )
    age = max(0, (now - latest).total_seconds()) * units.seconds if latest else None
    suffix = f" · last event {age.m_as('seconds'):.0f}s ago" if age is not None else ""
    return f"{run.command} · {run.status}{suffix}"
