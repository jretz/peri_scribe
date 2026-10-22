"""Performance charts follow complete recent evidence and terminal geometry."""

import asyncio
import datetime
import functools
import unittest.mock

import pytest
import textual.widgets
import time_machine

import peri_scribe.monitor.performance_widgets
import tests.helpers.factories.peri_scribe.monitor.events
import tests.helpers.factories.peri_scribe.monitor.status
import tests.helpers.fixtures.peri_scribe.monitor.application
import tests.helpers.fixtures.peri_scribe.monitor.controller
import tests.helpers.textual


@pytest.mark.asyncio
async def test_monitor_app_performance_keyboard_navigation_hides_inspection(
    monitor_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
) -> None:
    await monitor_session.pilot.press("6")
    await monitor_session.refresh()
    assert (
        monitor_session.app.query_one("#views", textual.widgets.TabbedContent).active
        == "performance"
    )
    assert not monitor_session.app.query_one("#inspection").display
    assert not monitor_session.app.query_one("#inspection-divider").display
    assert not monitor_session.app.query_one("#decisions").display
    assert monitor_session.app.query_one("#performance-charts").region.height > 0


@pytest.mark.asyncio
async def test_controller_activate_performance_before_first_paint_uses_loaded_evidence(
    initial_monitor: tests.helpers.fixtures.peri_scribe.monitor.controller.Session,
) -> None:
    controller = initial_monitor.app.controller
    await controller.activate("performance")
    assert not controller.presented
    assert controller.background is None
    assert not controller.content
    assert not controller.session.records_requested
    assert not controller.session.report_requested
    assert controller.prepared_generation == controller.generation


@pytest.mark.asyncio
async def test_monitor_app_performance_uses_complete_recent_history(
    monitor_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
) -> None:
    count = 125
    tests.helpers.factories.peri_scribe.monitor.events.write_log(
        monitor_session.directory,
        *(
            tests.helpers.factories.peri_scribe.monitor.status.record(
                "Finished command",
                run_id=str(index),
                command="fetch" if index % 2 else "run",
                status="completed",
                duration={"value": index + 1, "units": "seconds"},
            )
            for index in range(count)
        ),
    )
    await monitor_session.app.refresh_files()
    pane = monitor_session.app.query_one(
        peri_scribe.monitor.performance_widgets.PerformancePane,
    )
    assert sum(len(series.samples) for series in pane.series) == count
    assert {series.command for series in pane.series} == {"fetch", "run"}
    assert len(monitor_session.app.controller.snapshot.records.runs) < count


@pytest.mark.asyncio
async def test_monitor_app_performance_updates_while_log_browsing_is_paused(
    monitor_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
) -> None:
    await tests.helpers.textual.invoke(monitor_session.app.action_toggle_follow)
    visible = monitor_session.app.visible_state
    tests.helpers.factories.peri_scribe.monitor.events.write_log(
        monitor_session.directory,
        tests.helpers.factories.peri_scribe.monitor.status.record(
            "Finished command",
            command="run",
            status="completed",
            duration={"value": 10, "units": "seconds"},
        ),
    )
    await monitor_session.app.refresh_files()
    pane = monitor_session.app.query_one(
        peri_scribe.monitor.performance_widgets.PerformancePane,
    )
    assert monitor_session.app.visible_state is visible
    assert len(pane.series) == 1
    assert len(pane.series[0].samples) == 1
    await monitor_session.pilot.press("6")
    assert "LIVE PERFORMANCE" in str(
        monitor_session.app.query_one("#activity", textual.widgets.Static).content,
    )


@pytest.mark.asyncio
async def test_monitor_app_performance_expires_completed_runs_after_window(
    monitor_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
) -> None:
    tests.helpers.factories.peri_scribe.monitor.events.write_log(
        monitor_session.directory,
        tests.helpers.factories.peri_scribe.monitor.status.record(
            "Finished command",
            command="run",
            status="completed",
            duration={"value": 10, "units": "seconds"},
        ),
    )
    await monitor_session.app.refresh_files()
    pane = monitor_session.app.query_one(
        peri_scribe.monitor.performance_widgets.PerformancePane,
    )
    assert len(pane.series) == 1
    expired = (
        tests.helpers.factories.peri_scribe.monitor.status.NOW
        + datetime.timedelta(
            hours=48,
            microseconds=1,
        )
    )
    with time_machine.travel(expired, tick=False):
        await monitor_session.app.refresh_files()
        assert pane.series == ()


@pytest.mark.asyncio
async def test_controller_watch_presentation_advances_performance_without_reads(
    monitor_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = monitor_session.app.controller
    task = controller.cosmetic_task
    assert task is not None
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    controller.cosmetic_task = None
    tests.helpers.factories.peri_scribe.monitor.events.write_log(
        monitor_session.directory,
        tests.helpers.factories.peri_scribe.monitor.status.record(
            "Finished command",
            command="run",
            status="completed",
            duration={"value": 10, "units": "seconds"},
        ),
    )
    await monitor_session.app.refresh_files()
    pane = monitor_session.app.query_one(
        peri_scribe.monitor.performance_widgets.PerformancePane,
    )
    series = pane.series
    snapshot = controller.snapshot
    request = unittest.mock.AsyncMock(wraps=controller.session.request)
    monkeypatch.setattr(controller.session, "request", request)
    monkeypatch.setattr(
        controller.cosmetic_changed,
        "wait",
        unittest.mock.AsyncMock(side_effect=[TimeoutError, asyncio.CancelledError]),
    )
    later = pane.observed_at + datetime.timedelta(minutes=1)
    with time_machine.travel(later, tick=False):
        with pytest.raises(asyncio.CancelledError):
            await controller.watch_presentation()
        await controller.flush_display()
    assert pane.observed_at == later
    assert pane.series == series
    assert controller.snapshot is snapshot
    request.assert_not_awaited()


@pytest.mark.asyncio
async def test_monitor_app_performance_resizes_charts_and_preserves_scroll(
    monitor_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
) -> None:
    tests.helpers.factories.peri_scribe.monitor.events.write_log(
        monitor_session.directory,
        *(
            tests.helpers.factories.peri_scribe.monitor.status.record(
                "Finished command",
                run_id=f"{command}-{index}",
                command=command,
                status="completed",
                duration={"value": index + 1, "units": "seconds"},
            )
            for command in ("fetch", "geography", "kmz", "report", "run")
            for index in range(3)
        ),
    )
    await monitor_session.app.refresh_files()
    await monitor_session.pilot.press("6")
    pane = monitor_session.app.query_one(
        peri_scribe.monitor.performance_widgets.PerformancePane,
    )
    charts = pane.query_one("#performance-charts", textual.widgets.Static)
    await monitor_session.resize(80, 24)
    narrow = str(charts.content)
    assert max(map(len, narrow.splitlines())) <= charts.size.width
    assert pane.show_vertical_scrollbar
    assert not pane.show_horizontal_scrollbar
    await monitor_session.resize(160, 50)
    wide = str(charts.content)
    assert max(map(len, wide.splitlines())) <= charts.size.width
    assert wide != narrow
    await tests.helpers.textual.invoke(
        functools.partial(pane.scroll_page_down, animate=False),
    )
    await monitor_session.refresh()
    position = pane.scroll_offset
    assert position.y > 0
    await monitor_session.app.refresh_files()
    await monitor_session.refresh()
    assert pane.scroll_offset == position
