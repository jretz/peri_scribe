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
import peri_scribe.monitor.session
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


async def cancelled[Result](task: asyncio.Task[Result], repetitions: int) -> None:
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
class Session:
    """Observe session evidence and descriptor ownership at operation boundaries."""

    session: peri_scribe.monitor.session.MonitorSession
    active: set[int] = dataclasses.field(default_factory=set)
    observations: list[Observation] = dataclasses.field(default_factory=list)
    retired: bool = False

    def remember(self) -> None:
        """Project committed evidence and resource lifetime onto TLC variables."""
        identifiers = {"archive": 1, "new": 2}
        self.observations.append(
            (
                self.session.owner.stopped.is_set(),
                self.retired,
                tuple(sorted(self.active)),
                tuple(
                    sorted(
                        identifiers[run.identifier]
                        for run in self.session.snapshot.records.runs
                        if run.identifier in identifiers
                    ),
                ),
            ),
        )

    async def observe(
        self,
        function: collections.abc.Callable[
            [
                peri_scribe.monitor.session.MonitorSession,
                peri_scribe.monitor.session.Request,
            ],
            collections.abc.Coroutine[
                typing.Any,
                typing.Any,
                peri_scribe.monitor.session.Snapshot,
            ],
        ],
        session: peri_scribe.monitor.session.MonitorSession,
        request: peri_scribe.monitor.session.Request,
    ) -> peri_scribe.monitor.session.Snapshot:
        """Retain every admission, publication, and retirement in one execution.

        Args:
            function: Unmodified production request execution.
            session: The domain owner admitting the request.
            request: The request whose contribution is recorded.

        Returns:
            The unmodified request result.
        """
        identifier = (
            1 if isinstance(request, peri_scribe.monitor.session.LoadOlder) else 2
        )
        self.active.add(identifier)
        self.remember()
        try:
            return await function(session, request)
        finally:
            self.remember()
            self.active.remove(identifier)
            self.remember()

    def close(
        self,
        function: collections.abc.Callable[
            [peri_scribe.monitor.session.MonitorSession],
            None,
        ],
        session: peri_scribe.monitor.session.MonitorSession,
    ) -> None:
        """Record descriptor retirement only after both actual readers close.

        Args:
            function: Unmodified production descriptor cleanup.
            session: The observer whose resources are being retired.
        """
        self.remember()
        function(session)
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
    """Exercise the same owned domain operations beneath a mounted terminal.

    Args:
        app: The mounted consumer whose domain session is exercised.
        monkeypatch: Restores boundary observers after the scenario.
        stop: Whether shutdown begins while archive ingestion is suspended.
        cancel: Whether the archive requester cancels after admission.

    Returns:
        The domain publication and descriptor-retirement execution.
    """
    return await session_replay(
        app.controller.session,
        monkeypatch,
        stop=stop,
        cancel=cancel,
    )


async def session_replay(
    session: peri_scribe.monitor.session.MonitorSession,
    monkeypatch: pytest.MonkeyPatch,
    *,
    stop: bool,
    cancel: bool,
) -> list[Observation]:
    """Compete archive and live requests while their actual workers are suspended.

    Args:
        session: An isolated session with automatic observation disabled.
        monkeypatch: Restores boundary observers and the controlled worker gate.
        stop: Whether shutdown begins while archive ingestion is suspended.
        cancel: Whether the archive requester cancels after admission.

    Returns:
        The actual publication and descriptor-retirement execution.
    """
    scenario = Session(session=session)
    scenario.remember()
    monkeypatch.setattr(
        peri_scribe.monitor.session,
        "execute",
        functools.partial(scenario.observe, peri_scribe.monitor.session.execute),
    )
    monkeypatch.setattr(
        peri_scribe.monitor.session,
        "release",
        functools.partial(scenario.close, peri_scribe.monitor.session.release),
    )
    session.snapshot = dataclasses.replace(
        session.snapshot,
        archives=(archive(session.year_directory),),
    )
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
    loading = asyncio.create_task(
        session.request(peri_scribe.monitor.session.LoadOlder()),
    )
    closing = None
    try:
        assert await asyncio.to_thread(started.wait, 5)
        tests.helpers.factories.peri_scribe.monitor.events.write_log(
            session.year_directory,
            tests.helpers.factories.peri_scribe.monitor.events.record(
                "Starting command",
                command="run",
                run_id="new",
            ),
        )
        refresh = asyncio.create_task(
            session.request(peri_scribe.monitor.session.RefreshRecords()),
        )
        await asyncio.sleep(0)
        if cancel:
            await cancelled(loading, 2)
        if stop:
            closing = asyncio.create_task(session.close())
            await session.owner.stopped.wait()
            scenario.remember()
            assert not scenario.retired
        assert scenario.active == {1}
    finally:
        release.set()
    outcomes = await asyncio.gather(loading, refresh, return_exceptions=True)
    assert isinstance(outcomes[1], peri_scribe.monitor.session.Snapshot)
    if cancel:
        assert isinstance(outcomes[0], asyncio.CancelledError)
    else:
        assert isinstance(outcomes[0], peri_scribe.monitor.session.Snapshot)
    if closing is not None:
        await closing
    else:
        closing = asyncio.create_task(session.close())
        await session.owner.stopped.wait()
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
    """Keep the mounted consumer's readers alive while a real writer holds its lock.

    Args:
        app: A mounted monitor with automatic observation paused.
        monkeypatch: Restores the request and descriptor boundary observers.

    Returns:
        The actual owned lock-wait and shutdown execution.
    """
    return await session_lock_replay(app.controller.session, monkeypatch)


async def session_lock_replay(
    session: peri_scribe.monitor.session.MonitorSession,
    monkeypatch: pytest.MonkeyPatch,
) -> list[Observation]:
    """Repeatedly cancel reads and shutdown while a shared flock waits for a writer.

    Args:
        session: An isolated domain observer without automatic reconciliation.
        monkeypatch: Restores request and descriptor boundary observers.

    Returns:
        The actual resource-lifetime execution for comparison with TLC.
    """
    tests.helpers.factories.peri_scribe.monitor.events.write_log(
        session.year_directory,
        tests.helpers.factories.peri_scribe.monitor.events.record(
            "Starting command",
            command="run",
            run_id="initial",
        ),
    )
    await session.request(peri_scribe.monitor.session.RefreshRecords())
    streams = [cursor.stream for cursor in session.follower.cursors.values()]
    previous = session.snapshot
    scenario = Session(session=session)
    scenario.remember()
    monkeypatch.setattr(
        peri_scribe.monitor.session,
        "execute",
        functools.partial(scenario.observe, peri_scribe.monitor.session.execute),
    )
    monkeypatch.setattr(
        peri_scribe.monitor.session,
        "release",
        functools.partial(scenario.close, peri_scribe.monitor.session.release),
    )
    reading = PausedCall(function=session.follower.poll)
    reading.release.set()
    monkeypatch.setattr(session.follower, "poll", reading)
    lock_path = session.year_directory / "logs" / ".rotation.lock"
    with await asyncio.to_thread(lock_path.open, "ab") as writer:
        fcntl.flock(writer, fcntl.LOCK_EX)
        active = asyncio.create_task(
            session.request(peri_scribe.monitor.session.RefreshRecords()),
        )
        try:
            assert await asyncio.to_thread(reading.started.wait, 5)
            closing = asyncio.create_task(session.close())
            await session.owner.stopped.wait()
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
    assert session.snapshot is previous
    assert scenario.retired
    return scenario.observations
