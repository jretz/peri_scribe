"""Run the real terminal adapter in an isolated, synchronous test harness."""

import asyncio
import collections.abc
import contextlib
import dataclasses
import functools
import pathlib
import typing
import unittest.mock

import pytest
import textual.constants
import textual.pilot
import textual.widget
import textual.widgets
import time_machine

import peri_scribe.monitor.app
import tests.helpers.factories.peri_scribe.monitor.events
import tests.helpers.factories.peri_scribe.monitor.status


@dataclasses.dataclass(frozen=True, kw_only=True)
class Session:
    """One event loop keeps terminal tasks alive between test actions."""

    app: peri_scribe.monitor.app.MonitorApp
    runner: asyncio.Runner
    pilot: textual.pilot.Pilot[None]
    directory: pathlib.Path
    clock: collections.abc.Callable[[], object]

    def call[Result](
        self,
        callback: collections.abc.Callable[..., Result],
        *args: object,
    ) -> Result:
        """Keep synchronous widget actions inside Textual's running event loop.

        Args:
            callback: The user action or widget mutation.
            args: Positional arguments for that action.

        Returns:
            The action's result after dispatch within the terminal event loop.
        """
        return self.runner.run(invoke(callback, *args))

    def drag(self, divider: textual.widget.Widget, movement: tuple[int, int]) -> None:
        """Exercise pointer capture by dragging outside the divider's original bounds.

        Args:
            divider: The visible divider to move.
            movement: Horizontal and vertical pointer movement in terminal cells.
        """
        position = divider.region.offset
        destination = (position.x + movement[0], position.y + movement[1])
        self.runner.run(self.pilot.mouse_down(divider))
        self.runner.run(self.pilot.hover(offset=destination))
        self.runner.run(self.pilot.mouse_up(offset=destination))


async def invoke[Result](
    callback: collections.abc.Callable[..., Result],
    *args: object,
) -> Result:
    """Allow synchronous UI actions to schedule terminal messages and timers.

    Args:
        callback: The action that requires a running event loop.
        args: Positional arguments for that action.

    Returns:
        The result of the requested action.
    """
    result = callback(*args)
    await asyncio.sleep(0)
    return result


@pytest.fixture
def monitor_session(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> typing.Iterator[Session]:
    """Control file refreshes and terminal capabilities independently of the host.

    Args:
        tmp_path: The current test's isolated filesystem.
        monkeypatch: Fixes color support and pauses automatic file reads.

    Yields:
        A headless terminal and its explicit event-loop runner.
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
    with (
        time_machine.travel(
            tests.helpers.factories.peri_scribe.monitor.status.NOW,
            tick=False,
        ),
        asyncio.Runner() as runner,
    ):
        stack = contextlib.AsyncExitStack()
        pilot = runner.run(stack.enter_async_context(app.run_test(size=(120, 42))))
        try:
            runner.run(pilot.press("2"))
            yield Session(
                app=app,
                runner=runner,
                pilot=pilot,
                directory=directory,
                clock=interval.call_args.args[1],
            )
        finally:
            runner.run(stack.aclose())


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


@pytest.fixture
def scrolling_session(monitor_session: Session) -> Session:
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
    monitor_session.runner.run(monitor_session.app.refresh_files())
    for selector in ("#details", "#decisions"):
        monitor_session.call(
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
