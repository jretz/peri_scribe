"""Content preparation respects first paint, shared work, and inspection lifetimes."""

import asyncio
import datetime
import functools
import gc
import typing
import unittest.mock
import weakref

import pytest
import textual.widgets

import peri_scribe.monitor.controller
import peri_scribe.monitor.display
import peri_scribe.monitor.rendering
import peri_scribe.monitor.session
import peri_scribe.monitor.status_widgets
import peri_scribe.monitor.tasks
import peri_scribe.monitor.widgets
import tests.helpers.doubles.peri_scribe.monitor.controller
import tests.helpers.doubles.peri_scribe.monitor.tasks
import tests.helpers.factories.peri_scribe.monitor.events
import tests.helpers.factories.peri_scribe.monitor.status
import tests.helpers.fixtures.peri_scribe.monitor.controller


if typing.TYPE_CHECKING:
    import peri_scribe.monitor.app as monitor_application


@pytest.mark.asyncio
async def test_controller_start_publishes_complete_health_before_other_content(
    initial_monitor: tests.helpers.fixtures.peri_scribe.monitor.controller.Session,
) -> None:
    await initial_monitor.refresh()
    controller = initial_monitor.app.controller
    pane = initial_monitor.app.query_one(peri_scribe.monitor.status_widgets.StatusPane)
    assert controller.snapshot.health is not None
    assert controller.snapshot.history.caught_up
    assert controller.snapshot.history.state.runs
    assert pane.view is not None
    assert not controller.session.follower.started
    assert not controller.session.report_requested
    assert not controller.content
    assert not controller.presented


@pytest.mark.asyncio
async def test_controller_refresh_before_first_paint_keeps_other_content_deferred(
    initial_monitor: tests.helpers.fixtures.peri_scribe.monitor.controller.Session,
) -> None:
    controller = initial_monitor.app.controller
    await controller.flush_display()
    await controller.refresh()
    assert not controller.content
    assert controller.background is None


@pytest.mark.asyncio
async def test_controller_close_before_start_rejects_late_presentation_requests(
    unmounted_monitor: monitor_application.MonitorApp,
) -> None:
    controller = unmounted_monitor.controller
    await controller.close()
    await controller.load_older()
    controller.show_health(tests.helpers.factories.peri_scribe.monitor.status.NOW)
    assert not controller.available()
    assert controller.display_task is None


@pytest.mark.asyncio
async def test_controller_close_settles_presentation_after_domain_shutdown_failure(
    unmounted_monitor: monitor_application.MonitorApp,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = unmounted_monitor.controller
    released = asyncio.Event()
    worker = unittest.mock.AsyncMock(side_effect=released.wait)
    controller.display_task = asyncio.create_task(worker())
    with monkeypatch.context() as patch:
        patch.setattr(
            controller.session,
            "close",
            unittest.mock.AsyncMock(side_effect=RuntimeError("domain shutdown failed")),
        )
        closing = asyncio.create_task(controller.close())
        try:
            await asyncio.sleep(0)
            assert not closing.done()
        finally:
            released.set()
        with pytest.raises(RuntimeError, match="domain shutdown failed"):
            await closing
    assert controller.display_task.done()
    await controller.close()


@pytest.mark.asyncio
async def test_controller_begin_background_prepares_hidden_content_before_navigation(
    initial_monitor: tests.helpers.fixtures.peri_scribe.monitor.controller.Session,
) -> None:
    app = initial_monitor.app
    controller = app.controller
    initial_monitor.begin_background()
    background = controller.background
    assert background is not None
    initial_monitor.begin_background()
    assert controller.background is background
    await background
    assert app.query_one("#views", textual.widgets.TabbedContent).active == "status"
    assert controller.prepared_generation == controller.generation
    expected_rows = 3
    assert all(len(rows) == expected_rows for rows in app.rows.values())
    assert app.rendered_report.content == "# The complete report\n"
    version = controller.session.snapshot.version
    await controller.activate("logs")
    await controller.activate("report")
    assert controller.session.snapshot.version == version


@pytest.mark.parametrize("name", ["pipeline", "report"])
@pytest.mark.asyncio
async def test_controller_activate_before_paint_does_not_start_other_content(
    initial_monitor: tests.helpers.fixtures.peri_scribe.monitor.controller.Session,
    name: str,
) -> None:
    controller = initial_monitor.app.controller
    await controller.activate(name)
    assert not controller.presented
    assert controller.background is None
    assert len(controller.content) == 1
    assert controller.session.records_requested == (name == "pipeline")
    assert controller.session.report_requested == (name == "report")


@pytest.mark.parametrize("name", ["logs", "report"])
@pytest.mark.asyncio
async def test_controller_activate_joins_background_content_already_admitted(
    initial_monitor: tests.helpers.fixtures.peri_scribe.monitor.controller.Session,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
) -> None:
    kind = (
        peri_scribe.monitor.session.RefreshReport
        if name == "report"
        else peri_scribe.monitor.session.RefreshRecords
    )
    gate = tests.helpers.doubles.peri_scribe.monitor.controller.ContentGate(
        operation=peri_scribe.monitor.session.execute,
        kind=kind,
    )
    monkeypatch.setattr(peri_scribe.monitor.session, "execute", gate.execute)
    controller = initial_monitor.app.controller
    initial_monitor.begin_background()
    await gate.started.wait()
    navigation = asyncio.create_task(controller.activate(name))
    try:
        await asyncio.sleep(0)
        assert not navigation.done()
        assert controller.content[kind].priority == (
            peri_scribe.monitor.session.Priority.IMMEDIATE
        )
    finally:
        gate.released.set()
    await navigation
    assert controller.background is not None
    await controller.background
    assert sum(isinstance(request, kind) for request in gate.requests) == 1


@pytest.mark.asyncio
async def test_controller_prepare_content_promotes_queued_work_without_duplicate_read(
    initial_monitor: tests.helpers.fixtures.peri_scribe.monitor.controller.Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = initial_monitor.app.controller
    gate = tests.helpers.doubles.peri_scribe.monitor.controller.ContentGate(
        operation=peri_scribe.monitor.session.execute,
        kind=peri_scribe.monitor.session.RefreshHealth,
    )
    monkeypatch.setattr(peri_scribe.monitor.session, "execute", gate.execute)
    active = asyncio.create_task(
        controller.session.request(peri_scribe.monitor.session.RefreshHealth()),
    )
    await gate.started.wait()
    ordinary = asyncio.create_task(
        controller.session.request(peri_scribe.monitor.session.RefreshReport()),
    )
    background = asyncio.create_task(
        controller.prepare_content(
            peri_scribe.monitor.session.RefreshRecords(),
            priority=peri_scribe.monitor.session.Priority.BACKGROUND,
        ),
    )
    await asyncio.sleep(0)
    navigation = asyncio.create_task(controller.activate("pipeline"))
    try:
        await asyncio.sleep(0)
        expected_pending = 2
        assert len(controller.session.pending) == expected_pending
        assert isinstance(
            controller.session.pending[0].request,
            peri_scribe.monitor.session.RefreshRecords,
        )
    finally:
        gate.released.set()
    await asyncio.gather(active, ordinary, background, navigation)
    assert [type(request) for request in gate.requests] == [
        peri_scribe.monitor.session.RefreshHealth,
        peri_scribe.monitor.session.RefreshRecords,
        peri_scribe.monitor.session.RefreshReport,
    ]


@pytest.mark.asyncio
async def test_controller_prepare_content_releases_superseded_complete_snapshots(
    unmounted_monitor: monitor_application.MonitorApp,
) -> None:
    controller = unmounted_monitor.controller
    await controller.prepare_content(
        peri_scribe.monitor.session.RefreshRecords(),
        priority=peri_scribe.monitor.session.Priority.BACKGROUND,
    )
    previous = weakref.ref(controller.session.snapshot)
    await controller.prepare_content(
        peri_scribe.monitor.session.RefreshReport(),
        priority=peri_scribe.monitor.session.Priority.BACKGROUND,
    )
    gc.collect()
    assert previous() is None
    await controller.close()


@pytest.mark.asyncio
async def test_controller_prepare_display_discards_obsolete_prepared_rows(
    initial_monitor: tests.helpers.fixtures.peri_scribe.monitor.controller.Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = initial_monitor.app
    await app.controller.activate("pipeline")
    preparation = tests.helpers.doubles.peri_scribe.monitor.tasks.PausedCall(
        function=peri_scribe.monitor.display.prepare,
    )
    applied = unittest.mock.AsyncMock(wraps=peri_scribe.monitor.rendering.apply_records)
    monkeypatch.setattr(peri_scribe.monitor.display, "prepare", preparation)
    monkeypatch.setattr(peri_scribe.monitor.rendering, "apply_records", applied)
    app.controller.schedule_display()
    try:
        assert await asyncio.to_thread(preparation.started.wait, 5)
        change = tests.helpers.doubles.peri_scribe.monitor.controller.DisplayChange(
            operation=app.render_state,
        )
        monkeypatch.setattr(app, "render_state", change)
        stream = app.query_one("#pipeline-stream", peri_scribe.monitor.widgets.Stream)
        stream.query_one(textual.widgets.Input).value = "Beta"
        await asyncio.wait_for(change.dispatched.wait(), 5)
    finally:
        preparation.release.set()
    await app.controller.flush_display()
    applied.assert_awaited_once()
    prepared = applied.call_args.args[1]
    assert [row.event.message for row in prepared.pipeline] == ["Beta event"]
    assert app.controller.prepared_generation == app.controller.generation


@pytest.mark.asyncio
async def test_controller_prepare_display_repeats_after_superseded_widget_application(
    initial_monitor: tests.helpers.fixtures.peri_scribe.monitor.controller.Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = initial_monitor.app
    await app.controller.activate("pipeline")
    gate = tests.helpers.doubles.peri_scribe.monitor.controller.RenderingGate(
        operation=peri_scribe.monitor.rendering.apply_records,
    )
    monkeypatch.setattr(peri_scribe.monitor.rendering, "apply_records", gate.apply)
    app.controller.schedule_display()
    await gate.started.wait()
    try:
        change = tests.helpers.doubles.peri_scribe.monitor.controller.DisplayChange(
            operation=app.render_state,
        )
        monkeypatch.setattr(app, "render_state", change)
        stream = app.query_one("#pipeline-stream", peri_scribe.monitor.widgets.Stream)
        stream.query_one(textual.widgets.Input).value = "Beta"
        await asyncio.wait_for(change.dispatched.wait(), 5)
    finally:
        gate.released.set()
    await app.controller.flush_display()
    assert gate.generations[0] < gate.generations[-1]
    assert app.controller.prepared_generation == app.controller.generation
    table = stream.query_one(peri_scribe.monitor.widgets.EventTable)
    assert [event.message for event in app.rows[table].values()] == ["Beta event"]


@pytest.mark.asyncio
async def test_controller_flush_display_drains_work_replaced_before_resuming(
    unmounted_monitor: monitor_application.MonitorApp,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = unmounted_monitor.controller
    first_release = asyncio.Event()
    second_release = asyncio.Event()
    first = asyncio.create_task(
        tests.helpers.doubles.peri_scribe.monitor.controller.wait_for_release(
            first_release,
        ),
    )
    second = asyncio.create_task(
        tests.helpers.doubles.peri_scribe.monitor.controller.wait_for_release(
            second_release,
        ),
    )
    controller.display_task = first
    first.add_done_callback(
        functools.partial(
            tests.helpers.doubles.peri_scribe.monitor.controller.replace_display,
            controller,
            second,
        ),
    )
    joins = tests.helpers.doubles.peri_scribe.monitor.controller.TaskJoins(
        operation=peri_scribe.monitor.tasks.settle,
    )
    with monkeypatch.context() as patch:
        patch.setattr(peri_scribe.monitor.tasks, "settle", joins.settle)
        flushing = asyncio.create_task(controller.flush_display())
        try:
            assert await asyncio.wait_for(joins.joined.get(), 5) is first
            first_release.set()
            assert await asyncio.wait_for(joins.joined.get(), 5) is second
            assert not flushing.done()
        finally:
            first_release.set()
            second_release.set()
            await flushing
    await controller.close()


@pytest.mark.asyncio
async def test_controller_schedule_display_surfaces_completed_preparation_failure(
    unmounted_monitor: monitor_application.MonitorApp,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = unmounted_monitor.controller
    failure = unittest.mock.AsyncMock(side_effect=RuntimeError("preparation failed"))
    controller.display_task = asyncio.create_task(failure())
    await asyncio.sleep(0)
    controller.presented = True
    monkeypatch.setattr(controller, "available", unittest.mock.Mock(return_value=True))
    with pytest.raises(RuntimeError, match="preparation failed"):
        controller.schedule_display()
    with pytest.raises(ExceptionGroup, match="Monitor presentation tasks failed"):
        await controller.close()


@pytest.mark.asyncio
async def test_controller_accept_preserves_paused_run_and_event_snapshot(
    initial_monitor: tests.helpers.fixtures.peri_scribe.monitor.controller.Session,
) -> None:
    app = initial_monitor.app
    initial_monitor.begin_background()
    assert app.controller.background is not None
    await app.controller.background
    app.following = False
    selected = app.selected_run
    previous = app.visible_state
    tests.helpers.factories.peri_scribe.monitor.events.write_log(
        app.year_directory,
        tests.helpers.factories.peri_scribe.monitor.events.record(
            "Starting command",
            run_id="later-run",
        ),
    )
    await app.controller.refresh()
    assert app.visible_state is previous
    assert app.selected_run == selected
    assert app.controller.snapshot.records.runs[-1].identifier == "later-run"
    assert all(
        event.fields.get("run_id") == selected
        for rows in app.rows.values()
        for event in rows.values()
    )


@pytest.mark.asyncio
async def test_controller_close_discards_worker_completion_after_detachment(
    initial_monitor: tests.helpers.fixtures.peri_scribe.monitor.controller.Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = initial_monitor.app.controller
    await controller.activate("pipeline")
    preparation = tests.helpers.doubles.peri_scribe.monitor.tasks.PausedCall(
        function=peri_scribe.monitor.display.prepare,
    )
    applied = unittest.mock.AsyncMock(wraps=peri_scribe.monitor.rendering.apply_records)
    monkeypatch.setattr(peri_scribe.monitor.display, "prepare", preparation)
    monkeypatch.setattr(peri_scribe.monitor.rendering, "apply_records", applied)
    controller.schedule_display()
    try:
        assert await asyncio.to_thread(preparation.started.wait, 5)
        closing = asyncio.create_task(controller.close())
        await controller.session.owner.stopped.wait()
        assert not closing.done()
    finally:
        preparation.release.set()
    await closing
    applied.assert_not_awaited()
    assert controller.cosmetic_task is not None
    assert controller.cosmetic_task.done()


@pytest.mark.asyncio
async def test_controller_show_health_updates_ages_without_domain_work(
    initial_monitor: tests.helpers.fixtures.peri_scribe.monitor.controller.Session,
) -> None:
    controller = initial_monitor.app.controller
    pane = initial_monitor.app.query_one(peri_scribe.monitor.status_widgets.StatusPane)
    previous = pane.view
    snapshot = controller.session.snapshot
    now = tests.helpers.factories.peri_scribe.monitor.status.NOW
    controller.show_health(now + datetime.timedelta(minutes=1))
    await initial_monitor.refresh()
    assert pane.view is not None
    assert previous is not None
    assert pane.view.metrics[2].text != previous.metrics[2].text
    assert controller.session.snapshot is snapshot
    assert not controller.content


@pytest.mark.parametrize("detached", [False, True])
@pytest.mark.asyncio
async def test_controller_watch_presentation_redraws_only_while_attached(
    initial_monitor: tests.helpers.fixtures.peri_scribe.monitor.controller.Session,
    monkeypatch: pytest.MonkeyPatch,
    *,
    detached: bool,
) -> None:
    controller = initial_monitor.app.controller
    if detached:
        await initial_monitor.app.query_one("#views").remove()
    shown = unittest.mock.Mock(wraps=controller.show_health)
    monkeypatch.setattr(controller, "show_health", shown)
    with monkeypatch.context() as patch:
        patch.setattr(
            controller.cosmetic_changed,
            "wait",
            unittest.mock.AsyncMock(side_effect=[TimeoutError, asyncio.CancelledError]),
        )
        with pytest.raises(asyncio.CancelledError):
            await controller.watch_presentation()
    assert shown.call_count == (0 if detached else 1)
    assert not controller.content


@pytest.mark.asyncio
async def test_finish_presentations_waits_for_peers_before_reporting_failure() -> None:
    released = asyncio.Event()
    failure = unittest.mock.AsyncMock(side_effect=RuntimeError("preparation failed"))
    failed = asyncio.create_task(failure())
    peer = asyncio.create_task(released.wait())
    finishing = asyncio.create_task(
        peri_scribe.monitor.controller.finish_presentations((failed, peer)),
    )
    try:
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert not finishing.done()
    finally:
        released.set()
    with pytest.raises(ExceptionGroup, match="Monitor presentation tasks failed"):
        await finishing
    assert peer.done()
