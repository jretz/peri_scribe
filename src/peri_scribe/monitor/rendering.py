"""Apply prepared terminal content without owning evidence reads or calculations."""

import asyncio
import dataclasses
import datetime

import rich.json
import textual.widgets

import peri_scribe.monitor.display
import peri_scribe.monitor.model
import peri_scribe.monitor.presentation
import peri_scribe.monitor.status
import peri_scribe.monitor.storage
import peri_scribe.monitor.terminal_contract
import peri_scribe.monitor.theme
import peri_scribe.monitor.widgets


async def apply_records(
    app: peri_scribe.monitor.terminal_contract.Host,
    prepared: peri_scribe.monitor.display.Records,
    generation: int,
) -> None:
    """Apply prepared rows in bounded batches while preserving browsing positions.

    Args:
        app: The mounted terminal receiving prepared content.
        prepared: Widget-independent content from one preparation request.
        generation: The controller revision that still authorizes this update.
    """
    tree = app.query_one("#phase-tree", textual.widgets.Tree)
    previous = tree.scroll_offset
    expanded = {path: node.is_expanded for path, node in app.tree_nodes.items()}
    cursor = tree.cursor_node
    cursor_path = cursor.data.path if cursor is not None and cursor.data else ()
    tree.clear()
    app.tree_nodes.clear()
    for phase, label in prepared.phases:
        parent = app.tree_nodes.get(phase.path[:-1], tree.root)
        app.tree_nodes[phase.path] = parent.add(
            label,
            data=phase,
            expand=expanded.get(phase.path, True),
        )
    tree.root.expand()
    if cursor_path in app.tree_nodes:
        tree.call_after_refresh(tree.move_cursor, app.tree_nodes[cursor_path])
    tree.scroll_to(previous.x, previous.y, animate=False)
    if app.selected_phase not in app.tree_nodes:
        app.selected_phase = ()
    app.query_one("#decisions", textual.widgets.Static).update(
        "\n".join(prepared.reasons),
    )
    for identifier, rows in (
        ("pipeline-stream", prepared.pipeline),
        ("log-stream", prepared.logs),
    ):
        stream = app.query_one(
            f"#{identifier}",
            peri_scribe.monitor.widgets.Stream,
        )
        table = stream.query_one(peri_scribe.monitor.widgets.EventTable)
        row = table.cursor_row
        position = table.scroll_offset
        table.clear()
        app.rows[table] = {}
        table.row_tints = tuple(
            peri_scribe.monitor.theme.EVENT_TINTS.get(item.event.level) for item in rows
        )
        for index, item in enumerate(rows):
            if index and index % 128 == 0:
                await asyncio.sleep(0)
                if (
                    not app.controller.available()
                    or generation != app.controller.generation
                ):
                    return
            key = f"{generation}:{item.event.sequence}"
            app.rows[table][key] = item.event
            table.add_row(*item.cells, key=key)
        table.move_cursor(row=max(0, len(rows) - 1) if app.following else row)
        if not app.following:
            table.scroll_to(position.x, position.y, animate=False)
    table = app.query_one("#run-table", peri_scribe.monitor.widgets.TintedTable)
    row = table.cursor_row
    table.clear()
    table.row_tints = tuple(
        peri_scribe.monitor.theme.RUN_TINTS.get(item.run.status)
        for item in prepared.runs
    )
    for item in prepared.runs:
        table.add_row(*item.cells, key=item.run.identifier)
    table.move_cursor(row=row)


def show_activity(app: peri_scribe.monitor.terminal_contract.Host) -> None:
    """Format the current inspection independently of live health evidence."""
    pending = app.controller.snapshot.records.sequence - app.visible_state.sequence
    description = peri_scribe.monitor.presentation.activity(
        app.current_run(),
        datetime.datetime.now(datetime.UTC),
    )
    mode = "FOLLOW" if app.following else f"PAUSED · {pending} new events"
    peri_scribe.monitor.widgets.update_content(
        app.query_one("#activity", textual.widgets.Static),
        "LIVE STATUS · select an observation to inspect its Pipeline evidence"
        if app.query_one("#views", textual.widgets.TabbedContent).active == "status"
        else f"{mode} · {description}",
        layout=False,
    )


async def apply_report(
    app: peri_scribe.monitor.terminal_contract.Host,
    report: peri_scribe.monitor.storage.Report,
) -> None:
    """Populate delivered Markdown while preserving its reading position.

    Args:
        app: The mounted terminal receiving prepared content.
        report: The immutable content authorized by the controller.
    """
    if not app.query("#report-viewer"):
        return
    app.query_one("#report-time", textual.widgets.Static).update(
        f"{app.report_path.name}\n"
        f"{peri_scribe.monitor.presentation.report_heading(report)}",
    )
    viewer = app.query_one("#report-viewer", textual.widgets.MarkdownViewer)
    position = viewer.scroll_offset
    await viewer.document.update(report.content)
    if app.controller.available() and report == app.controller.snapshot.report:
        app.rendered_report = report
        if viewer.is_attached:
            viewer.scroll_to(position.x, position.y, animate=False)


async def inspect_evidence(
    app: peri_scribe.monitor.terminal_contract.Host,
    run: peri_scribe.monitor.model.Run,
    target: peri_scribe.monitor.status.Target,
) -> None:
    """Focus resolved evidence without involving widgets in its retrieval.

    Args:
        app: The mounted terminal receiving prepared content.
        run: The complete immutable command supplied by the session.
        target: The original observation selected from health evidence.
    """
    app.following = False
    app.selected_run = run.identifier
    app.visible_state = dataclasses.replace(
        app.controller.snapshot.records,
        runs=(
            *tuple(
                item
                for item in app.controller.snapshot.records.runs
                if item.identifier != run.identifier
            ),
            run,
        ),
    )
    selected = next(
        (
            event
            for event in reversed(run.events)
            if event.fields == target.event.fields
        ),
        run.events[-1],
    )
    app.selected_phase = selected.path
    stream = app.query_one("#pipeline-stream", peri_scribe.monitor.widgets.Stream)
    stream.query_one(textual.widgets.Input).value = ""
    stream.query_one(textual.widgets.Select).value = "debug"
    app.action_view("pipeline")
    app.controller.schedule_display(requested=True)
    generation = app.controller.generation
    await app.controller.flush_display()
    if (
        not app.controller.available()
        or generation != app.controller.generation
        or app.current_run() is not run
        or app.following
        or app.selected_phase != selected.path
    ):
        return
    app.query_one("#details", textual.widgets.Static).update(
        rich.json.JSON(peri_scribe.monitor.presentation.details(selected)),
    )
    table = stream.query_one(peri_scribe.monitor.widgets.EventTable)
    table.move_cursor(
        row=table.get_row_index(
            f"{generation}:{selected.sequence}",
        ),
    )
    table.focus()
