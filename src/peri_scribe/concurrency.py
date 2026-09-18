"""Own blocking workers until their writes and resources have finished."""

import asyncio
import threading
import typing


async def run_blocking[Result](
    function: typing.Callable[[], Result],
    *,
    stopped: threading.Event | None = None,
) -> Result:
    """Wait for worker cleanup even when its coordinating task is cancelled.

    Cancellation cannot stop a Python thread. Its enclosing task must remain alive
    until the worker exits so temporary files and shared writers remain available.

    Args:
        function: The blocking operation, with context variables propagated to it.
        stopped: Optional cooperative cancellation signal shared with the operation.

    Returns:
        The operation's result.

    Raises:
        asyncio.CancelledError: Cancellation is propagated after the worker exits.
    """
    worker = asyncio.create_task(asyncio.to_thread(function))
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        if stopped is not None:
            stopped.set()
        await finish_worker(worker)
        raise


async def finish_worker[Result](worker: asyncio.Task[Result]) -> None:
    """Keep repeated cancellation from abandoning resources owned by a thread.

    Args:
        worker: A worker whose result or error no longer replaces cancellation.
    """
    cleanup = asyncio.gather(worker, return_exceptions=True)
    while not cleanup.done():
        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError:
            continue


def cancellable[Item](
    items: typing.Iterable[Item],
    stopped: threading.Event,
) -> typing.Iterator[Item]:
    """Stop consuming or delivering chunks once their worker is cancelled.

    Checks on both sides of each read prevent a cancelled worker from starting another
    blocking read or processing bytes that arrived after cancellation.

    Args:
        items: The stream of download or conversion chunks.
        stopped: The worker's cooperative cancellation signal.

    Yields:
        Items in source order while the worker remains active.

    Raises:
        asyncio.CancelledError: When the coordinating task requests cancellation.
    """
    iterator = iter(items)
    while True:
        if stopped.is_set():
            raise asyncio.CancelledError
        try:
            item = next(iterator)
        except StopIteration:
            return
        if stopped.is_set():
            raise asyncio.CancelledError
        yield item
