"""Mouse-wheel steps keep content movement predictable across monitor panes."""

import functools

import pytest
import textual.events
import textual.widgets

import tests.helpers.fixtures.peri_scribe.monitor.application
import tests.helpers.textual


async def assert_scrolls_one_row_per_wheel_event(
    scrolling_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
    subtests: pytest.Subtests,
    view: str,
    selector: str,
) -> None:
    """Check both actual wheel messages at a fixed native viewport offset.

    Args:
        scrolling_session: The mounted monitor with overflowing native panes.
        subtests: Names each native observation or pane.
        view: The tab containing the observed native pane.
        selector: The mounted widget to observe.
    """
    session = scrolling_session
    if view == "palette":
        await session.resize(80, 20)
        await tests.helpers.textual.invoke(session.app.search_themes)
        await session.command_results()
    else:
        await session.show_view(view)
    await session.refresh()
    pane = session.app.screen.query_one(selector)
    initial_offset = 3
    following = session.app.following
    # Scrolling up in an event table pauses following, so exercise it last.
    for event_type, distance in (
        (textual.events.MouseScrollDown, 1),
        (textual.events.MouseScrollUp, -1),
    ):
        with subtests.test(event=event_type.__name__):
            await tests.helpers.textual.invoke(
                functools.partial(
                    pane.scroll_to,
                    y=initial_offset,
                    animate=False,
                    immediate=True,
                ),
            )
            await session.refresh()
            assert pane.scroll_offset.y == initial_offset
            assert session.app.following == following
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
            await session.refresh()
            assert pane.scroll_offset.y == initial_offset + distance


@pytest.mark.asyncio
async def test_monitor_app_scrolls_one_row_per_wheel_event(
    scrolling_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
    subtests: pytest.Subtests,
) -> None:
    session = scrolling_session
    for view, selector in (
        ("pipeline", "#phase-tree"),
        ("pipeline", "#pipeline-stream .events"),
        ("logs", "#log-stream .events"),
        ("runs", "#run-table"),
        ("report", "#report-viewer"),
        ("pipeline", "#inspection"),
        ("palette", "CommandList"),
    ):
        with subtests.test(view=view, selector=selector):
            await tests.helpers.textual.invoke(session.app.action_live)
            await session.show_view_from_pipeline("pipeline")
            if selector == "#inspection":
                for name in ("#details", "#decisions"):
                    await tests.helpers.textual.invoke(
                        session.app.query_one(name, textual.widgets.Static).update,
                        session.app.report_path.read_text(),
                    )
            await assert_scrolls_one_row_per_wheel_event(
                session,
                subtests,
                view,
                selector,
            )
