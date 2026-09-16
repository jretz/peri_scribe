"""Mouse-wheel steps keep content movement predictable across monitor panes."""

import functools
import typing

import pytest
import textual.events


if typing.TYPE_CHECKING:
    import tests.helpers.fixtures.peri_scribe.monitor.application


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
def test_monitor_app_scrolls_one_row_per_wheel_event(
    scrolling_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
    view: str,
    selector: str,
    event_type: type[textual.events.MouseEvent],
    distance: int,
) -> None:
    session = scrolling_session
    if view == "palette":
        session.runner.run(session.pilot.resize_terminal(80, 20))
        session.call(session.app.search_themes)
    else:
        session.call(session.app.action_view, view)
    session.runner.run(session.pilot.pause())
    pane = session.app.screen.query_one(selector)
    initial_offset = 3
    session.call(
        functools.partial(
            pane.scroll_to,
            y=initial_offset,
            animate=False,
            immediate=True,
        ),
    )
    session.runner.run(session.pilot.pause())
    assert pane.scroll_offset.y == initial_offset
    session.call(
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
    session.runner.run(session.pilot.pause())
    assert pane.scroll_offset.y == initial_offset + distance
