"""Exercise real terminal controls over isolated files and the shared domain model."""

import asyncio
import compression.zstd
import datetime
import functools
import json
import threading
import unittest.mock

import pytest
import rich.json
import textual.events
import textual.widgets

import peri_scribe.monitor.app
import peri_scribe.monitor.model
import peri_scribe.monitor.storage
import peri_scribe.monitor.widgets
import peri_scribe.phases
import peri_scribe.pipeline_stages
import tests.helpers.doubles.peri_scribe.monitor.app
import tests.helpers.factories.peri_scribe.monitor.events
import tests.helpers.fixtures.peri_scribe.monitor.application


def test_monitor_app_renders_every_possible_phase(
    monitor_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
) -> None:
    seen = set()
    for gated in (True, False):
        tests.helpers.factories.peri_scribe.monitor.events.write_log(
            monitor_session.directory,
            tests.helpers.factories.peri_scribe.monitor.events.record(
                "Starting command",
                command="run",
                run_id=str(gated),
            ),
            tests.helpers.factories.peri_scribe.monitor.events.record(
                "Planned phases",
                gated=gated,
                run_id=str(gated),
            ),
        )
        monitor_session.runner.run(monitor_session.app.refresh_files())
        seen.update(path[-1].phase for path in monitor_session.app.tree_nodes)
        assert all(
            node.data is not None and node.data.status == "waiting"
            for node in monitor_session.app.tree_nodes.values()
        )
        tests.helpers.factories.peri_scribe.monitor.events.write_log(
            monitor_session.directory,
            *(
                tests.helpers.factories.peri_scribe.monitor.events.record(
                    "Starting phase",
                    path=path,
                    run_id=str(gated),
                )
                for path in monitor_session.app.tree_nodes
            ),
        )
        monitor_session.runner.run(monitor_session.app.refresh_files())
        assert all(
            node.data is not None and node.data.status == "open"
            for node in monitor_session.app.tree_nodes.values()
        )
    assert seen == {*peri_scribe.phases.Phase, *peri_scribe.pipeline_stages.Stage}


def test_monitor_app_waiting_phases_cannot_filter(
    monitor_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
) -> None:
    node = next(iter(monitor_session.app.tree_nodes.values()))
    monitor_session.call(
        monitor_session.app.select_phase,
        textual.widgets.Tree.NodeSelected(node),
    )
    assert monitor_session.app.selected_phase == ()


def test_monitor_app_selects_started_source_branch(
    monitor_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
) -> None:
    path = (
        peri_scribe.phases.Segment(phase="fetch"),
        peri_scribe.phases.Segment(phase="fire-collection"),
        peri_scribe.phases.Segment(phase="collect-feed", branch="alpha"),
    )
    tests.helpers.factories.peri_scribe.monitor.events.write_log(
        monitor_session.directory,
        tests.helpers.factories.peri_scribe.monitor.events.record(
            "Starting command",
            command="run",
        ),
        tests.helpers.factories.peri_scribe.monitor.events.record(
            "Starting phase",
            path=path,
        ),
    )
    monitor_session.runner.run(monitor_session.app.refresh_files())
    node = monitor_session.app.tree_nodes[path]
    monitor_session.call(
        monitor_session.app.select_phase,
        textual.widgets.Tree.NodeSelected(node),
    )
    assert monitor_session.app.selected_phase == path
    root = monitor_session.app.query_one("#phase-tree", textual.widgets.Tree).root
    monitor_session.call(
        monitor_session.app.select_phase,
        textual.widgets.Tree.NodeSelected(root),
    )
    assert monitor_session.app.selected_phase == ()


def test_monitor_app_pause_keeps_collecting(
    monitor_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
) -> None:
    tests.helpers.factories.peri_scribe.monitor.events.write_log(
        monitor_session.directory,
        tests.helpers.factories.peri_scribe.monitor.events.record(
            "Starting command",
            command="run",
        ),
    )
    monitor_session.runner.run(monitor_session.app.refresh_files())
    monitor_session.call(monitor_session.app.action_toggle_follow)
    visible = monitor_session.app.visible_state
    tests.helpers.factories.peri_scribe.monitor.events.write_log(
        monitor_session.directory,
        tests.helpers.factories.peri_scribe.monitor.events.record("New event"),
    )
    monitor_session.runner.run(monitor_session.app.refresh_files())
    assert monitor_session.app.visible_state is visible
    assert monitor_session.app.state.sequence > visible.sequence
    monitor_session.call(monitor_session.app.action_toggle_follow)
    assert monitor_session.app.visible_state is monitor_session.app.state


def test_monitor_app_filters_and_inspects_events(
    monitor_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
) -> None:
    tests.helpers.factories.peri_scribe.monitor.events.write_log(
        monitor_session.directory,
        tests.helpers.factories.peri_scribe.monitor.events.record(
            "Starting command",
            command="run",
        ),
        tests.helpers.factories.peri_scribe.monitor.events.record(
            "Moonshine",
            level="warning",
            exception="Full traceback",
        ),
    )
    monitor_session.runner.run(monitor_session.app.refresh_files())
    monitor_session.call(monitor_session.app.action_search)
    stream = monitor_session.app.query_one(
        "#log-stream",
        peri_scribe.monitor.widgets.Stream,
    )
    monitor_session.call(
        setattr,
        stream.query_one(textual.widgets.Input),
        "value",
        "moonshine",
    )
    monitor_session.runner.run(monitor_session.pilot.pause())
    table = stream.query_one(peri_scribe.monitor.widgets.EventTable)
    assert table.row_count == 1
    monitor_session.call(
        monitor_session.app.select_row,
        textual.widgets.DataTable.RowSelected(table, 0, next(iter(table.rows))),
    )
    details = monitor_session.app.query_one("#details", textual.widgets.Static).content
    assert isinstance(details, rich.json.JSON)
    assert "Full traceback" in details.text.plain
    monitor_session.call(monitor_session.app.action_clear_filter)
    assert stream.query_one(textual.widgets.Input).value == ""


def test_monitor_app_report_uses_current_file_and_mtime(
    monitor_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
) -> None:
    path = monitor_session.app.report_path
    path.write_text("# Fires\n\n[Jump](#moonshine)\n\n## Moonshine\n\nDetails")
    monitor_session.runner.run(monitor_session.app.refresh_files())
    monitor_session.runner.run(monitor_session.pilot.press("5"))
    viewer = monitor_session.app.query_one(
        "#report-viewer",
        textual.widgets.MarkdownViewer,
    )
    assert monitor_session.call(viewer.document.goto_anchor, "moonshine")
    assert (
        monitor_session.app.report.modified
        == datetime.datetime.fromtimestamp(
            path.stat().st_mtime,
            datetime.UTC,
        ).astimezone()
    )
    assert "Report written" in str(
        monitor_session.app.query_one("#report-time", textual.widgets.Static).content,
    )


def test_monitor_app_defers_report_loading_until_its_tab_is_selected(
    monitor_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = monitor_session
    assert session.app.report == peri_scribe.monitor.storage.Report()
    read = unittest.mock.Mock(wraps=peri_scribe.monitor.storage.read_report)
    monkeypatch.setattr(peri_scribe.monitor.storage, "read_report", read)
    viewer = session.app.query_one("#report-viewer", textual.widgets.MarkdownViewer)
    update = unittest.mock.AsyncMock(wraps=viewer.document.update)
    monkeypatch.setattr(viewer.document, "update", update)
    session.app.report_path.write_text("# First")
    session.runner.run(session.app.refresh_files())
    session.app.report_path.write_text("# Latest")
    session.runner.run(session.app.refresh_files())
    read.assert_not_called()
    update.assert_not_called()
    session.runner.run(session.pilot.press("5"))
    update.assert_awaited_once_with("# Latest")
    session.runner.run(session.app.refresh_files())
    session.runner.run(session.pilot.press("1", "5"))
    update.assert_awaited_once()


def test_monitor_app_refreshes_replaced_report_while_paused(
    monitor_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
) -> None:
    monitor_session.call(monitor_session.app.action_toggle_follow)
    path = monitor_session.app.report_path
    path.write_text("# Original")
    monitor_session.runner.run(monitor_session.pilot.press("5"))
    temporary = path.with_suffix(".new")
    temporary.write_text("# Replacement")
    temporary.replace(path)
    monitor_session.runner.run(monitor_session.app.refresh_files())
    assert monitor_session.app.report.content == "# Replacement"


@pytest.mark.parametrize("tab", ["1", "2", "3", "4"])
def test_monitor_app_suspends_report_refresh_until_returning_to_its_tab(
    monitor_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
    monkeypatch: pytest.MonkeyPatch,
    tab: str,
) -> None:
    session = monitor_session
    session.app.report_path.write_text("# Original")
    session.runner.run(session.pilot.press("5", tab))
    read = unittest.mock.Mock(wraps=peri_scribe.monitor.storage.read_report)
    monkeypatch.setattr(peri_scribe.monitor.storage, "read_report", read)
    viewer = session.app.query_one("#report-viewer", textual.widgets.MarkdownViewer)
    update = unittest.mock.AsyncMock(wraps=viewer.document.update)
    monkeypatch.setattr(viewer.document, "update", update)
    session.app.report_path.write_text("# Replacement")
    session.runner.run(session.app.refresh_files())
    read.assert_not_called()
    update.assert_not_called()
    assert session.app.report.content == "# Original"
    session.runner.run(session.pilot.press("5"))
    assert session.app.report.content == "# Replacement"
    update.assert_awaited_once_with("# Replacement")


def test_render_report_discards_a_read_completed_after_leaving_its_tab(
    monitor_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = monitor_session
    session.app.report_path.write_text("# Original")
    session.runner.run(session.pilot.press("5"))
    viewer = session.app.query_one("#report-viewer", textual.widgets.MarkdownViewer)
    update = unittest.mock.AsyncMock(wraps=viewer.document.update)
    monkeypatch.setattr(viewer.document, "update", update)
    monkeypatch.setattr(
        peri_scribe.monitor.storage,
        "read_report",
        functools.partial(
            tests.helpers.doubles.peri_scribe.monitor.app.hide_report_during_read,
            session.app,
        ),
    )
    session.runner.run(peri_scribe.monitor.app.render_report(session.app))
    update.assert_not_called()
    assert session.app.report.content == "# Original"


def test_monitor_app_selects_historical_run(
    monitor_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
) -> None:
    tests.helpers.factories.peri_scribe.monitor.events.write_log(
        monitor_session.directory,
        tests.helpers.factories.peri_scribe.monitor.events.record(
            "Starting command",
            command="run",
        ),
        tests.helpers.factories.peri_scribe.monitor.events.record(
            "Finished command",
            status="completed",
        ),
    )
    monitor_session.runner.run(monitor_session.app.refresh_files())
    monitor_session.runner.run(monitor_session.pilot.press("3"))
    table = monitor_session.app.query_one("#run-table", textual.widgets.DataTable)
    monitor_session.call(
        monitor_session.app.select_row,
        textual.widgets.DataTable.RowSelected(table, 0, next(iter(table.rows))),
    )
    assert not monitor_session.app.following
    assert monitor_session.app.current_run().status == "completed"
    assert not monitor_session.app.tree_nodes


def test_monitor_app_navigation_keys(
    monitor_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
) -> None:
    monitor_session.runner.run(monitor_session.pilot.press("3", "2", "end"))
    assert (
        monitor_session.app.query_one("#views", textual.widgets.TabbedContent).active
        == "pipeline"
    )
    assert monitor_session.app.following


def test_event_table_upward_browsing_pauses_following(
    monitor_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
) -> None:
    table = monitor_session.app.query_one(peri_scribe.monitor.widgets.EventTable)
    monitor_session.call(table.on_key, textual.events.Key("up", None))
    monitor_session.runner.run(monitor_session.pilot.pause())
    assert not monitor_session.app.following


def test_event_table_wheel_browsing_pauses_following(
    monitor_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
) -> None:
    table = monitor_session.app.query_one(peri_scribe.monitor.widgets.EventTable)
    monitor_session.call(
        table.on_mouse_scroll_up,
        unittest.mock.Mock(spec=textual.events.MouseScrollUp),
    )
    monitor_session.runner.run(monitor_session.pilot.pause())
    assert not monitor_session.app.following


def test_monitor_app_loads_older_month_on_request(
    monitor_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
) -> None:
    path = monitor_session.directory / "logs" / "2026-08.jsonl.zst"
    path.parent.mkdir()
    with compression.zstd.open(path, "wt") as stream:
        stream.write(
            json.dumps(
                tests.helpers.factories.peri_scribe.monitor.events.record(
                    "Starting command",
                    run_id="archive",
                    command="run",
                ),
            )
            + "\n",
        )
    monitor_session.runner.run(monitor_session.app.refresh_files())
    monitor_session.runner.run(monitor_session.app.load_older())
    assert monitor_session.app.state.runs[0].identifier == "archive"
    monitor_session.runner.run(monitor_session.app.load_older())
    assert len(monitor_session.app.state.runs) == 1


def test_monitor_app_preserves_live_events_arriving_during_archive_loading(
    monitor_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = monitor_session
    tests.helpers.factories.peri_scribe.monitor.events.write_log(
        session.directory,
        tests.helpers.factories.peri_scribe.monitor.events.record(
            "Starting command",
            command="run",
            run_id="initial",
        ),
    )
    archive = session.directory / "logs" / "2026-08.jsonl.zst"
    with compression.zstd.open(archive, "wt") as stream:
        stream.write(
            json.dumps(
                tests.helpers.factories.peri_scribe.monitor.events.record(
                    "Starting command",
                    command="run",
                    run_id="archive",
                ),
            )
            + "\n",
        )
    session.runner.run(session.app.refresh_files())
    started, release = threading.Event(), threading.Event()
    monkeypatch.setattr(
        peri_scribe.monitor.model,
        "append_records",
        tests.helpers.doubles.peri_scribe.monitor.app.BlockedArchiveAppend(
            started=started,
            release=release,
            append=peri_scribe.monitor.model.append_records,
        ),
    )
    session.call(session.app.call_later, session.app.load_older)
    try:
        assert session.runner.run(asyncio.to_thread(started.wait, timeout=5))
        tests.helpers.factories.peri_scribe.monitor.events.write_log(
            session.directory,
            tests.helpers.factories.peri_scribe.monitor.events.record(
                "Starting command",
                command="run",
                run_id="new",
            ),
        )
        session.app.files_changed = True
        session.runner.run(
            tests.helpers.doubles.peri_scribe.monitor.app.tick(session.clock),
        )
    finally:
        release.set()
    session.runner.run(session.pilot.pause())
    session.runner.run(session.app.refresh_files())
    assert [run.identifier for run in session.app.state.runs] == [
        "archive",
        "initial",
        "new",
    ]


def test_monitor_app_preserves_collapsed_branches_during_live_updates(
    monitor_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
) -> None:
    path = (peri_scribe.phases.Segment(phase="fetch"),)
    monitor_session.call(monitor_session.app.tree_nodes[path].collapse)
    tests.helpers.factories.peri_scribe.monitor.events.write_log(
        monitor_session.directory,
        tests.helpers.factories.peri_scribe.monitor.events.record(
            "Starting command",
            command="run",
        ),
    )
    monitor_session.runner.run(monitor_session.app.refresh_files())
    assert not monitor_session.app.tree_nodes[path].is_expanded


def test_monitor_app_preserves_report_scroll_on_refresh(
    monitor_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
) -> None:
    path = monitor_session.app.report_path
    path.write_text("# Report\n\n" + "Paragraph\n\n" * 200)
    monitor_session.runner.run(monitor_session.app.refresh_files())
    monitor_session.runner.run(monitor_session.pilot.press("5"))
    viewer = monitor_session.app.query_one(
        "#report-viewer",
        textual.widgets.MarkdownViewer,
    )
    monitor_session.call(functools.partial(viewer.scroll_page_down, animate=False))
    monitor_session.runner.run(monitor_session.pilot.pause())
    before = viewer.scroll_offset
    assert before.y > 0
    path.write_text(path.read_text() + "New paragraph\n\n")
    monitor_session.runner.run(monitor_session.app.refresh_files())
    monitor_session.runner.run(monitor_session.pilot.pause())
    assert viewer.scroll_offset == before


def test_monitor_app_keeps_status_and_controls_inside_viewport(
    monitor_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
) -> None:
    monitor_session.runner.run(monitor_session.pilot.pause())
    for selector in ("#activity", "#views", "#inspection", "#file-status"):
        region = monitor_session.app.query_one(selector).region
        assert region.y >= 0
        assert region.bottom <= monitor_session.app.size.height


@pytest.mark.parametrize(
    ("tab", "selector"),
    [
        ("pipeline", "#phase-tree"),
        ("pipeline", "#pipeline-stream .events"),
        ("logs", "#log-stream .events"),
        ("runs", "#run-table"),
        ("report", "#report-viewer"),
        ("pipeline", "#inspection"),
    ],
)
def test_monitor_app_scrollbars_keep_terminal_edge_neutral(
    scrolling_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
    tab: str,
    selector: str,
) -> None:
    session = scrolling_session
    session.call(session.app.action_view, tab)
    session.runner.run(session.pilot.pause())
    pane = session.app.query_one(selector)
    assert pane.show_vertical_scrollbar
    backgrounds = set()
    for fraction in (0, 0.4, 1):
        session.call(
            functools.partial(
                pane.scroll_to,
                y=pane.max_scroll_y * fraction,
                animate=False,
            ),
        )
        session.runner.run(session.pilot.pause())
        bar = pane.vertical_scrollbar
        for row in range(bar.region.y, bar.region.bottom):
            style = session.app.screen.get_style_at(session.app.size.width - 1, row)
            backgrounds.add(style.color if style.reverse else style.bgcolor)
    assert len(backgrounds) == 1


def test_monitor_app_preserves_tree_cursor_during_refresh(
    monitor_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
) -> None:
    path = (peri_scribe.phases.Segment(phase="fetch"),)
    tree = monitor_session.app.query_one("#phase-tree", textual.widgets.Tree)
    monitor_session.runner.run(monitor_session.pilot.pause())
    monitor_session.call(tree.move_cursor, monitor_session.app.tree_nodes[path])
    monitor_session.runner.run(monitor_session.app.refresh_files())
    monitor_session.runner.run(monitor_session.pilot.pause())
    assert tree.cursor_node is not None
    assert tree.cursor_node.data is not None
    assert tree.cursor_node.data.path == path


def test_monitor_app_ignores_completed_read_after_views_unmount(
    monitor_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
) -> None:
    monitor_session.runner.run(
        tests.helpers.fixtures.peri_scribe.monitor.application.remove_views(
            monitor_session.app,
        ),
    )
    monitor_session.runner.run(monitor_session.app.refresh_files())
    assert not monitor_session.app.query("#views")


def test_monitor_app_refresh_files_does_not_scroll_a_viewer_removed_during_update(
    monitor_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = monitor_session
    viewer = session.app.query_one("#report-viewer", textual.widgets.MarkdownViewer)
    session.runner.run(session.pilot.press("5"))
    session.app.report_path.write_text("# Updated report")
    monkeypatch.setattr(
        viewer.document,
        "update",
        functools.partial(
            tests.helpers.doubles.peri_scribe.monitor.app.remove_viewer_during_update,
            viewer,
        ),
    )
    scroll = unittest.mock.Mock()
    monkeypatch.setattr(viewer, "scroll_to", scroll)
    session.runner.run(session.app.refresh_files())
    assert not viewer.is_attached
    scroll.assert_not_called()
    assert session.app.report.content == "# Updated report"


def test_monitor_app_does_not_redraw_after_shutdown_begins(
    monitor_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redraw = unittest.mock.Mock()
    monkeypatch.setattr(monitor_session.app, "render_state", redraw)
    with unittest.mock.patch.object(
        type(monitor_session.app),
        "is_running",
        new_callable=unittest.mock.PropertyMock,
        return_value=False,
    ):
        monitor_session.runner.run(monitor_session.app.refresh_files())
    redraw.assert_not_called()


def test_monitor_app_ignores_tab_changes_after_shutdown_begins(
    monitor_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
) -> None:
    inspection = monitor_session.app.query_one("#inspection")
    event = unittest.mock.Mock(
        spec=textual.widgets.TabbedContent.TabActivated,
        pane=unittest.mock.Mock(id="report"),
    )
    with unittest.mock.patch.object(
        type(monitor_session.app),
        "is_running",
        new_callable=unittest.mock.PropertyMock,
        return_value=False,
    ):
        monitor_session.runner.run(monitor_session.app.tab_changed(event))
    assert inspection.display


@pytest.mark.parametrize(
    ("tab", "divider", "before", "after", "dimension", "movement"),
    [
        (
            "pipeline",
            "#pipeline-divider",
            "#phase-tree",
            "#pipeline-stream",
            "width",
            (10, 0),
        ),
        ("pipeline", "#inspection-divider", "#views", "#inspection", "height", (0, -4)),
        ("logs", "#inspection-divider", "#views", "#inspection", "height", (0, -4)),
    ],
)
def test_monitor_app_resizes_panes_by_dragging(
    monitor_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
    *,
    tab: str,
    divider: str,
    before: str,
    after: str,
    dimension: str,
    movement: tuple[int, int],
) -> None:
    session = monitor_session
    session.call(session.app.action_view, tab)
    session.runner.run(session.pilot.pause())
    leading = session.app.query_one(before)
    trailing = session.app.query_one(after)
    initial = getattr(leading.size, dimension)
    total = initial + getattr(trailing.size, dimension)
    session.drag(session.app.query_one(divider), movement)
    change = movement[0] if dimension == "width" else movement[1]
    assert getattr(leading.size, dimension) == initial + change
    assert getattr(leading.size, dimension) + getattr(trailing.size, dimension) == total
    assert session.app.mouse_captured is None


@pytest.mark.parametrize("tab", ["runs", "report"])
def test_monitor_app_hides_inspection_divider_on_single_pane_tabs(
    monitor_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
    tab: str,
) -> None:
    session = monitor_session
    session.call(session.app.action_view, tab)
    session.runner.run(session.pilot.pause())
    assert not session.app.query_one("#inspection-divider").display


def test_monitor_app_preserves_resized_panes_after_refresh_and_tab_changes(
    monitor_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
) -> None:
    session = monitor_session
    session.drag(session.app.query_one("#pipeline-divider"), (10, 0))
    session.drag(session.app.query_one("#inspection-divider"), (0, -4))
    tree = session.app.query_one("#phase-tree")
    inspection = session.app.query_one("#inspection")
    sizes = (tree.size, inspection.size)
    session.runner.run(session.app.refresh_files())
    session.runner.run(session.pilot.press("4", "5", "3", "2"))
    assert (tree.size, inspection.size) == sizes


@pytest.mark.parametrize(("width", "height"), [(80, 24), (160, 50)])
def test_monitor_app_resized_panes_fit_after_terminal_resize(
    monitor_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
    width: int,
    height: int,
) -> None:
    session = monitor_session
    session.drag(session.app.query_one("#pipeline-divider"), (10, 0))
    session.drag(session.app.query_one("#inspection-divider"), (0, -4))
    tree = session.app.query_one("#phase-tree")
    stream = session.app.query_one("#pipeline-stream")
    proportion = tree.size.width / (tree.size.width + stream.size.width)
    session.runner.run(session.pilot.resize_terminal(width, height))
    assert tree.size.width / (tree.size.width + stream.size.width) == pytest.approx(
        proportion,
        abs=0.02,
    )
    for selector in ("#phase-tree", "#pipeline-stream", "#inspection", "Footer"):
        region = session.app.query_one(selector).region
        assert region.width > 0
        assert region.height > 0
        assert region.right <= width
        assert region.bottom <= height
