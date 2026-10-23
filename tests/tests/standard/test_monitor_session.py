"""Terminal assertions wait for real preparation and its deferred cursor layout."""

import asyncio

import pytest
import textual.widgets

import peri_scribe.monitor.display
import peri_scribe.monitor.history
import peri_scribe.monitor.status_widgets
import peri_scribe.monitor.widgets
import tests.helpers.doubles.peri_scribe.monitor.synchronization
import tests.helpers.doubles.peri_scribe.monitor.tasks
import tests.helpers.factories.peri_scribe.monitor.events
import tests.helpers.factories.peri_scribe.monitor.status
import tests.helpers.fixtures.peri_scribe.monitor.application
import tests.helpers.textual


@pytest.mark.asyncio
async def test_pause_clock_waits_for_cancellation_cleanup(
    monitor_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
) -> None:
    controller = monitor_session.app.controller
    cancellation = (
        tests.helpers.doubles.peri_scribe.monitor.synchronization.Cancellation()
    )
    cosmetic = asyncio.create_task(cancellation.wait())
    controller.cosmetic_task = cosmetic
    pausing = None
    try:
        with tests.helpers.doubles.peri_scribe.monitor.synchronization.release_on_exit(
            cancellation.released,
        ):
            await asyncio.wait_for(cancellation.started.wait(), 5)
            pausing = asyncio.create_task(
                tests.helpers.fixtures.peri_scribe.monitor.application.pause_clock(
                    monitor_session.app,
                ),
            )
            await asyncio.wait_for(cancellation.cancelling.wait(), 5)
            assert not pausing.done()
            assert controller.cosmetic_task is cosmetic
    finally:
        await asyncio.wait_for(pausing if pausing is not None else cosmetic, 5)
    assert cosmetic.cancelled()
    assert controller.cosmetic_task is None


@pytest.mark.asyncio
async def test_session_settle_waits_for_filter_preparation(
    monitor_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = monitor_session
    tests.helpers.factories.peri_scribe.monitor.events.write_log(
        session.directory,
        tests.helpers.factories.peri_scribe.monitor.events.record(
            "Starting command",
            command="run",
        ),
        tests.helpers.factories.peri_scribe.monitor.events.record("Selected event"),
        tests.helpers.factories.peri_scribe.monitor.events.record("Other event"),
    )
    await session.app.refresh_files()
    await session.show_view("logs")
    stream = session.app.query_one("#log-stream", peri_scribe.monitor.widgets.Stream)
    table = stream.query_one(peri_scribe.monitor.widgets.EventTable)
    original_count = table.row_count
    preparation = tests.helpers.doubles.peri_scribe.monitor.tasks.PausedCall(
        function=peri_scribe.monitor.display.prepare,
    )
    monkeypatch.setattr(peri_scribe.monitor.display, "prepare", preparation)
    stream.query_one(textual.widgets.Input).value = "Selected"
    settling = asyncio.create_task(session.settle())
    try:
        assert await asyncio.to_thread(preparation.started.wait, 5)
        await session.refresh()
        assert table.row_count == original_count
        assert not settling.done()
    finally:
        preparation.release.set()
        await asyncio.wait_for(settling, 5)
    assert [event.message for event in session.app.rows[table].values()] == [
        "Selected event",
    ]
    assert table.cursor_row == 0
    assert table.scroll_offset.y == 0


@pytest.mark.asyncio
async def test_session_show_view_waits_for_tab_preparation_and_cursor_layout(
    scrolling_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = scrolling_session
    activation = tests.helpers.doubles.peri_scribe.monitor.synchronization.Activation(
        operation=session.app.controller.activate,
    )
    monkeypatch.setattr(session.app.controller, "activate", activation.activate)
    navigation = asyncio.create_task(session.show_view("logs"))
    try:
        await asyncio.wait_for(activation.started.wait(), 5)
        await session.refresh()
        assert not navigation.done()
    finally:
        activation.released.set()
        await asyncio.wait_for(navigation, 5)
    table = session.app.query_one(
        "#log-stream .events",
        peri_scribe.monitor.widgets.EventTable,
    )
    assert table.cursor_row == table.row_count - 1
    assert table.max_scroll_y > 0
    assert table.scroll_offset.y == table.max_scroll_y


@pytest.mark.parametrize("control", ["keyboard", "row"])
@pytest.mark.asyncio
async def test_evidence_completed_waits_for_status_navigation(
    monitor_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
    evidence_completed: asyncio.Event,
    monkeypatch: pytest.MonkeyPatch,
    control: str,
) -> None:
    session = monitor_session
    tests.helpers.factories.peri_scribe.monitor.events.write_log(
        session.directory,
        *tests.helpers.factories.peri_scribe.monitor.status.failed_run(run_id="first"),
        *tests.helpers.factories.peri_scribe.monitor.status.failed_run(run_id="latest"),
    )
    await session.app.refresh_files()
    session.app.following = False
    session.app.selected_run = "first"
    await session.show_view("status")
    reading = tests.helpers.doubles.peri_scribe.monitor.tasks.PausedCall(
        function=peri_scribe.monitor.history.load_run,
    )
    monkeypatch.setattr(peri_scribe.monitor.history, "load_run", reading)
    if control == "keyboard":
        await tests.helpers.textual.invoke(
            session.app.query_one("#status-failure").focus,
        )
        navigating = asyncio.create_task(session.pilot.press("enter"))
    else:
        pane = session.app.query_one(peri_scribe.monitor.status_widgets.StatusPane)
        table = pane.query_one("#status-exceptions", textual.widgets.DataTable)
        navigating = asyncio.create_task(
            tests.helpers.textual.invoke(
                pane.select_evidence,
                textual.widgets.DataTable.RowSelected(table, 0, next(iter(table.rows))),
            ),
        )
    try:
        assert await asyncio.to_thread(reading.started.wait, 5)
        assert not evidence_completed.is_set()
        assert session.app.current_run().identifier == "first"
    finally:
        reading.release.set()
        await asyncio.wait_for(navigating, 5)
    await asyncio.wait_for(evidence_completed.wait(), 5)
    await session.settle()
    assert session.app.current_run().identifier == "latest"
    assert (
        session.app.query_one("#views", textual.widgets.TabbedContent).active
        == "pipeline"
    )
