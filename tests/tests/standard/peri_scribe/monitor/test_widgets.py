"""Report navigation distinguishes document anchors from external URLs."""

import unittest.mock

import pytest
import textual.widgets

import peri_scribe.monitor.widgets
import tests.helpers.fixtures.peri_scribe.monitor.application
import tests.helpers.fixtures.peri_scribe.monitor.widgets
import tests.helpers.textual


@pytest.mark.parametrize("key", ["down", "pagedown", "right", "x"])
@pytest.mark.asyncio
async def test_event_table_on_key_keeps_following_for_other_keys(
    monitor_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
    key: str,
) -> None:
    session = monitor_session
    table = session.app.query_one(
        "#pipeline-stream",
        peri_scribe.monitor.widgets.Stream,
    ).query_one(
        peri_scribe.monitor.widgets.EventTable,
    )
    await tests.helpers.textual.invoke(table.focus)
    await session.pilot.press(key)
    assert session.app.following


@pytest.mark.parametrize("href", ["#moonshine", "https://example.com/fire"])
@pytest.mark.asyncio
async def test_report_viewer_routes_links_without_loading_another_file(
    report_session: tests.helpers.fixtures.peri_scribe.monitor.widgets.ReportSession,
    monkeypatch: pytest.MonkeyPatch,
    href: str,
) -> None:
    session = report_session
    open_url = unittest.mock.Mock()
    monkeypatch.setattr(session.app, "open_url", open_url)
    viewer = session.app.query_one(textual.widgets.MarkdownViewer)
    original = viewer.document.source
    await tests.helpers.textual.invoke(
        viewer.document.post_message,
        textual.widgets.Markdown.LinkClicked(viewer.document, href),
    )
    await session.refresh()
    assert viewer.document.source == original
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
@pytest.mark.asyncio
async def test_pane_divider_resizes_with_arrow_keys(
    monitor_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
    selector: str,
    dimension: str,
    key: str,
    change: int,
) -> None:
    session = monitor_session
    divider = session.app.query_one(selector, peri_scribe.monitor.widgets.PaneDivider)
    initial = getattr(divider.before.size, dimension)
    await tests.helpers.textual.invoke(divider.focus)
    await session.pilot.press(key)
    assert getattr(divider.before.size, dimension) == initial + change
    assert session.app.following


@pytest.mark.parametrize("selector", ["#pipeline-divider", "#inspection-divider"])
@pytest.mark.parametrize("requested", [-1000, 1000])
@pytest.mark.asyncio
async def test_pane_divider_keeps_both_panes_visible_at_drag_limits(
    divider_session: tests.helpers.fixtures.peri_scribe.monitor.widgets.DividerSession,
    selector: str,
    requested: int,
) -> None:
    session = divider_session
    divider = session.app.query_one(selector, peri_scribe.monitor.widgets.PaneDivider)
    total = getattr(divider.before.size, divider.dimension) + getattr(
        divider.after.size,
        divider.dimension,
    )
    await tests.helpers.textual.invoke(divider.resize_panes, requested)
    await session.refresh()
    before = getattr(divider.before.size, divider.dimension)
    after = getattr(divider.after.size, divider.dimension)
    assert before >= (24 if divider.dimension == "width" else 8)
    assert after >= (24 if divider.dimension == "width" else 3)
    assert before + after == total


@pytest.mark.asyncio
async def test_pane_divider_released_mouse_does_not_resize(
    divider_session: tests.helpers.fixtures.peri_scribe.monitor.widgets.DividerSession,
) -> None:
    session = divider_session
    divider = session.app.query_one(
        "#pipeline-divider",
        peri_scribe.monitor.widgets.PaneDivider,
    )
    await session.drag(divider, (10, 0))
    size = divider.before.size
    await session.pilot.hover(divider)
    await session.pilot.hover(offset=(10, 10))
    assert divider.before.size == size


@pytest.mark.asyncio
async def test_pane_divider_ignores_secondary_mouse_button(
    divider_session: tests.helpers.fixtures.peri_scribe.monitor.widgets.DividerSession,
) -> None:
    session = divider_session
    divider = session.app.query_one(
        "#pipeline-divider",
        peri_scribe.monitor.widgets.PaneDivider,
    )
    initial = divider.before.size
    await session.pilot.mouse_down(divider, button=3)
    assert session.app.mouse_captured is None
    await session.pilot.hover(offset=(10, 10))
    await session.pilot.mouse_up(divider)
    assert divider.before.size == initial


@pytest.mark.asyncio
async def test_pane_divider_ignores_unrelated_keys(
    divider_session: tests.helpers.fixtures.peri_scribe.monitor.widgets.DividerSession,
) -> None:
    session = divider_session
    divider = session.app.query_one(
        "#pipeline-divider",
        peri_scribe.monitor.widgets.PaneDivider,
    )
    initial = divider.before.size
    await tests.helpers.textual.invoke(divider.focus)
    await session.pilot.press("up", "down", "x")
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
@pytest.mark.asyncio
async def test_pane_divider_renders_blank_cells(
    divider_session: tests.helpers.fixtures.peri_scribe.monitor.widgets.DividerSession,
    selector: str,
    *,
    focused: bool,
) -> None:
    session = divider_session
    divider = session.app.query_one(selector, peri_scribe.monitor.widgets.PaneDivider)
    if focused:
        await tests.helpers.textual.invoke(divider.focus)
    await session.refresh()
    lines = await tests.helpers.textual.invoke(
        divider.render_lines,
        divider.size.region,
    )
    assert len(lines) == divider.size.height
    assert all(line.text == " " * divider.size.width for line in lines)
