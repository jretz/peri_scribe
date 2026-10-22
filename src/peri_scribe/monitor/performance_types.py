"""Name performance series from the work and execution mode recorded for each run.

Algorithm reasoning and contracts:
[Charts](../../../docs/algorithms/monitor-presentation.md#performance-charts)
"""

import collections.abc

import peri_scribe.monitor.events
import peri_scribe.monitor.model
import peri_scribe.pipeline_stages


STAGES = tuple(stage.value for stage in peri_scribe.pipeline_stages.Stage)
DERIVED_STAGES = frozenset(STAGES[1:])


def parameters(
    events: tuple[peri_scribe.monitor.events.Event, ...],
) -> dict[str, object]:
    """Use supplied command arguments without mistaking a download policy for a run.

    Args:
        events: One invocation's structural evidence in occurrence order.

    Returns:
        Supplied command options, or an empty mapping when their record is unavailable.
    """
    result: dict[str, object] = {}
    for event in events:
        values = event.fields.get("parameters")
        if event.message == "Starting command" and isinstance(
            values,
            collections.abc.Mapping,
        ):
            result.update(values)
    return result


def selected_stages(
    events: tuple[peri_scribe.monitor.events.Event, ...],
    options: collections.abc.Mapping[str, object],
) -> tuple[str, ...]:
    """Prefer the executed plan while retaining explicit selection from older logs.

    Args:
        events: One invocation's structural evidence in occurrence order.
        options: Supplied command arguments.

    Returns:
        Its known selected stages, or an empty tuple when selection is unavailable.
    """
    for event in reversed(events):
        stages = event.fields.get("stages")
        if (
            event.message == "Planned phases"
            and isinstance(stages, list)
            and stages
            and all(isinstance(stage, str) and stage in STAGES for stage in stages)
        ):
            return tuple(stages)
    only = options.get("only_stage")
    if isinstance(only, str) and only in STAGES:
        return (only,)
    if not any(options.get(name) is not None for name in ("from_stage", "to_stage")):
        return ()
    first = options.get("from_stage")
    last = options.get("to_stage")
    first = STAGES[0] if first is None else first
    last = STAGES[-1] if last is None else last
    if not isinstance(first, str) or not isinstance(last, str):
        return ()
    if first not in STAGES or last not in STAGES:
        return ()
    start, end = STAGES.index(first), STAGES.index(last)
    return STAGES[start : end + 1]


def collection_type(
    events: tuple[peri_scribe.monitor.events.Event, ...],
    selected: tuple[str, ...],
    executed: set[str],
) -> str | None:
    """Keep requested collection and deferred output work in separate series.

    Args:
        events: One invocation's structural evidence.
        selected: Its known selected stages.
        executed: Observed top-level pipeline stages.

    Returns:
        The collection mode, or None when the evidence describes other work.
    """
    if selected == ("fetch",):
        return "Fetch only"
    if any(event.message == "Publication gate skipped" for event in events):
        return "Fetch only · publication deferred"
    if executed == {"fetch"}:
        unchanged = any(
            event.message == "Skipped phases"
            and not event.path
            and isinstance(stages := event.fields.get("phases"), list)
            and any(
                isinstance(stage, str) and stage in DERIVED_STAGES for stage in stages
            )
            for event in events
        )
        return "Fetch only · unchanged" if unchanged else "Fetch only"
    return None


def run_type(run: peri_scribe.monitor.model.Run) -> str:
    """Separate collection, conditional builds, forced builds, and partial selections.

    Args:
        run: One immutable invocation with its retained structural evidence.

    Returns:
        A concise series name. Missing mode evidence retains the command name rather
        than inferring work from its successful command endpoint alone.
    """
    if run.command != "run":
        return run.command
    events = peri_scribe.monitor.model.evidence(run)
    if any(
        event.message == "Another run owns this year; skipping invocation"
        for event in events
    ):
        return "Skipped · another run active"
    options = parameters(events)
    if options.get("list_stages") is True:
        return "List stages"
    selected = selected_stages(events, options)
    executed = {
        event.path[0].phase
        for event in events
        if event.message in {"Starting phase", "Finished phase"}
        and len(event.path) == 1
        and event.path[0].phase in STAGES
    }
    collection = collection_type(events, selected, executed)
    if collection is not None:
        return collection
    unconditional = options.get("unconditional") is True or any(
        event.message == "Required rebuild completed"
        and event.fields.get("unconditional") is True
        for event in events
    )
    if not (
        executed & DERIVED_STAGES or set(selected) & DERIVED_STAGES or unconditional
    ):
        return run.command
    label = "Unconditional build" if unconditional else "Conditional build"
    if selected and selected != STAGES:
        scope = (
            f"{selected[0]} only"
            if len(selected) == 1
            else f"{selected[0]} to {selected[-1]}"
        )
        label += f" · {scope}"
    return label
