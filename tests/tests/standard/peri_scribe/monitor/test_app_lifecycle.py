"""Controls outside the mounted terminal cannot schedule presentation work."""

import pathlib

import peri_scribe.monitor.app
import tests.helpers.factories.peri_scribe.monitor.events


def test_monitor_app_filter_changed_before_mount(monitor_year: pathlib.Path) -> None:
    app = peri_scribe.monitor.app.MonitorApp(
        monitor_year,
        monitor_year / "report.md",
        tests.helpers.factories.peri_scribe.monitor.events.BRANCHES,
    )
    app.filter_changed()
    assert app.controller.display_task is None
    assert app.controller.generation == 0
