"""Replay competing monitor operations against the complete checked TLC graph."""

from __future__ import annotations

import asyncio
import functools
import pathlib
import re
import typing
import unittest.mock

import peri_scribe.monitor.app
import tests.formal.helpers.corpus
import tests.formal.helpers.paths
import tests.helpers.doubles.peri_scribe.monitor.tasks
import tests.helpers.factories.peri_scribe.monitor.events
import tests.helpers.textual


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


async def application_replay(
    directory: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    stop: bool,
    cancel: bool,
    lock: bool = False,
) -> list[tests.helpers.doubles.peri_scribe.monitor.tasks.Observation]:
    """Exercise public monitor methods on mounted widgets and real compressed logs.

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
    app = peri_scribe.monitor.app.MonitorApp(
        directory,
        directory / "report.md",
        tests.helpers.factories.peri_scribe.monitor.events.BRANCHES,
    )
    monkeypatch.setattr(app, "set_interval", unittest.mock.Mock())
    monkeypatch.setattr(
        peri_scribe.monitor.app,
        "watch_files",
        unittest.mock.AsyncMock(),
    )
    async with tests.helpers.textual.mounted(app):
        if lock:
            replay_lock = (
                tests.helpers.doubles.peri_scribe.monitor.tasks.shared_lock_replay
            )
            return await replay_lock(app, monkeypatch)
        return await tests.helpers.doubles.peri_scribe.monitor.tasks.application_replay(
            app,
            monkeypatch,
            stop=stop,
            cancel=cancel,
        )
