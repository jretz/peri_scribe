"""Status hues cover complete rows without changing stripe brightness."""

import functools

import pytest

import peri_scribe.monitor.widgets
import tests.helpers.assertions.peri_scribe.monitor.striping
import tests.helpers.factories.peri_scribe.monitor.events
import tests.helpers.fixtures.peri_scribe.monitor.application


@pytest.mark.parametrize("theme", ["flexoki", "textual-light"])
@pytest.mark.parametrize("view", ["pipeline", "logs"])
def test_monitor_app_tints_severe_events_without_changing_stripe_brightness(
    color_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
    theme: str,
    view: str,
) -> None:
    session = color_session
    tests.helpers.factories.peri_scribe.monitor.events.write_log(
        session.directory,
        *(
            tests.helpers.factories.peri_scribe.monitor.events.record(
                f"Event {index}",
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
    session.runner.run(session.app.refresh_files())
    session.call(setattr, session.app, "theme", theme)
    session.call(session.app.action_view, view)
    session.runner.run(session.pilot.pause())
    table = session.app.query_one(
        "#pipeline-stream .events" if view == "pipeline" else "#log-stream .events",
        peri_scribe.monitor.widgets.EventTable,
    )
    colors = [
        session.call(
            tests.helpers.assertions.peri_scribe.monitor.striping.row_backgrounds,
            table,
            "row",
            index,
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
    session.runner.run(session.pilot.resize_terminal(120, 24))
    session.call(functools.partial(table.scroll_to, y=1, animate=False, immediate=True))
    session.runner.run(session.pilot.pause())
    assert table.scroll_offset.y == 1
    assert (
        session.call(
            tests.helpers.assertions.peri_scribe.monitor.striping.row_backgrounds,
            table,
            "row",
            3,
        )
        == colors[2]
    )


@pytest.mark.parametrize("theme", ["flexoki", "textual-light"])
def test_monitor_app_tints_finished_runs_without_changing_stripe_brightness(
    color_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
    theme: str,
) -> None:
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
    session.runner.run(session.app.refresh_files())
    session.call(setattr, session.app, "theme", theme)
    session.call(session.app.action_view, "runs")
    session.runner.run(session.pilot.pause())
    table = session.app.query_one("#run-table", peri_scribe.monitor.widgets.TintedTable)
    colors = [
        session.call(
            tests.helpers.assertions.peri_scribe.monitor.striping.row_backgrounds,
            table,
            "row",
            index,
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
