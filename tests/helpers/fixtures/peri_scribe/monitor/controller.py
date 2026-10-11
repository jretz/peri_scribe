"""Expose the first complete health frame before allowing background content."""

import collections.abc
import dataclasses
import pathlib
import typing
import unittest.mock

import pytest
import pytest_asyncio
import time_machine

import peri_scribe.monitor.app
import peri_scribe.monitor.session
import tests.helpers.factories.peri_scribe.monitor.events
import tests.helpers.factories.peri_scribe.monitor.status
import tests.helpers.textual


@dataclasses.dataclass(frozen=True, kw_only=True)
class Session(tests.helpers.textual.Session[peri_scribe.monitor.app.MonitorApp]):
    """Keep the paint acknowledgement under explicit scenario control."""

    begin_background: collections.abc.Callable[[], None]


@pytest.fixture
def unmounted_monitor(monitor_year: pathlib.Path) -> peri_scribe.monitor.app.MonitorApp:
    """Keep shutdown-before-start scenarios independent of a terminal message loop.

    Args:
        monitor_year: The scenario's isolated log and report directory.

    Returns:
        A configured application that has not admitted any work.
    """
    return peri_scribe.monitor.app.MonitorApp(
        monitor_year,
        monitor_year / "report.md",
        tests.helpers.factories.peri_scribe.monitor.events.BRANCHES,
    )


@pytest_asyncio.fixture
async def initial_monitor(
    monitor_year: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> typing.AsyncIterator[Session]:
    """Hold background preparation while preserving the actual health reader and UI.

    Args:
        monitor_year: The scenario's isolated log and report directory.
        monkeypatch: Restores automatic observation and paint acknowledgement.

    Yields:
        A mounted terminal whose initial health is complete.
    """
    monkeypatch.setattr(peri_scribe.monitor.session, "watch", unittest.mock.AsyncMock())
    monkeypatch.setattr(peri_scribe.monitor.session, "clock", unittest.mock.AsyncMock())
    tests.helpers.factories.peri_scribe.monitor.events.write_log(
        monitor_year,
        tests.helpers.factories.peri_scribe.monitor.events.record(
            "Starting command",
            command="run",
        ),
        tests.helpers.factories.peri_scribe.monitor.events.record("Alpha event"),
        tests.helpers.factories.peri_scribe.monitor.events.record("Beta event"),
    )
    report_path = monitor_year / "report.md"
    report_path.write_text("# The complete report\n")
    app = peri_scribe.monitor.app.MonitorApp(
        monitor_year,
        report_path,
        tests.helpers.factories.peri_scribe.monitor.events.BRANCHES,
    )
    begin_background = app.controller.begin_background
    monkeypatch.setattr(app.controller, "begin_background", unittest.mock.Mock())
    with time_machine.travel(
        tests.helpers.factories.peri_scribe.monitor.status.NOW,
        tick=False,
    ):
        async with tests.helpers.textual.mounted(app) as session:
            yield Session(
                app=app,
                pilot=session.pilot,
                begin_background=begin_background,
            )
