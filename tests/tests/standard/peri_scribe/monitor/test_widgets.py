"""Report navigation distinguishes document anchors from external URLs."""

import typing
import unittest.mock

import pytest
import textual.widgets

import peri_scribe.monitor.widgets


if typing.TYPE_CHECKING:
    import tests.helpers.fixtures.peri_scribe.monitor.application


@pytest.mark.parametrize("href", ["#moonshine", "https://example.com/fire"])
def test_report_viewer_routes_links_without_loading_another_file(
    monitor_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
    monkeypatch: pytest.MonkeyPatch,
    href: str,
) -> None:
    open_url = unittest.mock.Mock()
    monkeypatch.setattr(monitor_session.app, "open_url", open_url)
    monitor_session.app.report_path.write_text("# Report\n\n## Moonshine\n\nDetails")
    monitor_session.runner.run(monitor_session.app.refresh_files())
    viewer = monitor_session.app.query_one(textual.widgets.MarkdownViewer)
    monitor_session.call(
        viewer.document.post_message,
        textual.widgets.Markdown.LinkClicked(viewer.document, href),
    )
    monitor_session.runner.run(monitor_session.pilot.pause())
    assert viewer.document.source == monitor_session.app.report.content
    if href.startswith("#"):
        open_url.assert_not_called()
    else:
        open_url.assert_called_once_with(href)


@pytest.mark.parametrize(
    ("selector", "dimension", "key", "change"),
    [
        ("#pipeline-divider", "width", "right", 1),
        ("#pipeline-divider", "width", "left", -1),
        ("#inspection-divider", "height", "up", -1),
        ("#inspection-divider", "height", "down", 1),
    ],
)
def test_pane_divider_resizes_with_arrow_keys(
    monitor_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
    selector: str,
    dimension: str,
    key: str,
    change: int,
) -> None:
    session = monitor_session
    divider = session.app.query_one(selector, peri_scribe.monitor.widgets.PaneDivider)
    initial = getattr(divider.before.size, dimension)
    session.call(divider.focus)
    session.runner.run(session.pilot.press(key))
    assert getattr(divider.before.size, dimension) == initial + change
    assert session.app.following


@pytest.mark.parametrize("selector", ["#pipeline-divider", "#inspection-divider"])
@pytest.mark.parametrize("requested", [-1000, 1000])
def test_pane_divider_keeps_both_panes_visible_at_drag_limits(
    monitor_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
    selector: str,
    requested: int,
) -> None:
    session = monitor_session
    divider = session.app.query_one(selector, peri_scribe.monitor.widgets.PaneDivider)
    total = getattr(divider.before.size, divider.dimension) + getattr(
        divider.after.size,
        divider.dimension,
    )
    session.call(divider.resize_panes, requested)
    session.runner.run(session.pilot.pause())
    before = getattr(divider.before.size, divider.dimension)
    after = getattr(divider.after.size, divider.dimension)
    assert before >= (24 if divider.dimension == "width" else 8)
    assert after >= (24 if divider.dimension == "width" else 3)
    assert before + after == total


def test_pane_divider_released_mouse_does_not_resize(
    monitor_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
) -> None:
    session = monitor_session
    divider = session.app.query_one(
        "#pipeline-divider",
        peri_scribe.monitor.widgets.PaneDivider,
    )
    session.drag(divider, (10, 0))
    size = divider.before.size
    session.runner.run(session.pilot.hover(divider))
    session.runner.run(session.pilot.hover(offset=(10, 10)))
    assert divider.before.size == size


def test_pane_divider_ignores_secondary_mouse_button(
    monitor_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
) -> None:
    session = monitor_session
    divider = session.app.query_one(
        "#pipeline-divider",
        peri_scribe.monitor.widgets.PaneDivider,
    )
    initial = divider.before.size
    session.runner.run(session.pilot.mouse_down(divider, button=3))
    assert session.app.mouse_captured is None
    session.runner.run(session.pilot.hover(offset=(10, 10)))
    session.runner.run(session.pilot.mouse_up(divider))
    assert divider.before.size == initial


def test_pane_divider_ignores_unrelated_keys(
    monitor_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
) -> None:
    session = monitor_session
    divider = session.app.query_one(
        "#pipeline-divider",
        peri_scribe.monitor.widgets.PaneDivider,
    )
    initial = divider.before.size
    session.call(divider.focus)
    session.runner.run(session.pilot.press("up", "down", "x"))
    assert divider.before.size == initial


def test_pane_divider_ignores_resize_before_layout() -> None:
    before = textual.widgets.Static()
    divider = peri_scribe.monitor.widgets.PaneDivider(
        before,
        textual.widgets.Static(),
        dimension=peri_scribe.monitor.widgets.Dimension.WIDTH,
        identifier="divider",
    )
    divider.resize_panes(10)
    assert before.styles.width is None


@pytest.mark.parametrize("selector", ["#pipeline-divider", "#inspection-divider"])
@pytest.mark.parametrize("focused", [False, True])
def test_pane_divider_renders_blank_cells(
    monitor_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
    selector: str,
    *,
    focused: bool,
) -> None:
    session = monitor_session
    divider = session.app.query_one(selector, peri_scribe.monitor.widgets.PaneDivider)
    if focused:
        session.call(divider.focus)
    session.runner.run(session.pilot.pause())
    lines = session.call(divider.render_lines, divider.size.region)
    assert len(lines) == divider.size.height
    assert all(line.text == " " * divider.size.width for line in lines)
