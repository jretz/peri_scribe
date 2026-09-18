"""Cancellation must retain ownership of blocking workers."""

import asyncio
import contextvars
import functools
import itertools
import threading

import pytest

import peri_scribe.concurrency
import tests.helpers.doubles.concurrency


@pytest.mark.asyncio
@pytest.mark.parametrize("fail", [False, True])
async def test_run_blocking_waits_for_worker_after_cancellation(*, fail: bool) -> None:
    operation = tests.helpers.doubles.concurrency.BlockedOperation()
    task = asyncio.create_task(
        peri_scribe.concurrency.run_blocking(
            functools.partial(operation.run, fail=fail),
        ),
    )
    try:
        assert await asyncio.to_thread(operation.started.wait, 5)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
    finally:
        operation.release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert operation.finished.is_set()


@pytest.mark.asyncio
async def test_run_blocking_propagates_context() -> None:
    context: contextvars.ContextVar[str] = contextvars.ContextVar("source")
    token = context.set("test-feed")
    try:
        assert await peri_scribe.concurrency.run_blocking(context.get) == "test-feed"
    finally:
        context.reset(token)


@pytest.mark.asyncio
async def test_run_blocking_propagates_worker_failure() -> None:
    operation = tests.helpers.doubles.concurrency.BlockedOperation()
    operation.release.set()
    with pytest.raises(RuntimeError, match="worker failed"):
        await peri_scribe.concurrency.run_blocking(
            functools.partial(operation.run, fail=True),
        )


@pytest.mark.parametrize("delivered", [0, 1])
def test_cancellable_does_not_read_after_cancellation(delivered: int) -> None:
    stopped = threading.Event()
    values = [1, 2, 3]
    source = iter(values)
    chunks = peri_scribe.concurrency.cancellable(source, stopped)
    assert list(itertools.islice(chunks, delivered)) == values[:delivered]
    stopped.set()
    with pytest.raises(asyncio.CancelledError):
        next(chunks)
    assert list(source) == values[delivered:]
