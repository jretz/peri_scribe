"""Schedule actual blocking threads at the cancellation boundaries checked by TLC."""

import asyncio
import functools
import threading

import peri_scribe.concurrency
import tests.helpers.doubles.concurrency


async def owned_worker(
    operation: tests.helpers.doubles.concurrency.BlockedOperation,
    permit: asyncio.Semaphore,
    stopped: threading.Event,
    *,
    fails: bool,
) -> int:
    """Keep the concurrency permit inside the same lifetime as the worker owner.

    Args:
        operation: Controlled thread with explicit start and exit events.
        permit: The outer resource that cancellation must not release early.
        stopped: Signal delivered by the production cancellation handler.
        fails: Whether the worker raises while its owner is awaiting cleanup.

    Returns:
        The blocking operation's value on successful completion.
    """
    async with permit:
        return await peri_scribe.concurrency.run_blocking(
            functools.partial(operation.run, fail=fails),
            stopped=stopped,
        )


async def replay(*, cancellations: int, fails: bool) -> str:
    """Observe ownership before worker exit and compare its final outcome with TLC.

    Args:
        cancellations: Number of cancellations before the worker may exit.
        fails: Whether worker completion raises an error.

    Returns:
        The model's externally visible outcome label.
    """
    operation = tests.helpers.doubles.concurrency.BlockedOperation()
    permit = asyncio.Semaphore(1)
    stopped = threading.Event()
    task = asyncio.create_task(owned_worker(operation, permit, stopped, fails=fails))
    try:
        assert await asyncio.to_thread(operation.started.wait, 5)
        for _ in range(cancellations):
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
            assert permit.locked()
            assert stopped.is_set()
    finally:
        operation.release.set()
    try:
        await task
        outcome = "value"
    except asyncio.CancelledError:
        outcome = "cancelled"
    except RuntimeError:
        outcome = "error"
    assert operation.finished.is_set()
    assert not permit.locked()
    return outcome


class InterruptedRead:
    """Cancel during a blocking read so its completed bytes must not be delivered."""

    def __init__(self, stopped: threading.Event) -> None:
        """Retain the stream's cooperative stop signal.

        Args:
            stopped: Signal shared with the production stream iterator.
        """
        self.stopped = stopped
        self.reads = 0

    def __iter__(self) -> InterruptedRead:
        """Use a single stream position for observable reads.

        Returns:
            This stream.
        """
        return self

    def __next__(self) -> bytes:
        """Deliver late bytes only after cancellation has arrived.

        Returns:
            Bytes read concurrently with cancellation.
        """
        self.reads += 1
        self.stopped.set()
        return b"late bytes"
