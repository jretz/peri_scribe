"""Wait for active reads and publication before closing their file descriptors.

Algorithm reasoning and contracts:
[Worker lifetimes](../../../docs/algorithms/worker-lifetimes.md)
"""

import asyncio
import collections.abc
import dataclasses
import typing

import peri_scribe.concurrency


@dataclasses.dataclass(frozen=True, kw_only=True)
class Owner:
    """Keep resources available until their operation finishes, even on cancellation."""

    lock: asyncio.Lock = dataclasses.field(default_factory=asyncio.Lock)
    stopped: asyncio.Event = dataclasses.field(default_factory=asyncio.Event)
    closed: asyncio.Event = dataclasses.field(default_factory=asyncio.Event)

    async def run[Result](
        self,
        operation: collections.abc.Callable[
            [],
            collections.abc.Coroutine[typing.Any, typing.Any, Result],
        ],
    ) -> Result | None:
        """Run one operation through publication before allowing another to start.

        Once the operation starts, cancelling its caller still waits for it to finish.
        Otherwise a worker could keep using a reader after shutdown has closed it.

        Args:
            operation: Work that checks stopped before publishing after an await.

        Returns:
            The operation's result, or None after new work has been stopped.
        """
        async with self.lock:
            if self.stopped.is_set():
                return None
            return await settle(asyncio.create_task(operation()))

    async def close(self, release: collections.abc.Callable[[], None]) -> None:
        """Stop publication, then wait for active work before closing its files.

        Args:
            release: File-descriptor cleanup, called once after active work finishes.
        """
        self.stopped.set()
        await settle(asyncio.create_task(self.finish(release)))

    async def finish(self, release: collections.abc.Callable[[], None]) -> None:
        """Keep repeated shutdown and cancellation from racing descriptor cleanup.

        Args:
            release: Cleanup that may itself need to wait for synchronous readers.
        """
        async with self.lock:
            if not self.closed.is_set():
                await asyncio.to_thread(release)
                self.closed.set()


async def settle[Result](task: asyncio.Task[Result]) -> Result:
    """Propagate caller cancellation only after the task finishes using its resources.

    Args:
        task: An operation whose lifetime includes worker completion and publication.

    Returns:
        The operation's result when the caller remains interested.

    Raises:
        asyncio.CancelledError: After the operation finishes if its caller cancelled.
    """
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await peri_scribe.concurrency.finish_worker(task)
        raise
