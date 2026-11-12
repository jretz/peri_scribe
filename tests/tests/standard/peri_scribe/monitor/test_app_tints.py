"""Status hues cover complete rows without changing stripe brightness."""

import functools

import pytest

import peri_scribe.monitor.widgets
import tests.helpers.assertions.peri_scribe.monitor.striping
import tests.helpers.factories.peri_scribe.monitor.events
import tests.helpers.fixtures.peri_scribe.monitor.application
import tests.helpers.textual


async def assert_tints_severe_events_without_changing_stripe_brightness(
    color_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
    subtests: pytest.Subtests,
    theme: str,
) -> None:
    """Check severe-event colors before the same command enters the run-list probes.

    Args:
        color_session: The mounted monitor with terminal colors enabled.
        subtests: Names each native observation or pane.
        theme: The terminal palette under observation.
    """
    session = color_session
    tests.helpers.factories.peri_scribe.monitor.events.write_log(
        session.directory,
        *(
            tests.helpers.factories.peri_scribe.monitor.events.record(
                f"Event {index}",
                run_id="0",
                level=level,
            )
            for index, level in enumerate(
                (
                    "info",
                    "info",
                    "info",
                    "warning",
                    "warning",
                    "error",
                    "error",
                    "critical",
                    "critical",
                    "info",
                ),
            )
        ),
    )
    await session.app.refresh_files()
    await tests.helpers.textual.invoke(setattr, session.app, "theme", theme)
    with subtests.test(view="pipeline"):
        await assert_severe_event_tints(session, "pipeline", "#pipeline-stream .events")
    await session.resize(*tests.helpers.textual.DEFAULT_TERMINAL_SIZE)
    with subtests.test(view="logs"):
        await assert_severe_event_tints(session, "logs", "#log-stream .events")


async def assert_severe_event_tints(
    session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
    view: str,
    selector: str,
) -> None:
    """Check row colors before and after scrolling moves a tinted row on screen.

    Args:
        session: The seeded monitor at its default terminal size.
        view: The monitor tab containing the event table.
        selector: The event table to inspect on that tab.
    """
    await session.show_view(view)
    table = session.app.query_one(selector, peri_scribe.monitor.widgets.EventTable)
    colors = [
        (
            await tests.helpers.textual.invoke(
                tests.helpers.assertions.peri_scribe.monitor.striping.row_backgrounds,
                table,
                "row",
                index,
            )
        )
        for index in range(1, 9)
    ]
    assert all(len(color) == 1 for color in colors)
    for index in range(3, 9):
        neutral = colors[0 if index % 2 else 1]
        tinted = colors[index - 1]
        tests.helpers.assertions.peri_scribe.monitor.striping.assert_tint_preserves_brightness(
            tinted,
            neutral,
        )
    assert colors[2] != colors[4]
    await session.resize(120, 24)
    await tests.helpers.textual.invoke(
        functools.partial(table.scroll_to, y=1, animate=False, immediate=True),
    )
    await session.refresh()
    assert table.scroll_offset.y == 1
    assert (
        await tests.helpers.textual.invoke(
            tests.helpers.assertions.peri_scribe.monitor.striping.row_backgrounds,
            table,
            "row",
            3,
        )
    ) == colors[2]


async def assert_tints_finished_runs_without_changing_stripe_brightness(
    color_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
    theme: str,
) -> None:
    """Check native run outcomes while retaining the preceding command evidence.

    Args:
        color_session: The mounted monitor with terminal colors enabled.
        theme: The terminal palette under observation.
    """
    session = color_session
    for index, status in enumerate(
        ("open", "completed", "completed", "failed", "failed", "open", "open"),
    ):
        records = [
            tests.helpers.factories.peri_scribe.monitor.events.record(
                "Starting command",
                run_id=str(index),
                command="run",
            ),
        ]
        if status != "open":
            records.append(
                tests.helpers.factories.peri_scribe.monitor.events.record(
                    "Finished command",
                    run_id=str(index),
                    status=status,
                ),
            )
        tests.helpers.factories.peri_scribe.monitor.events.write_log(
            session.directory,
            *records,
        )
    await session.app.refresh_files()
    await tests.helpers.textual.invoke(setattr, session.app, "theme", theme)
    await session.show_view("runs")
    table = session.app.query_one("#run-table", peri_scribe.monitor.widgets.TintedTable)
    colors = [
        (
            await tests.helpers.textual.invoke(
                tests.helpers.assertions.peri_scribe.monitor.striping.row_backgrounds,
                table,
                "row",
                index,
            )
        )
        for index in range(1, 7)
    ]
    assert all(len(color) == 1 for color in colors)
    for index in range(2, 6):
        neutral = colors[0 if index % 2 else 5]
        tinted = colors[index - 1]
        tests.helpers.assertions.peri_scribe.monitor.striping.assert_tint_preserves_brightness(
            tinted,
            neutral,
        )
    assert colors[1] != colors[3]


@pytest.mark.parametrize("theme", ["flexoki", "textual-light"])
@pytest.mark.asyncio
async def test_monitor_app_tints_preserve_native_stripes_for_events_and_runs(
    color_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
    subtests: pytest.Subtests,
    theme: str,
) -> None:
    session = color_session
    with subtests.test(
        scenario="tints_severe_events_without_changing_stripe_brightness",
    ):
        await assert_tints_severe_events_without_changing_stripe_brightness(
            session,
            subtests,
            theme,
        )
    await session.resize(*tests.helpers.textual.DEFAULT_TERMINAL_SIZE)
    with subtests.test(
        scenario="tints_finished_runs_without_changing_stripe_brightness",
    ):
        await assert_tints_finished_runs_without_changing_stripe_brightness(
            session,
            theme,
        )
