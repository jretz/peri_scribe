"""Mouse-wheel steps keep content movement predictable across monitor panes."""

import functools

import pytest
import textual.events

import tests.helpers.fixtures.peri_scribe.monitor.application
import tests.helpers.textual


@pytest.mark.parametrize(
    ("view", "selector"),
    [
        ("pipeline", "#phase-tree"),
        ("pipeline", "#pipeline-stream .events"),
        ("logs", "#log-stream .events"),
        ("runs", "#run-table"),
        ("report", "#report-viewer"),
        ("pipeline", "#inspection"),
        ("palette", "CommandList"),
    ],
)
@pytest.mark.parametrize(
    ("event_type", "distance"),
    [(textual.events.MouseScrollDown, 1), (textual.events.MouseScrollUp, -1)],
)
@pytest.mark.asyncio
async def test_monitor_app_scrolls_one_row_per_wheel_event(
    scrolling_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
    view: str,
    selector: str,
    event_type: type[textual.events.MouseEvent],
    distance: int,
) -> None:
    session = scrolling_session
    if view == "palette":
        await session.pilot.resize_terminal(80, 20)
        await tests.helpers.textual.invoke(session.app.search_themes)
    else:
        await tests.helpers.textual.invoke(session.app.action_view, view)
        await session.app.refresh_files()
    await session.refresh()
    pane = session.app.screen.query_one(selector)
    initial_offset = 3
    await tests.helpers.textual.invoke(
        functools.partial(
            pane.scroll_to,
            y=initial_offset,
            animate=False,
            immediate=True,
        ),
    )
    await session.pilot.pause()
    assert pane.scroll_offset.y == initial_offset
    await tests.helpers.textual.invoke(
        pane.post_message,
        event_type(
            pane,
            x=1,
            y=1,
            delta_x=0,
            delta_y=0,
            button=0,
            shift=False,
            meta=False,
            ctrl=False,
        ),
    )
    await session.pilot.pause()
    assert pane.scroll_offset.y == initial_offset + distance
