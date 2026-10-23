"""Expose request ownership boundaries without relying on wall-clock delays."""

import asyncio
import collections.abc
import contextlib
import dataclasses
import pathlib
import typing

import peri_scribe.concurrency
import peri_scribe.monitor.session
import tests.helpers.doubles.peri_scribe.monitor.synchronization


@dataclasses.dataclass(frozen=True, kw_only=True)
class Gate:
    """Hold one admitted request while peers, cancellation, or cleanup compete."""

    started: asyncio.Event = dataclasses.field(default_factory=asyncio.Event)
    released: asyncio.Event = dataclasses.field(default_factory=asyncio.Event)
    requests: list[str] = dataclasses.field(default_factory=list)
    failures: frozenset[str] = frozenset()
    tasks: list[asyncio.Task[object]] = dataclasses.field(default_factory=list)

    def start[Result](
        self,
        operation: collections.abc.Coroutine[typing.Any, typing.Any, Result],
    ) -> asyncio.Task[Result]:
        """Retain a caller so assertion failure can still join its admitted work.

        Args:
            operation: The request or shutdown call controlled by this scenario.

        Returns:
            The scheduled caller, whose result the scenario must check explicitly.
        """
        task = asyncio.create_task(operation)
        self.tasks.append(task)
        return task

    @contextlib.asynccontextmanager
    async def running(
        self,
        session: peri_scribe.monitor.session.MonitorSession,
    ) -> collections.abc.AsyncGenerator[None]:
        """Release blocked work and retire its session if an assertion fails.

        Successful scenarios await each caller and check its outcome themselves.
        Failure cleanup joins those callers before monkeypatches can be restored,
        while preserving the assertion that interrupted the scenario.

        Args:
            session: The domain owner whose requests use this gate.

        Yields:
            Control while the scenario admits and checks requests.
        """
        try:
            yield
        except BaseException as failure:
            self.released.set()
            cleanup = asyncio.create_task(self.finish(session))
            await peri_scribe.concurrency.finish_worker(cleanup)
            try:
                cleanup.result()
            except BaseException as cleanup_failure:
                raise failure from cleanup_failure
            raise
        else:
            self.released.set()
            await session.close()

    async def finish(
        self,
        session: peri_scribe.monitor.session.MonitorSession,
    ) -> None:
        """Keep failed-scenario joins and resource retirement in one owned task.

        Args:
            session: The owner whose gate has already been released.
        """
        await asyncio.gather(*self.tasks, return_exceptions=True)
        await session.close()

    async def execute(
        self,
        session: peri_scribe.monitor.session.MonitorSession,
        request: peri_scribe.monitor.session.Request,
    ) -> peri_scribe.monitor.session.Snapshot:
        """Keep admission and publication observable through the real scheduler.

        Args:
            session: The real resource and publication owner.
            request: A command-evidence request with a recognizable identifier.

        Returns:
            A committed snapshot carrying the request identifier.

        Raises:
            RuntimeError: For identifiers selected by the failure scenario.
        """
        assert isinstance(request, peri_scribe.monitor.session.LoadRun)
        self.requests.append(request.identifier)
        self.started.set()
        await self.released.wait()
        if request.identifier in self.failures:
            message = "request failed"
            raise RuntimeError(message)
        return peri_scribe.monitor.session.publish(
            session,
            dataclasses.replace(session.snapshot, errors=(request.identifier,)),
        )


async def queued(
    session: peri_scribe.monitor.session.MonitorSession,
    count: int,
) -> None:
    """Let already scheduled submitters enqueue before the active request is released.

    Args:
        session: The request queue under test.
        count: The number of pending requests required by the scenario.
    """
    await asyncio.sleep(0)
    assert len(session.pending) == count


async def hints(
    session: peri_scribe.monitor.session.MonitorSession,
) -> None:
    """Exercise the native-hint boundary without starting an operating-system watcher.

    Args:
        session: The session whose observation lifetime is tested.
    """
    session.files_changed = True
    await session.watching_stopped.wait()


async def changes(
    directory: pathlib.Path,
    stopped: asyncio.Event,
) -> collections.abc.AsyncIterator[None]:
    """Deliver one native change hint without observing the host filesystem.

    Args:
        directory: The isolated directory whose observer is exercised.
        stopped: The session's cooperative observer shutdown event.

    Yields:
        One reconciliation hint.
    """
    assert await asyncio.to_thread(directory.is_dir)
    assert not stopped.is_set()
    yield None


async def fail_after_admission(
    gate: Gate,
    session: peri_scribe.monitor.session.MonitorSession,
    failure: AssertionError,
    *,
    cancel_cleanup: bool = False,
) -> None:
    """Interrupt a scenario while its real request waits for explicit release.

    Args:
        gate: The test owner responsible for releasing and joining its callers.
        session: The actual scheduler retaining the admitted request.
        failure: The assertion that cleanup must preserve.
        cancel_cleanup: Whether cancellation competes with the failed scenario's join.
    """
    async with gate.running(session):
        gate.start(
            session.request(peri_scribe.monitor.session.LoadRun(identifier="active")),
        )
        await gate.started.wait()
        if cancel_cleanup:
            tests.helpers.doubles.peri_scribe.monitor.synchronization.interrupt_cleanup(
                failure,
            )
        raise failure
