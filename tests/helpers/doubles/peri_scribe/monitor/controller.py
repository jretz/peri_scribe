"""Suspend content admission while retaining the real reader and publication path."""

import asyncio
import collections.abc
import dataclasses
import typing


if typing.TYPE_CHECKING:
    import peri_scribe.monitor.app as monitor_application
    import peri_scribe.monitor.controller as monitor_controller
    import peri_scribe.monitor.display
    import peri_scribe.monitor.session


@dataclasses.dataclass(frozen=True, kw_only=True)
class ContentGate:
    """Make overlapping navigation observable without depending on read latency."""

    operation: collections.abc.Callable[
        [
            peri_scribe.monitor.session.MonitorSession,
            peri_scribe.monitor.session.Request,
        ],
        collections.abc.Coroutine[
            typing.Any,
            typing.Any,
            peri_scribe.monitor.session.Snapshot,
        ],
    ]
    kind: type[peri_scribe.monitor.session.Request]
    started: asyncio.Event = dataclasses.field(default_factory=asyncio.Event)
    released: asyncio.Event = dataclasses.field(default_factory=asyncio.Event)
    requests: list[peri_scribe.monitor.session.Request] = dataclasses.field(
        default_factory=list,
    )

    async def execute(
        self,
        session: peri_scribe.monitor.session.MonitorSession,
        request: peri_scribe.monitor.session.Request,
    ) -> peri_scribe.monitor.session.Snapshot:
        """Pause one kind of work after admission while other callers may join it.

        Args:
            session: The actual scheduler and evidence owner.
            request: The admitted operation.

        Returns:
            The complete result from the unmodified domain operation.
        """
        self.requests.append(request)
        if isinstance(request, self.kind):
            self.started.set()
            await self.released.wait()
        return await self.operation(session, request)


@dataclasses.dataclass(frozen=True, kw_only=True)
class RenderingGate:
    """Keep an applied generation unacknowledged while navigation supersedes it."""

    operation: collections.abc.Callable[
        [monitor_application.MonitorApp, peri_scribe.monitor.display.Records, int],
        collections.abc.Awaitable[None],
    ]
    started: asyncio.Event = dataclasses.field(default_factory=asyncio.Event)
    released: asyncio.Event = dataclasses.field(default_factory=asyncio.Event)
    generations: list[int] = dataclasses.field(default_factory=list)

    async def apply(
        self,
        app: monitor_application.MonitorApp,
        prepared: peri_scribe.monitor.display.Records,
        generation: int,
    ) -> None:
        """Retain the actual widget application before its completion checkpoint.

        Args:
            app: The mounted terminal receiving prepared content.
            prepared: The complete diagnostic content prepared in a worker.
            generation: The presentation revision captured by that worker.
        """
        await self.operation(app, prepared, generation)
        self.generations.append(generation)
        self.started.set()
        await self.released.wait()


@dataclasses.dataclass(frozen=True, kw_only=True)
class DisplayChange:
    """A paint wait cannot acknowledge a control message still queued for dispatch."""

    operation: collections.abc.Callable[[], None]
    dispatched: asyncio.Event = dataclasses.field(default_factory=asyncio.Event)

    def __call__(self) -> None:
        """Acknowledge only after the controller receives a new display generation."""
        self.operation()
        self.dispatched.set()


@dataclasses.dataclass(frozen=True, kw_only=True)
class TaskJoins:
    """Expose the exact owned tasks a flush joins, independently of callback timing."""

    operation: collections.abc.Callable[
        [asyncio.Task[None]],
        collections.abc.Awaitable[None],
    ]
    joined: asyncio.Queue[asyncio.Task[None]] = dataclasses.field(
        default_factory=asyncio.Queue,
    )

    async def settle(self, task: asyncio.Task[None]) -> None:
        """Record admission before preserving the production cancellation behavior.

        Args:
            task: The presentation work already selected by the controller.
        """
        self.joined.put_nowait(task)
        await self.operation(task)


async def wait_for_release(released: asyncio.Event) -> None:
    """Represent an owned preparation whose completion is controlled by the scenario.

    Args:
        released: The scenario's explicit permission for preparation to finish.
    """
    await released.wait()


def replace_display(
    controller: monitor_controller.Controller,
    replacement: asyncio.Task[None],
    completed: asyncio.Task[None],
) -> None:
    """Model a queued display request arriving before the flush resumes.

    Args:
        controller: The owner whose preparation was superseded.
        replacement: The already admitted successor task.
        completed: The preceding task whose completion dispatches this callback.
    """
    completed.result()
    controller.display_task = replacement
