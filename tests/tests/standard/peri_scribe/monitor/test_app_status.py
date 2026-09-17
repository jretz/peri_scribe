"""Status remains live and its evidence links open exact historical Pipeline records."""

import datetime
import unittest.mock

import pytest
import rich.json
import rich.text
import textual.events
import textual.widgets
import time_machine

import peri_scribe.monitor.history
import peri_scribe.monitor.status
import peri_scribe.monitor.status_widgets
import peri_scribe.monitor.theme
import tests.helpers.doubles.errors
import tests.helpers.factories.peri_scribe.monitor.events
import tests.helpers.factories.peri_scribe.monitor.status
import tests.helpers.fixtures.peri_scribe.monitor.application


def test_monitor_app_status_is_first_tab_and_first_shortcut(
    monitor_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
) -> None:
    session = monitor_session
    assert session.app.query(textual.widgets.TabPane).first().id == "status"
    session.runner.run(session.pilot.press("1"))
    assert (
        session.app.query_one("#views", textual.widgets.TabbedContent).active
        == "status"
    )
    assert not session.app.query_one("#inspection").display
    assert not session.app.query_one("#decisions").display


def test_monitor_app_status_ages_update_without_new_logs(
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
        session.runner.run(session.app.refresh_files())
        pane = session.app.query_one(peri_scribe.monitor.status_widgets.StatusPane)
        assert pane.view is not None
        assert pane.view.metrics[0].health == peri_scribe.monitor.status.Health.GOOD
    with time_machine.travel(now + datetime.timedelta(hours=7), tick=False):
        session.runner.run(session.app.refresh_files())
        assert pane.view is not None
        assert pane.view.metrics[0].health == peri_scribe.monitor.status.Health.BAD


def test_monitor_app_status_uses_live_phase_while_pipeline_is_paused(
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
    session.runner.run(session.app.refresh_files())
    session.call(session.app.action_toggle_follow)
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
    session.runner.run(session.app.refresh_files())
    assert session.app.current_run().identifier == "old"
    text = session.app.query_one(
        "#status-activity",
        peri_scribe.monitor.status_widgets.StatusLink,
    ).content
    assert isinstance(text, rich.text.Text)
    assert "fetch → fire-collection → collect-feed → query-features" in text.plain


def test_monitor_app_status_links_load_run_beyond_interactive_history(
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
    session.runner.run(session.app.refresh_files())
    assert all(run.identifier != "failed" for run in session.app.state.runs)
    session.call(
        session.app.query_one(
            "#status-failure",
            peri_scribe.monitor.status_widgets.StatusLink,
        ).on_click,
    )
    session.runner.run(session.pilot.pause())
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


def test_monitor_app_status_exception_row_opens_latest_instance(
    monitor_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
) -> None:
    session = monitor_session
    tests.helpers.factories.peri_scribe.monitor.events.write_log(
        session.directory,
        *tests.helpers.factories.peri_scribe.monitor.status.failed_run(run_id="first"),
        *tests.helpers.factories.peri_scribe.monitor.status.failed_run(run_id="latest"),
    )
    session.runner.run(session.app.refresh_files())
    pane = session.app.query_one(peri_scribe.monitor.status_widgets.StatusPane)
    table = pane.query_one("#status-exceptions", textual.widgets.DataTable)
    session.call(
        pane.select_evidence,
        textual.widgets.DataTable.RowSelected(table, 0, next(iter(table.rows))),
    )
    session.runner.run(session.pilot.pause())
    assert session.app.current_run().identifier == "latest"


def test_monitor_app_status_link_supports_keyboard(
    monitor_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
) -> None:
    session = monitor_session
    tests.helpers.factories.peri_scribe.monitor.events.write_log(
        session.directory,
        *tests.helpers.factories.peri_scribe.monitor.status.failed_run(),
    )
    session.runner.run(session.app.refresh_files())
    session.runner.run(session.pilot.press("1"))
    session.call(session.app.query_one("#status-failure").focus)
    session.runner.run(session.pilot.press("enter"))
    assert (
        session.app.query_one("#views", textual.widgets.TabbedContent).active
        == "pipeline"
    )


def test_monitor_app_status_missing_evidence_reports_unavailable(
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
    session.runner.run(
        session.app.open_status_evidence(
            peri_scribe.monitor.status_widgets.OpenEvidence(target),
        ),
    )
    assert "no longer available" in notification.call_args.args[0]


def test_monitor_app_status_evidence_read_error_is_visible(
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
    session.runner.run(
        session.app.open_status_evidence(
            peri_scribe.monitor.status_widgets.OpenEvidence(target),
        ),
    )
    assert "unreadable" in notification.call_args.args[0]


@pytest.mark.parametrize(("width", "height"), [(80, 24), (120, 42)])
def test_monitor_app_status_fits_terminal_with_scrollable_details(
    monitor_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
    width: int,
    height: int,
) -> None:
    session = monitor_session
    session.runner.run(session.pilot.press("1"))
    session.runner.run(session.pilot.resize_terminal(width, height))
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


def test_monitor_app_status_health_uses_colors_and_symbols(
    color_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
) -> None:
    session = color_session
    session.runner.run(session.pilot.press("1"))
    text = session.app.query_one("#status-overview", textual.widgets.Static).content
    assert isinstance(text, rich.text.Text)
    assert peri_scribe.monitor.theme.RED in str(text.style)
    assert "✗" in text.plain


def test_monitor_app_status_empty_observations_do_not_navigate(
    monitor_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
) -> None:
    session = monitor_session
    session.runner.run(session.pilot.press("1"))
    link = session.app.query_one(
        "#status-failure",
        peri_scribe.monitor.status_widgets.StatusLink,
    )
    session.call(link.on_click)
    session.call(link.on_key, textual.events.Key("x", "x"))
    pane = session.app.query_one(peri_scribe.monitor.status_widgets.StatusPane)
    table = pane.query_one("#status-exceptions", textual.widgets.DataTable)
    session.call(
        pane.select_evidence,
        textual.widgets.DataTable.RowSelected(table, 0, next(iter(table.rows))),
    )
    session.runner.run(session.pilot.pause())
    assert (
        session.app.query_one("#views", textual.widgets.TabbedContent).active
        == "status"
    )


def test_monitor_app_status_preserves_exception_selection_as_count_changes(
    monitor_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
) -> None:
    session = monitor_session
    tests.helpers.factories.peri_scribe.monitor.events.write_log(
        session.directory,
        *tests.helpers.factories.peri_scribe.monitor.status.failed_run(run_id="first"),
    )
    session.runner.run(session.app.refresh_files())
    table = session.app.query_one("#status-exceptions", textual.widgets.DataTable)
    selected = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
    tests.helpers.factories.peri_scribe.monitor.events.write_log(
        session.directory,
        *tests.helpers.factories.peri_scribe.monitor.status.failed_run(run_id="latest"),
    )
    session.runner.run(session.app.refresh_files())
    assert table.coordinate_to_cell_key(table.cursor_coordinate).row_key == selected
    assert table.get_row(selected)[1] == "2"


def test_monitor_app_status_unlinked_observations_are_readable(
    monitor_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
) -> None:
    session = monitor_session
    pane = session.app.query_one(peri_scribe.monitor.status_widgets.StatusPane)
    session.call(
        pane.update_table,
        "recent",
        (
            peri_scribe.monitor.status.Metric(
                label="Unknown time",
                text="History unavailable",
                health=peri_scribe.monitor.status.Health.WARNING,
            ),
        ),
    )
    table = pane.query_one("#status-recent", textual.widgets.DataTable)
    assert table.row_count == 1
    assert not any(key[0] == "recent" for key in pane.targets)
