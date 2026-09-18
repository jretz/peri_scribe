"""Check row shading in the composed monitor, including built-in option lists."""

import functools

import pytest
import textual.command
import textual.widgets

import tests.helpers.assertions.peri_scribe.monitor.striping
import tests.helpers.fixtures.peri_scribe.monitor.application
import tests.helpers.textual


@pytest.mark.parametrize("theme", ["flexoki", "textual-light"])
@pytest.mark.parametrize(
    ("view", "selector", "metadata"),
    [
        ("pipeline", "#phase-tree", "line"),
        ("pipeline", "#pipeline-stream .events", "row"),
        ("logs", "#log-stream .events", "row"),
        ("runs", "#run-table", "row"),
    ],
)
@pytest.mark.asyncio
async def test_monitor_app_stripes_rows_across_the_full_width_after_scrolling(
    scrolling_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
    theme: str,
    view: str,
    selector: str,
    metadata: str,
) -> None:
    session = scrolling_session
    await tests.helpers.textual.invoke(setattr, session.app, "theme", theme)
    await tests.helpers.textual.invoke(session.app.action_view, view)
    await session.pilot.pause()
    widget = session.app.query_one(selector)
    backgrounds = []
    for offset in (0, 1):
        await tests.helpers.textual.invoke(
            functools.partial(
                widget.scroll_to,
                y=offset,
                animate=False,
                immediate=True,
            ),
        )
        await session.pilot.pause()
        colors = [
            (
                await tests.helpers.textual.invoke(
                    tests.helpers.assertions.peri_scribe.monitor.striping.row_backgrounds,
                    widget,
                    metadata,
                    index,
                )
            )
            for index in (1, 2, 3)
        ]
        assert all(len(color) == 1 for color in colors)
        assert colors[0] == colors[2] != colors[1]
        backgrounds.append(colors)
    assert backgrounds[0] == backgrounds[1]


@pytest.mark.parametrize("theme", ["flexoki", "textual-light"])
@pytest.mark.parametrize("palette", [False, True])
@pytest.mark.asyncio
async def test_monitor_app_stripes_options_without_overwriting_selection(
    monitor_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
    theme: str,
    *,
    palette: bool,
) -> None:
    session = monitor_session
    await tests.helpers.textual.invoke(setattr, session.app, "theme", theme)
    if palette:
        await session.pilot.resize_terminal(60, 42)
        await session.pilot.press("ctrl+p")
        widget = session.app.screen.query_one(textual.command.CommandList)
    else:
        select = session.app.query_one(
            "#pipeline-stream .severity",
            textual.widgets.Select,
        )
        await tests.helpers.textual.invoke(select.action_show_overlay)
        widget = select.query_one(textual.widgets.OptionList)
    await tests.helpers.textual.invoke(setattr, widget, "highlighted", 0)
    await session.pilot.pause()
    colors = [
        (
            await tests.helpers.textual.invoke(
                tests.helpers.assertions.peri_scribe.monitor.striping.row_backgrounds,
                widget,
                "option",
                index,
            )
        )
        for index in range(4)
    ]
    assert all(len(color) == 1 for color in colors)
    assert colors[1] == colors[3] != colors[2]
    assert colors[0] not in colors[1:]
    await tests.helpers.textual.invoke(setattr, widget, "highlighted", 1)
    await session.pilot.pause()
    selected = await tests.helpers.textual.invoke(
        tests.helpers.assertions.peri_scribe.monitor.striping.row_backgrounds,
        widget,
        "option",
        1,
    )
    assert selected == colors[0]
