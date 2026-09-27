"""Expose the monitor owner's publication and resource lifetime at real await points."""

from __future__ import annotations

import asyncio
import collections.abc
import compression.zstd
import dataclasses
import fcntl
import functools
import json
import pathlib
import threading
import typing

import peri_scribe.monitor.app
import peri_scribe.monitor.model
import peri_scribe.monitor.tasks
import tests.helpers.doubles.concurrency
import tests.helpers.doubles.peri_scribe.monitor.app
import tests.helpers.factories.peri_scribe.monitor.events


if typing.TYPE_CHECKING:
    import pytest


type Observation = tuple[bool, bool, tuple[int, ...], tuple[int, ...]]


@dataclasses.dataclass(kw_only=True)
class Scenario:
    """Retain a complete execution while real threads wait independently of tasks."""

    owner: peri_scribe.monitor.tasks.Owner = dataclasses.field(
        default_factory=peri_scribe.monitor.tasks.Owner,
    )
    worker: tests.helpers.doubles.concurrency.BlockedOperation = dataclasses.field(
        default_factory=tests.helpers.doubles.concurrency.BlockedOperation,
    )
    active: set[int] = dataclasses.field(default_factory=set)
    published: set[int] = dataclasses.field(default_factory=set)
    observations: list[Observation] = dataclasses.field(default_factory=list)
    retired: bool = False
    releases: int = 0

    def remember(self) -> None:
        """Observe ownership and visible effects without inferring model transitions."""
        self.observations.append(
            (
                self.owner.stopped.is_set(),
                self.retired,
                tuple(sorted(self.active)),
                tuple(sorted(self.published)),
            ),
        )

    async def operation(self, identifier: int, *, fails: bool = False) -> None:
        """Take a snapshot before a blocking operation and publish only while mounted.

        Args:
            identifier: Distinct evidence contributed by this operation.
            fails: Whether the first admitted worker raises after being released.
        """
        self.active.add(identifier)
        self.remember()
        snapshot = self.published.copy()
        try:
            await asyncio.to_thread(functools.partial(self.worker.run, fail=fails))
            if not self.owner.stopped.is_set():
                self.published = snapshot | {identifier}
                self.remember()
        finally:
            self.active.remove(identifier)
            self.remember()

    def release(self) -> None:
        """Descriptor retirement is observable separately from operation completion."""
        self.remember()
        self.releases += 1
        self.retired = True
        self.remember()

    async def stop(self) -> None:
        """Record the synchronous admission barrier before awaiting actual shutdown."""
        closing = asyncio.create_task(self.owner.close(self.release))
        await self.owner.stopped.wait()
        self.remember()
        await closing


async def cancelled(task: asyncio.Task[None], repetitions: int) -> None:
    """Allow cancellation delivery without letting the controlled worker finish.

    Args:
        task: The admitted owner or shutdown task whose resources must remain live.
        repetitions: Independent cancellation deliveries before worker completion.
    """
    for _ in range(repetitions):
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()


@dataclasses.dataclass(kw_only=True)
class Application:
    """Record real app state and operation lifetimes without replacing their effects."""

    app: peri_scribe.monitor.app.MonitorApp
    active: set[int] = dataclasses.field(default_factory=set)
    observations: list[Observation] = dataclasses.field(default_factory=list)
    retired: bool = False

    def remember(self) -> None:
        """Project actual visible evidence and resource lifetimes onto TLC variables."""
        identifiers = {"archive": 1, "new": 2}
        self.observations.append(
            (
                self.app.operations.stopped.is_set(),
                self.retired,
                tuple(sorted(self.active)),
                tuple(
                    sorted(
                        identifiers[run.identifier]
                        for run in self.app.state.runs
                        if run.identifier in identifiers
                    ),
                ),
            ),
        )

    async def observe(
        self,
        identifier: int,
        function: collections.abc.Callable[
            [peri_scribe.monitor.app.MonitorApp],
            collections.abc.Coroutine[typing.Any, typing.Any, None],
        ],
        app: peri_scribe.monitor.app.MonitorApp,
    ) -> None:
        """Observe the production operation before and after its ordinary effects.

        Args:
            identifier: The operation's checked evidence identity.
            function: Unmodified production operation.
            app: The observer invoking that operation through its public API.
        """
        self.active.add(identifier)
        self.remember()
        try:
            await function(app)
        finally:
            self.remember()
            self.active.remove(identifier)
            self.remember()

    def close(
        self,
        function: collections.abc.Callable[[peri_scribe.monitor.app.MonitorApp], None],
        app: peri_scribe.monitor.app.MonitorApp,
    ) -> None:
        """Record descriptor retirement after the real app releases both readers.

        Args:
            function: Unmodified production descriptor cleanup.
            app: The observer whose readers are being retired.
        """
        self.remember()
        function(app)
        self.retired = True
        self.remember()


def archive(directory: pathlib.Path) -> pathlib.Path:
    """Provide one actual compressed historical event for concurrent ingestion.

    Args:
        directory: The application's isolated year directory.

    Returns:
        The previous month's archive.
    """
    path = directory / "logs" / "2026-08.jsonl.zst"
    path.parent.mkdir(exist_ok=True)
    with compression.zstd.open(path, "wt") as stream:
        stream.write(
            json.dumps(
                tests.helpers.factories.peri_scribe.monitor.events.record(
                    "Starting command",
                    command="run",
                    run_id="archive",
                ),
            )
            + "\n",
        )
    return path


async def application_replay(
    app: peri_scribe.monitor.app.MonitorApp,
    monkeypatch: pytest.MonkeyPatch,
    *,
    stop: bool,
    cancel: bool,
) -> list[Observation]:
    """Compete actual archive and live refresh APIs while their threads are suspended.

    Args:
        app: A mounted headless monitor with automatic refresh paused.
        monkeypatch: Restores the boundary observers and controlled worker gate.
        stop: Whether unmount begins while the archive append is suspended.
        cancel: Whether the archive caller cancels after admission.

    Returns:
        The actual state-publication and descriptor-retirement execution.
    """
    scenario = Application(app=app)
    scenario.remember()
    for identifier, name in ((1, "load_older_owned"), (2, "refresh_owned")):
        monkeypatch.setattr(
            peri_scribe.monitor.app,
            name,
            functools.partial(
                scenario.observe,
                identifier,
                getattr(peri_scribe.monitor.app, name),
            ),
        )
    monkeypatch.setattr(
        peri_scribe.monitor.app,
        "close_readers",
        functools.partial(scenario.close, peri_scribe.monitor.app.close_readers),
    )
    app.archives = (archive(app.year_directory),)
    started, release = threading.Event(), threading.Event()
    monkeypatch.setattr(
        peri_scribe.monitor.model,
        "append_records",
        tests.helpers.doubles.peri_scribe.monitor.app.BlockedArchiveAppend(
            started=started,
            release=release,
            append=peri_scribe.monitor.model.append_records,
        ),
    )
    loading = asyncio.create_task(app.load_older())
    closing = None
    try:
        assert await asyncio.to_thread(started.wait, 5)
        tests.helpers.factories.peri_scribe.monitor.events.write_log(
            app.year_directory,
            tests.helpers.factories.peri_scribe.monitor.events.record(
                "Starting command",
                command="run",
                run_id="new",
            ),
        )
        refresh = asyncio.create_task(app.refresh_files())
        await asyncio.sleep(0)
        if cancel:
            await cancelled(loading, 2)
        if stop:
            closing = asyncio.create_task(app.on_unmount())
            await app.operations.stopped.wait()
            scenario.remember()
            assert not scenario.retired
        assert scenario.active == {1}
    finally:
        release.set()
    outcomes = await asyncio.gather(loading, refresh, return_exceptions=True)
    assert outcomes[1] is None
    if cancel:
        assert isinstance(outcomes[0], asyncio.CancelledError)
    else:
        assert outcomes[0] is None
    if closing is not None:
        await closing
    else:
        closing = asyncio.create_task(app.on_unmount())
        await app.operations.stopped.wait()
        scenario.remember()
        await closing
    return scenario.observations


@dataclasses.dataclass(frozen=True, kw_only=True)
class PausedCall[Result]:
    """Hold actual file operations at an observable point before they return."""

    function: collections.abc.Callable[..., Result]
    started: threading.Event = dataclasses.field(default_factory=threading.Event)
    release: threading.Event = dataclasses.field(default_factory=threading.Event)
    finished: threading.Event = dataclasses.field(default_factory=threading.Event)

    def __call__(self, *args: object, **kwargs: object) -> Result:
        """Keep a worker visible independently of its coordinating task.

        Args:
            args: Positional arguments forwarded to the actual file operation.
            kwargs: Named arguments forwarded to the actual file operation.

        Returns:
            The unmodified operation's result.
        """
        self.started.set()
        try:
            assert self.release.wait(5), "test did not release file operation"
            return self.function(*args, **kwargs)
        finally:
            self.finished.set()


@dataclasses.dataclass(frozen=True, kw_only=True)
class PausedUpdate:
    """Let unmount begin while an already-admitted Markdown update is awaiting work."""

    function: collections.abc.Callable[[str], collections.abc.Awaitable[None]]
    started: asyncio.Event = dataclasses.field(default_factory=asyncio.Event)
    release: asyncio.Event = dataclasses.field(default_factory=asyncio.Event)

    async def __call__(self, content: str) -> None:
        """Finish admitted rendering only when its resource owner permits completion.

        Args:
            content: The new document already accepted by the presentation.
        """
        self.started.set()
        await self.release.wait()
        await self.function(content)


async def shared_lock_replay(
    app: peri_scribe.monitor.app.MonitorApp,
    monkeypatch: pytest.MonkeyPatch,
) -> list[Observation]:
    """Unmount and repeatedly cancel while a real shared flock waits for a writer.

    Args:
        app: A mounted monitor whose periodic refreshes are paused.
        monkeypatch: Restores entry/exit observers after descriptor retirement.

    Returns:
        The actual owned lock-wait and shutdown execution for TLC comparison.
    """
    tests.helpers.factories.peri_scribe.monitor.events.write_log(
        app.year_directory,
        tests.helpers.factories.peri_scribe.monitor.events.record(
            "Starting command",
            command="run",
            run_id="initial",
        ),
    )
    await app.refresh_files()
    streams = [cursor.stream for cursor in app.follower.cursors.values()]
    previous = app.state
    scenario = Application(app=app)
    scenario.remember()
    monkeypatch.setattr(
        peri_scribe.monitor.app,
        "refresh_owned",
        functools.partial(scenario.observe, 1, peri_scribe.monitor.app.refresh_owned),
    )
    monkeypatch.setattr(
        peri_scribe.monitor.app,
        "close_readers",
        functools.partial(scenario.close, peri_scribe.monitor.app.close_readers),
    )
    reading = PausedCall(function=app.follower.poll)
    reading.release.set()
    monkeypatch.setattr(app.follower, "poll", reading)
    lock_path = app.year_directory / "logs" / ".rotation.lock"
    with await asyncio.to_thread(lock_path.open, "ab") as writer:
        fcntl.flock(writer, fcntl.LOCK_EX)
        active = asyncio.create_task(app.refresh_files())
        try:
            assert await asyncio.to_thread(reading.started.wait, 5)
            closing = asyncio.create_task(app.on_unmount())
            await app.operations.stopped.wait()
            scenario.remember()
            await cancelled(active, 2)
            await cancelled(closing, 2)
            assert not reading.finished.is_set()
            assert not scenario.retired
            assert streams
            assert not any(stream.closed for stream in streams)
        finally:
            fcntl.flock(writer, fcntl.LOCK_UN)
        outcomes = await asyncio.gather(active, closing, return_exceptions=True)
    assert all(isinstance(outcome, asyncio.CancelledError) for outcome in outcomes)
    assert reading.finished.is_set()
    assert all(stream.closed for stream in streams)
    assert app.state is previous
    assert scenario.retired
    return scenario.observations
