"""Run the real terminal adapter on each async test's isolated event loop."""

import asyncio
import collections.abc
import contextlib
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
import peri_scribe.monitor.session
import tests.helpers.doubles.peri_scribe.monitor.app
import tests.helpers.factories.peri_scribe.monitor.events
import tests.helpers.factories.peri_scribe.monitor.status
import tests.helpers.textual


@dataclasses.dataclass(frozen=True, kw_only=True)
class Session(tests.helpers.textual.Session[peri_scribe.monitor.app.MonitorApp]):
    """One event loop keeps terminal tasks alive between test actions."""

    directory: pathlib.Path
    clock: collections.abc.Callable[[], object]

    async def settle(self) -> None:
        """Wait for dispatched controls, content preparation, and the resulting paint.

        Tests keep inputs stable while this runs. Dispatching control messages first
        admits tab workers and filter preparation; joining both kinds of work keeps
        their final table replacement and cursor movement ahead of assertions.
        """
        await self.refresh()
        await self.app.workers.wait_for_complete()
        await self.app.controller.flush_display()
        await self.refresh()

    async def show_view(self, name: str) -> None:
        """Finish tab preparation and painting before browsing its rendered rows.

        Tab activation prepares content in background workers. Their final cursor
        movement can scroll a table, so assertions need both completed preparation and
        the resulting screen refresh.

        Args:
            name: The terminal tab to display.
        """
        self.app.action_view(name)
        await self.settle()


async def pause_clock(app: peri_scribe.monitor.app.MonitorApp) -> None:
    """Finish automatic age updates before a test controls presentation time.

    Freezing the observation clock leaves the asyncio timer running. Joining its
    cancellation prevents it from resetting explicitly displayed ages or preparing
    tables during the scenario.

    Args:
        app: A mounted monitor whose cosmetic clock has started.
    """
    cosmetic = app.controller.cosmetic_task
    assert cosmetic is not None
    cosmetic.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await cosmetic
    app.controller.cosmetic_task = None


@pytest_asyncio.fixture
async def monitor_session(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> typing.AsyncIterator[Session]:
    """Control observation, cosmetic timers, and terminal capabilities explicitly.

    Args:
        tmp_path: The current test's isolated filesystem.
        monkeypatch: Fixes color support and pauses automatic file reads.

    Yields:
        A headless terminal running on the current test's event loop.
    """
    monkeypatch.setattr(textual.constants, "COLOR_SYSTEM", "truecolor")
    monkeypatch.setattr(
        peri_scribe.monitor.session,
        "watch",
        unittest.mock.AsyncMock(),
    )
    monkeypatch.setattr(
        peri_scribe.monitor.session,
        "clock",
        unittest.mock.AsyncMock(),
    )
    directory = tmp_path / "2026"
    directory.mkdir()
    app = peri_scribe.monitor.app.MonitorApp(
        directory,
        directory / "report.md",
        tests.helpers.factories.peri_scribe.monitor.events.BRANCHES,
    )
    with time_machine.travel(
        tests.helpers.factories.peri_scribe.monitor.status.NOW,
        tick=False,
    ):
        async with tests.helpers.textual.mounted(app) as session:
            await pause_clock(app)
            monitor = Session(
                app=app,
                pilot=session.pilot,
                directory=directory,
                clock=app.controller.session.tick,
            )
            await monitor.show_view("pipeline")
            if app.controller.background is not None:
                await app.controller.background
            await monitor.settle()
            yield monitor


async def remove_views(app: peri_scribe.monitor.app.MonitorApp) -> None:
    """Reproduce shutdown while allowing already scheduled file reads to finish.

    Args:
        app: The headless observer whose presentation is being removed.
    """
    await app.query_one("#views").remove()


@pytest.fixture
def evidence_completed(
    monitor_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> asyncio.Event:
    """Observe one completed evidence command after its control message bubbles.

    Input delivery may finish before the status control's message reaches the app.
    The controller's return joins the requested read and evidence presentation.

    Args:
        monitor_session: The mounted monitor whose evidence command is observed.
        monkeypatch: Restore the command after the current test.

    Returns:
        A signal set only after successful evidence navigation finishes.
    """
    completed = asyncio.Event()
    controller = monitor_session.app.controller
    monkeypatch.setattr(
        controller,
        "open_evidence",
        functools.partial(
            tests.helpers.doubles.peri_scribe.monitor.app.open_evidence_with_completion,
            completed,
            controller.open_evidence,
        ),
    )
    return completed


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
        [peri_scribe.monitor.session.MonitorSession],
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
    watcher = peri_scribe.monitor.session.watch
    return watcher, request.getfixturevalue("monitor_session")
