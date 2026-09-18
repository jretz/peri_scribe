"""Run the real terminal adapter on each async test's isolated event loop."""

import collections.abc
import dataclasses
import functools
import pathlib
import typing
import unittest.mock

import pytest
import pytest_asyncio
import textual.constants
import textual.widgets
import time_machine

import peri_scribe.monitor.app
import tests.helpers.factories.peri_scribe.monitor.events
import tests.helpers.factories.peri_scribe.monitor.status
import tests.helpers.textual


@dataclasses.dataclass(frozen=True, kw_only=True)
class Session(tests.helpers.textual.Session[peri_scribe.monitor.app.MonitorApp]):
    """One event loop keeps terminal tasks alive between test actions."""

    directory: pathlib.Path
    clock: collections.abc.Callable[[], object]


@pytest_asyncio.fixture
async def monitor_session(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> typing.AsyncIterator[Session]:
    """Control file refreshes and terminal capabilities independently of the host.

    Args:
        tmp_path: The current test's isolated filesystem.
        monkeypatch: Fixes color support and pauses automatic file reads.

    Yields:
        A headless terminal running on the current test's event loop.
    """
    monkeypatch.setattr(textual.constants, "COLOR_SYSTEM", "truecolor")
    monkeypatch.setattr(
        peri_scribe.monitor.app,
        "watch_files",
        unittest.mock.AsyncMock(),
    )
    directory = tmp_path / "2026"
    directory.mkdir()
    app = peri_scribe.monitor.app.MonitorApp(
        directory,
        directory / "report.md",
        tests.helpers.factories.peri_scribe.monitor.events.BRANCHES,
    )
    interval = unittest.mock.Mock(
        wraps=functools.partial(app.set_interval, pause=True),
    )
    monkeypatch.setattr(app, "set_interval", interval)
    with time_machine.travel(
        tests.helpers.factories.peri_scribe.monitor.status.NOW,
        tick=False,
    ):
        async with tests.helpers.textual.mounted(app) as session:
            await tests.helpers.textual.invoke(app.action_view, "pipeline")
            await session.refresh()
            yield Session(
                app=app,
                pilot=session.pilot,
                directory=directory,
                clock=interval.call_args.args[1],
            )


async def remove_views(app: peri_scribe.monitor.app.MonitorApp) -> None:
    """Reproduce shutdown while allowing already scheduled file reads to finish.

    Args:
        app: The headless observer whose presentation is being removed.
    """
    await app.query_one("#views").remove()


@pytest.fixture
def color_session(
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> Session:
    """Exercise status hues even when the test runner requests monochrome output.

    Args:
        monkeypatch: Restores the terminal environment after this test.
        request: Starts the ordinary isolated monitor after enabling color.

    Returns:
        A mounted monitor with its normal color rendering enabled.
    """
    monkeypatch.delenv("NO_COLOR", raising=False)
    return request.getfixturevalue("monitor_session")


@pytest_asyncio.fixture
async def scrolling_session(monitor_session: Session) -> Session:
    """Give every pane enough content to exercise its scrollbar at several positions.

    Args:
        monitor_session: The current test's isolated terminal session.

    Returns:
        A populated terminal whose panes all overflow vertically.
    """
    tests.helpers.factories.peri_scribe.monitor.events.write_log(
        monitor_session.directory,
        *(
            tests.helpers.factories.peri_scribe.monitor.events.record(
                "Starting command",
                command="run",
                run_id=str(number),
            )
            for number in range(50)
        ),
        *(
            tests.helpers.factories.peri_scribe.monitor.events.record(
                f"Event {number}",
                run_id="49",
            )
            for number in range(100)
        ),
    )
    content = "\n\n".join(f"Paragraph {number}" for number in range(100))
    monitor_session.app.report_path.write_text(content)
    await monitor_session.app.refresh_files()
    for selector in ("#details", "#decisions"):
        await tests.helpers.textual.invoke(
            monitor_session.app.query_one(selector, textual.widgets.Static).update,
            content,
        )
    return monitor_session


@pytest.fixture
def file_watching_session(
    request: pytest.FixtureRequest,
) -> tuple[
    collections.abc.Callable[
        [peri_scribe.monitor.app.MonitorApp],
        collections.abc.Coroutine[typing.Any, typing.Any, None],
    ],
    Session,
]:
    """Preserve the real notification consumer before isolating automatic file reads.

    Args:
        request: Starts the ordinary monitor after saving its notification consumer.

    Returns:
        The native-hint consumer and a controlled monitor session.
    """
    watcher = peri_scribe.monitor.app.watch_files
    return watcher, request.getfixturevalue("monitor_session")
