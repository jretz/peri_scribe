"""Expose request ownership boundaries without relying on wall-clock delays."""

import asyncio
import collections.abc
import dataclasses
import pathlib

import peri_scribe.monitor.session


@dataclasses.dataclass(frozen=True, kw_only=True)
class Gate:
    """Hold one admitted request while peers, cancellation, or cleanup compete."""

    started: asyncio.Event = dataclasses.field(default_factory=asyncio.Event)
    released: asyncio.Event = dataclasses.field(default_factory=asyncio.Event)
    requests: list[str] = dataclasses.field(default_factory=list)
    failures: frozenset[str] = frozenset()

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
