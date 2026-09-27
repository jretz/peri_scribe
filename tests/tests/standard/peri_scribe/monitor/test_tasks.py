"""Keep cancelled monitor tasks and descriptor cleanup inside their resource owner."""

import asyncio
import functools
import unittest.mock

import pytest

import peri_scribe.monitor.tasks
import tests.helpers.doubles.peri_scribe.monitor.tasks


@pytest.mark.asyncio
async def test_owner_run_preserves_consumed_evidence_when_caller_cancels() -> None:
    scenario = tests.helpers.doubles.peri_scribe.monitor.tasks.Scenario()
    task = asyncio.create_task(
        scenario.owner.run(functools.partial(scenario.operation, 1)),
    )
    try:
        assert await asyncio.to_thread(scenario.worker.started.wait, 5)
        await tests.helpers.doubles.peri_scribe.monitor.tasks.cancelled(task, 3)
        assert scenario.owner.lock.locked()
    finally:
        scenario.worker.release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert scenario.published == {1}
    await scenario.owner.run(functools.partial(scenario.operation, 2))
    assert scenario.published == {1, 2}


@pytest.mark.asyncio
async def test_owner_run_cancels_queued_work_without_touching_active_work() -> None:
    scenario = tests.helpers.doubles.peri_scribe.monitor.tasks.Scenario()
    active = asyncio.create_task(
        scenario.owner.run(functools.partial(scenario.operation, 1)),
    )
    queued = asyncio.create_task(
        scenario.owner.run(functools.partial(scenario.operation, 2)),
    )
    try:
        assert await asyncio.to_thread(scenario.worker.started.wait, 5)
        queued.cancel()
        with pytest.raises(asyncio.CancelledError):
            await queued
        assert scenario.active == {1}
        assert not active.done()
    finally:
        scenario.worker.release.set()
    await active
    assert scenario.published == {1}


@pytest.mark.asyncio
async def test_owner_close_waits_for_workers_despite_repeated_cancellation() -> None:
    scenario = tests.helpers.doubles.peri_scribe.monitor.tasks.Scenario()
    active = asyncio.create_task(
        scenario.owner.run(functools.partial(scenario.operation, 1)),
    )
    try:
        assert await asyncio.to_thread(scenario.worker.started.wait, 5)
        closing = asyncio.create_task(scenario.owner.close(scenario.release))
        await scenario.owner.stopped.wait()
        await tests.helpers.doubles.peri_scribe.monitor.tasks.cancelled(closing, 3)
        assert not scenario.retired
    finally:
        scenario.worker.release.set()
    await active
    with pytest.raises(asyncio.CancelledError):
        await closing
    await scenario.owner.close(scenario.release)
    await scenario.owner.run(functools.partial(scenario.operation, 2))
    assert scenario.owner.closed.is_set()
    assert scenario.releases == 1
    assert scenario.published == set()


@pytest.mark.asyncio
async def test_owner_run_releases_ownership_after_worker_failure() -> None:
    scenario = tests.helpers.doubles.peri_scribe.monitor.tasks.Scenario()
    scenario.worker.release.set()
    with pytest.raises(RuntimeError, match="worker failed"):
        await scenario.owner.run(functools.partial(scenario.operation, 1, fails=True))
    await scenario.owner.run(functools.partial(scenario.operation, 2))
    assert scenario.published == {2}


@pytest.mark.asyncio
async def test_owner_close_can_retry_failed_cleanup_without_reopening_admission() -> (
    None
):
    owner = peri_scribe.monitor.tasks.Owner()
    release = unittest.mock.Mock(side_effect=[OSError("close failed"), None])
    with pytest.raises(OSError, match="close failed"):
        await owner.close(release)
    assert owner.stopped.is_set()
    assert not owner.closed.is_set()
    await owner.close(release)
    assert owner.closed.is_set()
