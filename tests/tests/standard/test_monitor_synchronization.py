"""Interrupted admission must leave the mounted fixture able to finish its worker."""

import asyncio
import threading

import pytest

import tests.helpers.doubles.peri_scribe.monitor.synchronization


@pytest.mark.parametrize("event_type", [asyncio.Event, threading.Event])
@pytest.mark.asyncio
async def test_release_on_exit_opens_gate_after_admission_wait_is_cancelled(
    event_type: type[asyncio.Event | threading.Event],
) -> None:
    released = event_type()
    admitted = asyncio.Event()
    task = asyncio.current_task()
    assert task is not None
    asyncio.get_running_loop().call_soon(task.cancel)
    try:
        with (
            pytest.raises(asyncio.CancelledError),
            tests.helpers.doubles.peri_scribe.monitor.synchronization.release_on_exit(
                released,
            ),
        ):
            await admitted.wait()
        assert released.is_set()
    finally:
        task.uncancel()
