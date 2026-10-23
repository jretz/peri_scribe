"""Expose tab-worker admission separately from preparation and final layout."""

import asyncio
import collections.abc
import contextlib
import dataclasses
import threading
import typing


@contextlib.contextmanager
def release_on_exit(
    released: asyncio.Event | threading.Event,
) -> collections.abc.Generator[None]:
    """Unblock a worker even when its scenario is interrupted before admission.

    Enter before awaiting the worker's start signal. The owning monitor fixture
    joins work after the gate opens, before restoring its monkeypatches.

    Args:
        released: The gate keeping the scenario's worker alive.

    Yields:
        Control while the scenario admits and checks the worker.
    """
    try:
        yield
    finally:
        released.set()


def interrupt_cleanup(failure: BaseException, *arguments: object) -> typing.Never:
    """Deliver cancellation at the first suspension after a scenario fails.

    Raises the supplied scenario failure before cancellation can be delivered.

    Args:
        failure: The scenario error that cleanup must preserve.
        arguments: Arguments supplied by the observed callback boundary.
    """
    task = asyncio.current_task()
    assert task is not None
    asyncio.get_running_loop().call_soon(task.cancel)
    raise failure


@dataclasses.dataclass(frozen=True, kw_only=True)
class Activation:
    """Hold a dispatched navigation worker before it schedules table preparation."""

    operation: collections.abc.Callable[[str], collections.abc.Awaitable[None]]
    started: asyncio.Event = dataclasses.field(default_factory=asyncio.Event)
    released: asyncio.Event = dataclasses.field(default_factory=asyncio.Event)

    async def activate(self, name: str) -> None:
        """Expose admission before continuing the real tab activation.

        Args:
            name: The requested terminal tab.
        """
        self.started.set()
        await self.released.wait()
        await self.operation(name)


@dataclasses.dataclass(frozen=True, kw_only=True)
class Cancellation:
    """Keep task cleanup pending after cancellation has been delivered."""

    started: asyncio.Event = dataclasses.field(default_factory=asyncio.Event)
    cancelling: asyncio.Event = dataclasses.field(default_factory=asyncio.Event)
    released: asyncio.Event = dataclasses.field(default_factory=asyncio.Event)

    async def wait(self) -> None:
        """Expose cancellation cleanup independently of the caller requesting it."""
        self.started.set()
        try:
            await self.released.wait()
        finally:
            self.cancelling.set()
            await self.released.wait()
