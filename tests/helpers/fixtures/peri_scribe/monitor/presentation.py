"""Record actual presentation payloads while real domain owners run."""

import asyncio
import collections.abc
import contextlib
import dataclasses
import pathlib
import typing
import unittest.mock

import pytest
import pytest_asyncio
import time_machine

import peri_scribe.monitor.app
import peri_scribe.monitor.display
import peri_scribe.monitor.health_presentation
import peri_scribe.monitor.model
import peri_scribe.monitor.session
import peri_scribe.monitor.status
import peri_scribe.monitor.storage
import peri_scribe.monitor.terminal_contract
import peri_scribe.monitor.terminal_presentation
import tests.helpers.factories.peri_scribe.monitor.events
import tests.helpers.factories.peri_scribe.monitor.status
import tests.helpers.fixtures.peri_scribe.monitor.application


type Host = peri_scribe.monitor.terminal_contract.Host


@dataclasses.dataclass(kw_only=True)
class Recording(peri_scribe.monitor.terminal_presentation.Presentation):
    """Keep private attachment state and immutable actual output history."""

    attached: bool = True
    health_views: tuple[peri_scribe.monitor.health_presentation.View, ...] = ()
    prepared: tuple[peri_scribe.monitor.display.Records, ...] = ()
    generations: tuple[int, ...] = ()
    reports: tuple[peri_scribe.monitor.storage.Report, ...] = ()
    callbacks: tuple[collections.abc.Callable[[], None], ...] = ()
    queries: tuple[str, str] = ("", "")
    archive_enabled: tuple[bool, ...] = ()
    errors_seen: tuple[tuple[str, ...], ...] = ()
    activity_versions: tuple[tuple[int, int, str, bool], ...] = ()

    @typing.override
    def available(self, app: Host) -> bool:
        """Return the explicitly controlled component attachment state."""
        return self.attached

    @typing.override
    def after_refresh(
        self,
        app: Host,
        callback: collections.abc.Callable[[], None],
    ) -> None:
        """Retain the actual callback for separately owned frame-admission checks."""
        self.callbacks += (callback,)

    @typing.override
    def older_enabled(self, app: Host, *, enabled: bool) -> None:
        """Record the actual archive-control decision."""
        self.archive_enabled += (enabled,)

    @typing.override
    def health(
        self,
        app: Host,
        view: peri_scribe.monitor.health_presentation.View,
    ) -> None:
        """Retain the actual immutable health value passed by the controller."""
        self.health_views += (view,)

    @typing.override
    def activity(self, app: Host) -> None:
        """Record current domain and inspection identities together."""
        self.activity_versions += (
            (
                app.controller.snapshot.records.sequence,
                app.visible_state.sequence,
                app.selected_run,
                app.following,
            ),
        )

    @typing.override
    def errors(self, app: Host, errors: tuple[str, ...]) -> None:
        """Retain actual domain errors in their original order."""
        self.errors_seen += (errors,)

    @typing.override
    def filters(self, app: Host) -> peri_scribe.monitor.terminal_presentation.Filters:
        """Return the explicit component controls in native pipeline/log order."""
        return (
            peri_scribe.monitor.display.Filter(
                minimum_level="info",
                query=self.queries[0],
                path=app.selected_phase,
            ),
            peri_scribe.monitor.display.Filter(
                minimum_level="info",
                query=self.queries[1],
                path=(),
            ),
        )

    @typing.override
    async def records(
        self,
        app: Host,
        prepared: peri_scribe.monitor.display.Records,
        generation: int,
    ) -> None:
        """Retain actual prepared values and their authorization generation."""
        self.prepared += (prepared,)
        self.generations += (generation,)

    @typing.override
    def has_report(self, app: Host) -> bool:
        """Return the explicitly controlled report attachment state."""
        return self.attached

    @typing.override
    async def report(
        self,
        app: Host,
        report: peri_scribe.monitor.storage.Report,
    ) -> None:
        """Complete the abstract report effect only while its value remains current."""
        self.reports += (report,)
        if app.controller.available() and report == app.controller.snapshot.report:
            app.rendered_report = report

    @typing.override
    async def evidence(
        self,
        app: Host,
        run: peri_scribe.monitor.model.Run,
        target: peri_scribe.monitor.status.Target,
    ) -> None:
        """Reject native evidence navigation outside its mounted owner.

        Raises:
            AssertionError: This component does not own native evidence navigation.
        """
        message = "Native evidence navigation belongs to its mounted tests"
        raise AssertionError(message)

    @typing.override
    def cursor(self, app: Host, name: str) -> None:
        """Reject native cursor adjustment outside its mounted owner.

        Raises:
            AssertionError: This component does not own native cursor adjustment.
        """
        message = "Native cursor application belongs to its mounted tests"
        raise AssertionError(message)


@dataclasses.dataclass(frozen=True, kw_only=True)
class Session:
    """Keep a real application and private recording port on one isolated event loop."""

    app: peri_scribe.monitor.app.MonitorApp
    presentation: Recording
    directory: pathlib.Path
    begin_background: collections.abc.Callable[[], None]

    async def refresh(self) -> None:
        """Join the real controller preparation before inspecting its output."""
        await self.app.controller.flush_display()
        await asyncio.sleep(0)


@contextlib.asynccontextmanager
async def owned_component(
    directory: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    background: bool,
) -> typing.AsyncGenerator[Session]:
    """Run a real application controller and close its actual domain owners.

    Yields:
        A private component session carrying actual immutable output values.
    """
    monkeypatch.setattr(peri_scribe.monitor.session, "watch", unittest.mock.AsyncMock())
    monkeypatch.setattr(peri_scribe.monitor.session, "clock", unittest.mock.AsyncMock())
    presentation = Recording()
    app = peri_scribe.monitor.app.MonitorApp(
        directory,
        directory / "report.md",
        tests.helpers.factories.peri_scribe.monitor.events.BRANCHES,
        presentation=presentation,
    )
    with time_machine.travel(
        tests.helpers.factories.peri_scribe.monitor.status.NOW,
        tick=False,
    ):
        try:
            await app.controller.start()
            await tests.helpers.fixtures.peri_scribe.monitor.application.pause_clock(
                app,
            )
            if background:
                app.controller.begin_background()
                assert app.controller.background is not None
                await app.controller.background
            yield Session(
                app=app,
                presentation=presentation,
                directory=directory,
                begin_background=app.controller.begin_background,
            )
        finally:
            await app.on_unmount()


@pytest_asyncio.fixture
async def component_monitor(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> typing.AsyncIterator[Session]:
    """Initialize the empty-year component after normal background preparation.

    Yields:
        The current test's actual application, controller and domain session.
    """
    directory = tmp_path / "2026"
    directory.mkdir()
    async with owned_component(directory, monkeypatch, background=True) as session:
        yield session


@pytest_asyncio.fixture
async def component_initial_monitor(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> typing.AsyncIterator[Session]:
    """Keep the actual initial health ready while frame admission is held.

    Yields:
        The original three-record and report inputs before background content.
    """
    directory = tmp_path / "2026"
    directory.mkdir()
    tests.helpers.factories.peri_scribe.monitor.events.write_log(
        directory,
        tests.helpers.factories.peri_scribe.monitor.events.record(
            "Starting command",
            command="run",
        ),
        tests.helpers.factories.peri_scribe.monitor.events.record("Alpha event"),
        tests.helpers.factories.peri_scribe.monitor.events.record("Beta event"),
    )
    (directory / "report.md").write_text("# The complete report\n")
    async with owned_component(directory, monkeypatch, background=False) as session:
        yield session


@pytest.fixture
def component_file_watching_session(
    request: pytest.FixtureRequest,
) -> tuple[
    collections.abc.Callable[
        [peri_scribe.monitor.session.MonitorSession],
        collections.abc.Coroutine[typing.Any, typing.Any, None],
    ],
    Session,
]:
    """Save the actual watcher before component observation is isolated.

    Returns:
        The native watcher and current component session.
    """
    watcher = peri_scribe.monitor.session.watch
    return watcher, request.getfixturevalue("component_monitor")
