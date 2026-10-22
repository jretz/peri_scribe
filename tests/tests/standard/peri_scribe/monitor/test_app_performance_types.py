"""Mode-specific performance charts retain their own duration and histogram scales."""

import pytest
import textual.widgets

import peri_scribe.monitor.performance_widgets
import tests.helpers.factories.peri_scribe.monitor.events
import tests.helpers.factories.peri_scribe.monitor.status
import tests.helpers.fixtures.peri_scribe.monitor.application


@pytest.mark.asyncio
async def test_monitor_app_performance_separates_modes_within_the_run_command(
    monitor_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
) -> None:
    for identifier, options, phase, elapsed, decision in (
        ("conditional", {}, "geography", 100, None),
        ("fetch", {"only_stage": "fetch"}, "fetch", 1, None),
        ("unconditional", {"unconditional": True}, "geography", 1000, None),
        ("deferred", {}, "fetch", 2, {"event": "Publication gate skipped"}),
        (
            "unchanged",
            {},
            "fetch",
            3,
            {"event": "Skipped phases", "phases": ["geography"]},
        ),
    ):
        records = [
            tests.helpers.factories.peri_scribe.monitor.status.record(
                "Starting command",
                run_id=identifier,
                command="run",
                parameters=options,
            ),
            tests.helpers.factories.peri_scribe.monitor.status.record(
                "Finished phase",
                run_id=identifier,
                phase=phase,
                status="completed",
            ),
        ]
        if decision is not None:
            records.append(
                tests.helpers.factories.peri_scribe.monitor.status.record(
                    str(decision["event"]),
                    run_id=identifier,
                )
                | decision,
            )
        records.append(
            tests.helpers.factories.peri_scribe.monitor.status.record(
                "Finished command",
                run_id=identifier,
                status="completed",
                duration={"value": elapsed, "units": "seconds"},
            ),
        )
        tests.helpers.factories.peri_scribe.monitor.events.write_log(
            monitor_session.directory,
            *records,
        )
    await monitor_session.app.refresh_files()
    pane = monitor_session.app.query_one(
        peri_scribe.monitor.performance_widgets.PerformancePane,
    )
    assert [series.command for series in pane.series] == [
        "Fetch only",
        "Fetch only · publication deferred",
        "Fetch only · unchanged",
        "Conditional build",
        "Unconditional build",
    ]
    assert [series.samples[0].duration.magnitude for series in pane.series] == [
        1,
        2,
        3,
        100,
        1000,
    ]
    await monitor_session.pilot.press("6")
    chart = pane.query_one("#performance-charts", textual.widgets.Static)
    assert all(series.command in str(chart.content) for series in pane.series)
