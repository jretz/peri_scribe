"""Prepare terminal content independently of widget lifetimes and mutation."""

import dataclasses
import typing

import peri_scribe.monitor.events
import peri_scribe.monitor.model
import peri_scribe.monitor.presentation
import peri_scribe.phases


if typing.TYPE_CHECKING:
    import rich.text


@dataclasses.dataclass(frozen=True, kw_only=True)
class Filter:
    """Capture controls before a worker prepares an independent display snapshot."""

    minimum_level: str
    query: str
    path: peri_scribe.phases.Path = ()


@dataclasses.dataclass(frozen=True, kw_only=True)
class EventRow:
    """Keep row identity, inspection evidence, and formatted cells together."""

    event: peri_scribe.monitor.events.Event
    cells: tuple[str, rich.text.Text, rich.text.Text]


@dataclasses.dataclass(frozen=True, kw_only=True)
class RunRow:
    """Preserve the run associated with each prepared history row."""

    run: peri_scribe.monitor.model.Run
    cells: tuple[str, rich.text.Text, rich.text.Text]


@dataclasses.dataclass(frozen=True, kw_only=True)
class Records:
    """One prepared result contains no references to live terminal widgets."""

    phases: tuple[tuple[peri_scribe.monitor.model.PhaseState, rich.text.Text], ...]
    reasons: tuple[str, ...]
    pipeline: tuple[EventRow, ...]
    logs: tuple[EventRow, ...]
    runs: tuple[RunRow, ...]


def event_rows(
    run: peri_scribe.monitor.model.Run,
    filtering: Filter,
) -> tuple[EventRow, ...]:
    """Apply one captured filter without reading controls from a worker.

    Args:
        run: The immutable run being inspected.
        filtering: Severity, text, and execution scope captured on the UI thread.

    Returns:
        Complete rows in the domain filter's stable event order.
    """
    return tuple(
        EventRow(event=event, cells=peri_scribe.monitor.presentation.event_cells(event))
        for event in peri_scribe.monitor.model.filter_events(
            run,
            minimum_level=filtering.minimum_level,
            query=filtering.query,
            path=filtering.path,
        )
    )


def prepare(
    state: peri_scribe.monitor.model.State,
    run: peri_scribe.monitor.model.Run,
    branches: peri_scribe.phases.Branches,
    pipeline: Filter,
    logs: Filter,
) -> Records:
    """Prepare diagnostic content while the terminal can continue processing input.

    Args:
        state: Current bounded run history.
        run: The immutable selected run, possibly from an older snapshot.
        branches: The configured phase catalogue.
        pipeline: Captured Pipeline controls.
        logs: Captured Logs controls.

    Returns:
        Formatted phases, events, and runs for one consistent request.
    """
    hierarchy = peri_scribe.monitor.model.phase_tree(run, branches)
    return Records(
        phases=tuple(
            (phase, peri_scribe.monitor.presentation.phase_label(phase))
            for phase in hierarchy.phases
        ),
        reasons=(
            *hierarchy.reasons,
            *(
                f"Trimmed {omission.path[-1].phase}: {omission.reason}"
                for omission in hierarchy.omissions
            ),
        ),
        pipeline=event_rows(run, pipeline),
        logs=event_rows(run, logs),
        runs=tuple(
            RunRow(run=item, cells=peri_scribe.monitor.presentation.run_cells(item))
            for item in reversed(state.runs)
        ),
    )
