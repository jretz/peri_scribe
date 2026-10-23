"""Replay competing monitor operations against the complete checked TLC graph."""

from __future__ import annotations

import asyncio
import collections.abc
import contextlib
import functools
import pathlib
import re
import typing

import peri_scribe.concurrency
import peri_scribe.monitor.session
import tests.formal.helpers.corpus
import tests.formal.helpers.paths
import tests.helpers.doubles.peri_scribe.monitor.tasks


if typing.TYPE_CHECKING:
    import pytest


def contract(
    directory: pathlib.Path,
) -> tests.formal.helpers.paths.Contract[
    tests.helpers.doubles.peri_scribe.monitor.tasks.Observation
]:
    """Use actual TLC edges for acquisition, read, publication, and teardown order.

    Args:
        directory: Isolated checker metadata and graph export location.

    Returns:
        The directed-path oracle projected onto concrete observable effects.
    """
    graph = tests.formal.helpers.corpus.graph("MonitorTasks", "MonitorTasks", directory)
    actions = {edge: edge.action for edges in graph.outgoing.values() for edge in edges}
    return tests.formal.helpers.paths.Contract(
        graph=graph,
        values={
            identifier: (
                state["stopped"] == "TRUE",
                state["closed"] == "TRUE",
                (int(state["active"]),) if state["active"] != "0" else (),
                tuple(sorted(map(int, re.findall(r"\d+", state["published"])))),
            )
            for identifier, state in graph.states.items()
        },
        actions=actions,
        internal=frozenset(actions.values()),
    )


async def replay(
    order: tuple[int, ...],
    cancellations: int,
    *,
    stop: bool,
    fails: bool,
) -> list[tests.helpers.doubles.peri_scribe.monitor.tasks.Observation]:
    """Hold the first real worker while peers, cancellation, and shutdown compete.

    An interrupted replay joins its callers before retiring the owner. Releasing the
    worker alone leaves queued operations running after the failed scenario returns.

    Args:
        order: Admission order for three competing evidence updates.
        cancellations: Repeated cancellation of the admitted task.
        stop: Whether shutdown begins before the active thread finishes.
        fails: Whether that active thread fails after release.

    Returns:
        Every observed boundary from initial state through descriptor retirement.
    """
    scenario = tests.helpers.doubles.peri_scribe.monitor.tasks.Scenario()
    scenario.remember()
    tasks = [
        asyncio.create_task(
            scenario.owner.run(
                functools.partial(
                    scenario.operation,
                    identifier,
                    fails=fails and position == 0,
                ),
            ),
        )
        for position, identifier in enumerate(order)
    ]
    closing = None
    callers = tasks.copy()
    async with owned_replay(scenario, callers):
        try:
            assert await asyncio.to_thread(scenario.worker.started.wait, 5)
            await tests.helpers.doubles.peri_scribe.monitor.tasks.cancelled(
                tasks[0],
                cancellations,
            )
            assert scenario.active == {order[0]}
            assert scenario.owner.lock.locked()
            if stop:
                closing = asyncio.create_task(scenario.stop())
                callers.append(closing)
                await scenario.owner.stopped.wait()
                await asyncio.sleep(0)
                assert not scenario.retired
                assert not closing.done()
            scenario.remember()
        finally:
            scenario.worker.release.set()
        outcomes = await asyncio.gather(*tasks, return_exceptions=True)
        if cancellations:
            assert isinstance(outcomes[0], asyncio.CancelledError)
        elif fails:
            assert isinstance(outcomes[0], RuntimeError)
        else:
            assert outcomes[0] is None
        if closing is not None:
            await closing
        else:
            await scenario.stop()
        assert scenario.published == (set() if stop else set(order[int(fails) :]))
        assert scenario.releases == 1
        assert not scenario.active
    return scenario.observations


@contextlib.asynccontextmanager
async def owned_replay(
    scenario: tests.helpers.doubles.peri_scribe.monitor.tasks.Scenario,
    callers: collections.abc.Sequence[asyncio.Task[None]],
) -> collections.abc.AsyncGenerator[None]:
    """Finish a failed scenario's admitted work before its owner leaves the replay.

    Args:
        scenario: The resource owner whose worker must finish before retirement.
        callers: Every operation or shutdown task admitted by the replay.

    Yields:
        Control while the replay observes its operations and checks their results.
    """
    try:
        yield
    except BaseException as failure:
        scenario.worker.release.set()
        cleanup = asyncio.create_task(finish_owned_replay(scenario, callers))
        await peri_scribe.concurrency.finish_worker(cleanup)
        try:
            cleanup.result()
        except BaseException as cleanup_failure:
            raise failure from cleanup_failure
        raise


async def finish_owned_replay(
    scenario: tests.helpers.doubles.peri_scribe.monitor.tasks.Scenario,
    callers: collections.abc.Sequence[asyncio.Task[None]],
) -> None:
    """Join every caller and retire the owner inside one cancellation-safe task.

    Args:
        scenario: The owner whose worker gate has already been released.
        callers: Operations and shutdown work retained until they complete.
    """
    await asyncio.gather(*callers, return_exceptions=True)
    await scenario.owner.close(scenario.release)


async def application_replay(
    directory: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    stop: bool,
    cancel: bool,
    lock: bool = False,
) -> list[tests.helpers.doubles.peri_scribe.monitor.tasks.Observation]:
    """Exercise domain requests using real compressed archives and retained log readers.

    A failed replay closes its private session before monkeypatches are restored. The
    shared replay releases its worker gate or file lock while unwinding; session close
    then joins that work and retires its readers while preserving the replay failure.

    Args:
        directory: An isolated observed year directory.
        monkeypatch: Restores the controlled worker gates after this execution.
        stop: Whether unmount competes with archive and refresh operations.
        cancel: Whether the admitted archive caller is repeatedly cancelled.
        lock: Whether to hold the actual writer flock through cancellation and unmount.

    Returns:
        Concrete observations through the monitor's actual state and descriptor APIs.
    """
    directory /= "2026"
    await asyncio.to_thread(directory.mkdir, parents=True)
    session = peri_scribe.monitor.session.MonitorSession(
        directory,
        directory / "report.md",
    )
    try:
        if lock:
            replay = tests.helpers.doubles.peri_scribe.monitor.tasks.session_lock_replay
            return await replay(session, monkeypatch)
        return await tests.helpers.doubles.peri_scribe.monitor.tasks.session_replay(
            session,
            monkeypatch,
            stop=stop,
            cancel=cancel,
        )
    except BaseException as failure:
        try:
            await session.close()
        except BaseException as cleanup_failure:
            raise failure from cleanup_failure
        raise
