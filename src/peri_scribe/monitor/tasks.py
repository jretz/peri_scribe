"""Keep evidence reads, publication, and descriptor retirement under one owner."""

import asyncio
import collections.abc
import dataclasses
import typing

import peri_scribe.concurrency


@dataclasses.dataclass(frozen=True, kw_only=True)
class Owner:
    """An admitted operation retains its resources until its result is settled."""

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
        """Serialize snapshots through publication, including cancelled callers.

        Args:
            operation: Work that checks stopped before publishing after an await.

        Returns:
            The operation's result, or None after admission has stopped.
        """
        async with self.lock:
            if self.stopped.is_set():
                return None
            return await settle(asyncio.create_task(operation()))

    async def close(self, release: collections.abc.Callable[[], None]) -> None:
        """Stop publication before asynchronously waiting for all descriptor users.

        Args:
            release: Descriptor cleanup, called once after admitted work finishes.
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
    """Cancellation reaches the caller only after its admitted work relinquishes use.

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
