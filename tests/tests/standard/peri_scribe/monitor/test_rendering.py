"""Incremental diagnostic updates preserve the identity of selectable evidence."""

import asyncio

import pytest
import rich.json
import textual.widgets

import peri_scribe.monitor.display
import peri_scribe.monitor.model
import peri_scribe.monitor.rendering
import peri_scribe.monitor.status
import peri_scribe.monitor.storage
import peri_scribe.monitor.widgets
import peri_scribe.phases
import tests.helpers.doubles.peri_scribe.monitor.rendering
import tests.helpers.doubles.peri_scribe.monitor.tasks
import tests.helpers.factories.peri_scribe.monitor.events
import tests.helpers.factories.peri_scribe.monitor.rendering
import tests.helpers.fixtures.peri_scribe.monitor.controller


@pytest.mark.asyncio
async def test_apply_records_preserves_table_evidence_during_replacement(
    initial_monitor: tests.helpers.fixtures.peri_scribe.monitor.controller.Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = initial_monitor.app
    await app.controller.activate("logs")
    pipeline = app.query_one(
        "#pipeline-stream",
        peri_scribe.monitor.widgets.Stream,
    ).query_one(peri_scribe.monitor.widgets.EventTable)
    logs = app.query_one(
        "#log-stream",
        peri_scribe.monitor.widgets.Stream,
    ).query_one(peri_scribe.monitor.widgets.EventTable)
    key = next(iter(logs.rows))
    original_event = app.rows[logs][str(key.value)]
    queued_selection = textual.widgets.DataTable.RowSelected(logs, 0, key)
    prepared = tests.helpers.factories.peri_scribe.monitor.rendering.records(
        "replacement",
    )
    assert prepared.pipeline[0].event.sequence == original_event.sequence
    notice = tests.helpers.doubles.peri_scribe.monitor.rendering.RowNotice(
        operation=pipeline.add_row,
    )
    monkeypatch.setattr(pipeline, "add_row", notice.add_row)
    app.controller.generation += 1
    updating = asyncio.create_task(
        peri_scribe.monitor.rendering.apply_records(
            app,
            prepared,
            app.controller.generation,
        ),
    )
    try:
        await notice.added.wait()
        assert not updating.done()
        assert 0 < pipeline.row_count < len(prepared.pipeline)
        assert key in logs.rows
        app.select_row(queued_selection)
        details = app.query_one("#details", textual.widgets.Static).content
        assert isinstance(details, rich.json.JSON)
        assert str(original_event.fields["run_id"]) in details.text.plain
        assert "replacement" not in details.text.plain
    finally:
        await updating
    replacement_selection = textual.widgets.DataTable.RowSelected(
        logs,
        1,
        tuple(logs.rows)[1],
    )
    app.select_row(replacement_selection)
    details = app.query_one("#details", textual.widgets.Static).content
    assert isinstance(details, rich.json.JSON)
    assert "Replacement event 1" in details.text.plain
    app.select_row(queued_selection)
    selected = app.query_one("#details", textual.widgets.Static).content
    assert isinstance(selected, rich.json.JSON)
    assert selected.text.plain == details.text.plain


@pytest.mark.parametrize("interruption", ["live", "close"])
@pytest.mark.asyncio
async def test_inspect_evidence_abandons_obsolete_completion(
    initial_monitor: tests.helpers.fixtures.peri_scribe.monitor.controller.Session,
    monkeypatch: pytest.MonkeyPatch,
    interruption: str,
) -> None:
    app = initial_monitor.app
    await app.controller.activate("pipeline")
    run = peri_scribe.monitor.model.append_records(
        peri_scribe.monitor.model.State(sequence=100),
        (
            tests.helpers.factories.peri_scribe.monitor.events.record(
                "Historical command evidence",
                run_id="historical",
            ),
        ),
    ).runs[0]
    target = peri_scribe.monitor.status.Target(run=run.identifier, event=run.events[0])
    preparation = tests.helpers.doubles.peri_scribe.monitor.tasks.PausedCall(
        function=peri_scribe.monitor.display.prepare,
    )
    monkeypatch.setattr(peri_scribe.monitor.display, "prepare", preparation)
    inspection = asyncio.create_task(
        peri_scribe.monitor.rendering.inspect_evidence(app, run, target),
    )
    closing = None
    try:
        assert await asyncio.to_thread(preparation.started.wait, 5)
        if interruption == "live":
            app.action_live()
        else:
            closing = asyncio.create_task(app.controller.close())
            await app.controller.session.owner.stopped.wait()
    finally:
        preparation.release.set()
    await inspection
    if closing is not None:
        await closing
    else:
        assert app.following
        assert app.current_run().identifier == "run-1"
    assert not isinstance(
        app.query_one("#details", textual.widgets.Static).content,
        rich.json.JSON,
    )


@pytest.mark.parametrize("interruption", ["obsolete", "close"])
@pytest.mark.asyncio
async def test_apply_records_stops_batches_after_authorization_changes(
    initial_monitor: tests.helpers.fixtures.peri_scribe.monitor.controller.Session,
    monkeypatch: pytest.MonkeyPatch,
    interruption: str,
) -> None:
    app = initial_monitor.app
    await app.controller.activate("pipeline")
    pipeline = app.query_one(
        "#pipeline-stream",
        peri_scribe.monitor.widgets.Stream,
    ).query_one(peri_scribe.monitor.widgets.EventTable)
    logs = app.query_one(
        "#log-stream",
        peri_scribe.monitor.widgets.Stream,
    ).query_one(peri_scribe.monitor.widgets.EventTable)
    original_logs = tuple(logs.rows)
    prepared = tests.helpers.factories.peri_scribe.monitor.rendering.records(
        "replacement",
    )
    notice = tests.helpers.doubles.peri_scribe.monitor.rendering.RowNotice(
        operation=pipeline.add_row,
    )
    monkeypatch.setattr(pipeline, "add_row", notice.add_row)
    updating = asyncio.create_task(
        peri_scribe.monitor.rendering.apply_records(
            app,
            prepared,
            app.controller.generation,
        ),
    )
    try:
        await notice.added.wait()
        if interruption == "obsolete":
            app.controller.generation += 1
        else:
            await app.controller.close()
    finally:
        await updating
    assert 0 < pipeline.row_count < len(prepared.pipeline)
    assert tuple(logs.rows) == original_logs


@pytest.mark.asyncio
async def test_apply_records_clears_unavailable_phase_selection(
    initial_monitor: tests.helpers.fixtures.peri_scribe.monitor.controller.Session,
) -> None:
    app = initial_monitor.app
    app.selected_phase = (peri_scribe.phases.Segment(phase="retired-phase"),)
    prepared = tests.helpers.factories.peri_scribe.monitor.rendering.records(
        "replacement",
        count=1,
    )
    await peri_scribe.monitor.rendering.apply_records(
        app,
        prepared,
        app.controller.generation,
    )
    assert app.selected_phase == ()


@pytest.mark.asyncio
async def test_apply_records_preserves_phase_cursor_across_replacement(
    initial_monitor: tests.helpers.fixtures.peri_scribe.monitor.controller.Session,
) -> None:
    app = initial_monitor.app
    await app.controller.activate("pipeline")
    app.action_view("pipeline")
    tree = app.query_one("#phase-tree", textual.widgets.Tree)
    path, previous = next(iter(app.tree_nodes.items()))
    tree.move_cursor(previous)
    await initial_monitor.refresh()
    filtering = peri_scribe.monitor.display.Filter(minimum_level="debug", query="")
    prepared = peri_scribe.monitor.display.prepare(
        app.controller.snapshot.records,
        app.current_run(),
        app.branches,
        filtering,
        filtering,
    )
    await peri_scribe.monitor.rendering.apply_records(
        app,
        prepared,
        app.controller.generation,
    )
    await initial_monitor.refresh()
    assert tree.cursor_node is not previous
    assert tree.cursor_node is app.tree_nodes[path]


@pytest.mark.asyncio
async def test_apply_report_preserves_checkpoint_after_viewer_removal(
    initial_monitor: tests.helpers.fixtures.peri_scribe.monitor.controller.Session,
) -> None:
    app = initial_monitor.app
    previous = app.rendered_report
    await app.query_one("#report-viewer").remove()
    await peri_scribe.monitor.rendering.apply_report(
        app,
        peri_scribe.monitor.storage.Report(content="# Unpresented content"),
    )
    assert app.rendered_report is previous
