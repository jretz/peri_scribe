"""Own blocking workers until their writes and resources have finished.

Algorithm reasoning and contracts:
[Worker lifetimes](../../docs/algorithms/worker-lifetimes.md)
[Ordered history work](../../docs/algorithms/history-work-queues.md)
"""

import asyncio
import concurrent.futures
import contextlib
import threading
import typing


@contextlib.contextmanager
def ordered_parallel_map[Item, Result](
    function: typing.Callable[[Item], Result],
    items: typing.Iterable[Item],
    *,
    max_workers: int,
    max_pending: int = 64,
    weight: typing.Callable[[Item], int] | None = None,
    max_weight: int | None = None,
) -> typing.Generator[typing.Iterator[Result]]:
    """Refill independent work on completion and deliver results in input order.

    The context owns every worker until it settles, including when the consumer raises
    or stops early. Completed results awaiting an earlier position remain resident;
    admission bounds cover unfinished tasks, not output bytes or process memory. Input,
    submission, consumer and worker failures leave the context after worker cleanup.

    Args:
        function: Independent operation, with input resources owned by this context.
        items: Inputs in required output order; iteration occurs on the owning thread.
        max_workers: Maximum simultaneously executing operations.
        max_pending: Maximum submitted futures awaiting completion observation.
        weight: Nonnegative integer input weight, evaluated before submission.
        max_weight: Positive admitted-weight limit; one oversized input runs alone.
            Weights default to one when no weight function is supplied.

    Yields:
        An iterator that delivers successful results or worker errors in input order.

    Raises:
        ValueError: If an admission limit is nonpositive or an input weight is invalid.
    """
    if (
        max_workers < 1
        or max_pending < 1
        or (max_weight is not None and max_weight < 1)
    ):
        message = "Worker, pending and weight limits must be positive"
        raise ValueError(message)
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
    results = ordered_results(
        executor,
        function,
        items,
        max_pending=max_pending,
        weight=weight,
        max_weight=max_weight,
    )
    try:
        yield results
    finally:
        try:
            results.close()
        finally:
            executor.shutdown(wait=True, cancel_futures=True)


def ordered_results[Item, Result](
    executor: concurrent.futures.ThreadPoolExecutor,
    function: typing.Callable[[Item], Result],
    items: typing.Iterable[Item],
    *,
    max_pending: int,
    weight: typing.Callable[[Item], int] | None,
    max_weight: int | None,
) -> typing.Generator[Result]:
    """Keep admission independent of the next position due for delivery.

    Input and submission errors propagate immediately; worker errors follow input order.

    Args:
        executor: Workers whose enclosing context cancels and joins on every exit.
        function: Independent task calculation.
        items: Ordered inputs whose production can fail on the owning thread.
        max_pending: Positive bound on unobserved submitted futures.
        weight: Optional nonnegative encoded input weight.
        max_weight: Optional positive pending-weight budget.

    Yields:
        Results in input order, raising the earliest submitted worker error in order.

    Raises:
        ValueError: When a weight is not a nonnegative integer.
    """
    iterator = enumerate(items)
    pending: dict[concurrent.futures.Future[Result], tuple[int, int]] = {}
    ready: dict[int, concurrent.futures.Future[Result]] = {}
    waiting: tuple[int, Item, int] | None = None
    pending_weight = 0
    next_position = 0
    exhausted = False
    failed = False
    while pending or not exhausted:
        while not failed and not exhausted and len(pending) < max_pending:
            if waiting is None:
                try:
                    position, item = next(iterator)
                except StopIteration:
                    exhausted = True
                    break
                item_weight = 1 if weight is None else weight(item)
                if not isinstance(item_weight, int) or item_weight < 0:
                    message = "Input weights must be nonnegative integers"
                    raise ValueError(message)
                waiting = position, item, item_weight
            position, item, item_weight = waiting
            if (
                pending
                and max_weight is not None
                and pending_weight + item_weight > max_weight
            ):
                break
            pending[executor.submit(function, item)] = position, item_weight
            pending_weight += item_weight
            waiting = None
        if not pending:
            break
        completed, _ = concurrent.futures.wait(
            pending,
            return_when=concurrent.futures.FIRST_COMPLETED,
        )
        for future in completed:
            position, item_weight = pending.pop(future)
            pending_weight -= item_weight
            ready[position] = future
            failed = failed or future.exception() is not None
        while next_position in ready:
            yield ready.pop(next_position).result()
            next_position += 1


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
