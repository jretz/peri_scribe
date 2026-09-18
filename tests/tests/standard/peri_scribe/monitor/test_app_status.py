"""Status remains live and its evidence links open exact historical Pipeline records."""

import collections.abc
import datetime
import typing
import unittest.mock

import pytest
import rich.json
import rich.text
import textual.widgets
import time_machine

import peri_scribe.monitor.app
import peri_scribe.monitor.changes
import peri_scribe.monitor.history
import peri_scribe.monitor.status
import peri_scribe.monitor.status_widgets
import peri_scribe.monitor.storage
import tests.helpers.doubles.errors
import tests.helpers.doubles.peri_scribe.monitor.changes
import tests.helpers.factories.peri_scribe.monitor.events
import tests.helpers.factories.peri_scribe.monitor.status
import tests.helpers.fixtures.peri_scribe.monitor.application
import tests.helpers.textual


@pytest.mark.asyncio
async def test_monitor_app_status_is_first_tab_and_first_shortcut(
    monitor_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
) -> None:
    session = monitor_session
    assert session.app.query(textual.widgets.TabPane).first().id == "status"
    await session.pilot.press("1")
    assert (
        session.app.query_one("#views", textual.widgets.TabbedContent).active
        == "status"
    )
    assert not session.app.query_one("#inspection").display
    assert not session.app.query_one("#decisions").display


@pytest.mark.asyncio
async def test_monitor_app_status_ages_update_without_new_logs(
    monitor_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
) -> None:
    session = monitor_session
    now = tests.helpers.factories.peri_scribe.monitor.status.NOW
    session.app.kmz_path.parent.mkdir()
    session.app.kmz_path.write_bytes(b"map")
    session.app.report_path.write_text("Report")
    tests.helpers.factories.peri_scribe.monitor.events.write_log(
        session.directory,
        tests.helpers.factories.peri_scribe.monitor.status.finished("kmz"),
        tests.helpers.factories.peri_scribe.monitor.status.finished("reports"),
    )
    with time_machine.travel(now + datetime.timedelta(hours=4), tick=False):
        await session.app.refresh_files()
        pane = session.app.query_one(peri_scribe.monitor.status_widgets.StatusPane)
        assert pane.view is not None
        assert pane.view.metrics[0].health == peri_scribe.monitor.status.Health.GOOD
    with time_machine.travel(now + datetime.timedelta(hours=7), tick=False):
        await session.app.refresh_files()
        assert pane.view is not None
        assert pane.view.metrics[0].health == peri_scribe.monitor.status.Health.BAD


@pytest.mark.asyncio
async def test_monitor_app_status_reuses_sorted_evidence_when_only_time_changes(
    monitor_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = monitor_session
    session.app.kmz_path.parent.mkdir()
    session.app.kmz_path.write_bytes(b"map")
    tests.helpers.factories.peri_scribe.monitor.events.write_log(
        session.directory,
        tests.helpers.factories.peri_scribe.monitor.status.finished("kmz"),
    )
    evidence = unittest.mock.Mock(wraps=peri_scribe.monitor.status.evidence)
    monkeypatch.setattr(peri_scribe.monitor.status, "evidence", evidence)
    await session.app.refresh_files()
    pane = session.app.query_one(peri_scribe.monitor.status_widgets.StatusPane)
    assert pane.view is not None
    previous = pane.view.metrics
    now = tests.helpers.factories.peri_scribe.monitor.status.NOW
    with time_machine.travel(now + datetime.timedelta(hours=7), tick=False):
        await session.app.refresh_files()
    evidence.assert_called_once()
    assert pane.view.metrics != previous
    tests.helpers.factories.peri_scribe.monitor.events.write_log(
        session.directory,
        tests.helpers.factories.peri_scribe.monitor.status.finished("reports"),
    )
    await session.app.refresh_files()
    expected_calls = 2
    assert evidence.call_count == expected_calls


@pytest.mark.asyncio
async def test_monitor_app_status_catches_up_before_projecting_history(
    monitor_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = monitor_session
    monkeypatch.setattr(peri_scribe.monitor.storage, "MAXIMUM_READ_BYTES", 100)
    tests.helpers.factories.peri_scribe.monitor.events.write_log(
        session.directory,
        *tests.helpers.factories.peri_scribe.monitor.status.failed_run(),
    )
    project = unittest.mock.Mock(wraps=peri_scribe.monitor.status.project)
    monkeypatch.setattr(peri_scribe.monitor.status, "project", project)
    await session.app.refresh_files()
    project.assert_called_once()
    assert project.call_args.args[0].caught_up
    pane = session.app.query_one(peri_scribe.monitor.status_widgets.StatusPane)
    assert pane.view is not None
    assert pane.view.coverage.health == peri_scribe.monitor.status.Health.GOOD


@pytest.mark.asyncio
async def test_monitor_app_status_uses_live_phase_while_pipeline_is_paused(
    monitor_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
) -> None:
    session = monitor_session
    tests.helpers.factories.peri_scribe.monitor.events.write_log(
        session.directory,
        tests.helpers.factories.peri_scribe.monitor.status.record(
            "Starting command",
            command="run",
            run_id="old",
        ),
    )
    await session.app.refresh_files()
    await tests.helpers.textual.invoke(session.app.action_toggle_follow)
    tests.helpers.factories.peri_scribe.monitor.events.write_log(
        session.directory,
        tests.helpers.factories.peri_scribe.monitor.status.record(
            "Starting command",
            command="run",
            run_id="new",
        ),
        tests.helpers.factories.peri_scribe.monitor.status.record(
            "Starting phase",
            run_id="new",
            phase="fetch.fire-collection.collect-feed.query-features",
        ),
    )
    await session.app.refresh_files()
    assert session.app.current_run().identifier == "old"
    text = session.app.query_one(
        "#status-activity",
        peri_scribe.monitor.status_widgets.StatusLink,
    ).content
    assert isinstance(text, rich.text.Text)
    assert "fetch → fire-collection → collect-feed → query-features" in text.plain


@pytest.mark.asyncio
async def test_monitor_app_status_links_load_run_beyond_interactive_history(
    monitor_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
) -> None:
    session = monitor_session
    tests.helpers.factories.peri_scribe.monitor.events.write_log(
        session.directory,
        *tests.helpers.factories.peri_scribe.monitor.status.failed_run(),
        *(
            tests.helpers.factories.peri_scribe.monitor.status.record(
                "Starting command",
                command="run",
                run_id=str(number),
            )
            for number in range(110)
        ),
    )
    await session.app.refresh_files()
    assert all(run.identifier != "failed" for run in session.app.state.runs)
    await tests.helpers.textual.invoke(
        session.app.query_one(
            "#status-failure",
            peri_scribe.monitor.status_widgets.StatusLink,
        ).on_click,
    )
    await session.pilot.pause()
    assert session.app.current_run().identifier == "failed"
    assert not session.app.following
    assert (
        session.app.query_one("#views", textual.widgets.TabbedContent).active
        == "pipeline"
    )
    assert session.app.selected_phase[-1].phase == "prepare-fire-histories"
    details = session.app.query_one("#details", textual.widgets.Static).content
    assert isinstance(details, rich.json.JSON)
    assert "invalid geometry" in details.text.plain


@pytest.mark.asyncio
async def test_monitor_app_status_exception_row_opens_latest_instance(
    monitor_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
) -> None:
    session = monitor_session
    tests.helpers.factories.peri_scribe.monitor.events.write_log(
        session.directory,
        *tests.helpers.factories.peri_scribe.monitor.status.failed_run(run_id="first"),
        *tests.helpers.factories.peri_scribe.monitor.status.failed_run(run_id="latest"),
    )
    await session.app.refresh_files()
    pane = session.app.query_one(peri_scribe.monitor.status_widgets.StatusPane)
    table = pane.query_one("#status-exceptions", textual.widgets.DataTable)
    await tests.helpers.textual.invoke(
        pane.select_evidence,
        textual.widgets.DataTable.RowSelected(table, 0, next(iter(table.rows))),
    )
    await session.pilot.pause()
    assert session.app.current_run().identifier == "latest"


@pytest.mark.asyncio
async def test_monitor_app_status_link_supports_keyboard(
    monitor_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
) -> None:
    session = monitor_session
    tests.helpers.factories.peri_scribe.monitor.events.write_log(
        session.directory,
        *tests.helpers.factories.peri_scribe.monitor.status.failed_run(),
    )
    await session.app.refresh_files()
    await session.pilot.press("1")
    await tests.helpers.textual.invoke(session.app.query_one("#status-failure").focus)
    await session.pilot.press("enter")
    assert (
        session.app.query_one("#views", textual.widgets.TabbedContent).active
        == "pipeline"
    )


@pytest.mark.asyncio
async def test_monitor_app_status_missing_evidence_reports_unavailable(
    monitor_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = monitor_session
    notification = unittest.mock.Mock()
    monkeypatch.setattr(session.app, "notify", notification)
    history = tests.helpers.factories.peri_scribe.monitor.status.history(
        *tests.helpers.factories.peri_scribe.monitor.status.failed_run(),
    )
    target = peri_scribe.monitor.status.evidence(history)[0]
    await session.app.open_status_evidence(
        peri_scribe.monitor.status_widgets.OpenEvidence(target),
    )
    assert "no longer available" in notification.call_args.args[0]


@pytest.mark.asyncio
async def test_monitor_app_status_evidence_read_error_is_visible(
    monitor_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = monitor_session
    notification = unittest.mock.Mock()
    monkeypatch.setattr(session.app, "notify", notification)
    monkeypatch.setattr(
        peri_scribe.monitor.history,
        "load_run",
        tests.helpers.doubles.errors.raising_stub(OSError("unreadable")),
    )
    target = peri_scribe.monitor.status.evidence(
        tests.helpers.factories.peri_scribe.monitor.status.history(
            *tests.helpers.factories.peri_scribe.monitor.status.failed_run(),
        ),
    )[0]
    await session.app.open_status_evidence(
        peri_scribe.monitor.status_widgets.OpenEvidence(target),
    )
    assert "unreadable" in notification.call_args.args[0]


@pytest.mark.parametrize(("width", "height"), [(80, 24), (120, 42)])
@pytest.mark.asyncio
async def test_monitor_app_status_fits_terminal_with_scrollable_details(
    monitor_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
    width: int,
    height: int,
) -> None:
    session = monitor_session
    await session.pilot.press("1")
    await session.pilot.resize_terminal(width, height)
    for selector in (
        "#status-content",
        "#status-overview",
        "#status-outputs",
        "Footer",
    ):
        region = session.app.query_one(selector).region
        assert region.width > 0
        assert region.height > 0
        assert region.right <= width
        assert region.bottom <= height


@pytest.mark.asyncio
async def test_refresh_clock_updates_freshness_without_reading_files(
    monitor_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = monitor_session
    now = tests.helpers.factories.peri_scribe.monitor.status.NOW
    session.app.report_path.write_text("Report")
    tests.helpers.factories.peri_scribe.monitor.events.write_log(
        session.directory,
        tests.helpers.factories.peri_scribe.monitor.status.finished("reports"),
    )
    await session.app.refresh_files()
    read = unittest.mock.AsyncMock()
    monkeypatch.setattr(session.app, "refresh_files", read)
    session.app.files_changed = False
    session.app.reconcile_at = float("inf")
    with time_machine.travel(now + datetime.timedelta(hours=7), tick=False):
        await peri_scribe.monitor.app.refresh_clock(session.app)
    read.assert_not_awaited()
    pane = session.app.query_one(peri_scribe.monitor.status_widgets.StatusPane)
    assert pane.view is not None
    assert pane.view.metrics[1].health == peri_scribe.monitor.status.Health.BAD


@pytest.mark.parametrize("notification", [True, False])
@pytest.mark.asyncio
async def test_refresh_clock_reads_on_notification_or_reconciliation_deadline(
    monitor_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
    monkeypatch: pytest.MonkeyPatch,
    *,
    notification: bool,
) -> None:
    session = monitor_session
    read = unittest.mock.AsyncMock()
    monkeypatch.setattr(session.app, "refresh_files", read)
    session.app.files_changed = notification
    session.app.reconcile_at = float("inf") if notification else 0
    await peri_scribe.monitor.app.refresh_clock(session.app)
    read.assert_awaited_once()
    assert not session.app.files_changed


@pytest.mark.asyncio
async def test_refresh_clock_ignores_unmounted_views(
    monitor_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = monitor_session
    await tests.helpers.fixtures.peri_scribe.monitor.application.remove_views(
        session.app,
    )
    read = unittest.mock.AsyncMock()
    monkeypatch.setattr(session.app, "refresh_files", read)
    await peri_scribe.monitor.app.refresh_clock(session.app)
    read.assert_not_awaited()


@pytest.mark.asyncio
async def test_refresh_clock_waits_for_initial_status(
    monitor_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = monitor_session
    session.app.status_snapshot = None
    session.app.files_changed = False
    session.app.reconcile_at = float("inf")
    read = unittest.mock.AsyncMock()
    monkeypatch.setattr(session.app, "refresh_files", read)
    await peri_scribe.monitor.app.refresh_clock(session.app)
    read.assert_not_awaited()


@pytest.mark.asyncio
async def test_watch_files_coalesces_notifications_without_reading_from_the_worker(
    file_watching_session: tuple[
        collections.abc.Callable[
            [peri_scribe.monitor.app.MonitorApp],
            collections.abc.Coroutine[typing.Any, typing.Any, None],
        ],
        tests.helpers.fixtures.peri_scribe.monitor.application.Session,
    ],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    watcher, session = file_watching_session
    hints = tests.helpers.doubles.peri_scribe.monitor.changes.notifications(
        session.app.watching_stopped,
    )
    monkeypatch.setattr(
        peri_scribe.monitor.changes,
        "watch",
        unittest.mock.Mock(return_value=hints),
    )
    session.app.files_changed = False
    read = unittest.mock.AsyncMock()
    monkeypatch.setattr(session.app, "refresh_files", read)
    await watcher(session.app)
    assert session.app.files_changed
    read.assert_not_awaited()
