"""Replay owners finish their workers before an assertion escapes."""

import asyncio
import functools
import pathlib
import unittest.mock

import pytest

import peri_scribe.monitor.session
import peri_scribe.monitor.tasks
import tests.formal.helpers.monitor_tasks
import tests.helpers.doubles.peri_scribe.monitor.synchronization
import tests.helpers.doubles.peri_scribe.monitor.tasks


@pytest.mark.parametrize("fails", [False, True])
@pytest.mark.parametrize("cancel_cleanup", [False, True])
@pytest.mark.asyncio
async def test_replay_joins_owned_operations_after_assertion_failure(
    monkeypatch: pytest.MonkeyPatch,
    *,
    fails: bool,
    cancel_cleanup: bool,
) -> None:
    scenario = tests.helpers.doubles.peri_scribe.monitor.tasks.Scenario()
    monkeypatch.setattr(
        tests.helpers.doubles.peri_scribe.monitor.tasks,
        "Scenario",
        unittest.mock.Mock(return_value=scenario),
    )
    failure = AssertionError("scenario assertion failed")
    monkeypatch.setattr(
        tests.helpers.doubles.peri_scribe.monitor.tasks,
        "cancelled",
        unittest.mock.AsyncMock(
            side_effect=(
                functools.partial(
                    tests.helpers.doubles.peri_scribe.monitor.synchronization.interrupt_cleanup,
                    failure,
                )
                if cancel_cleanup
                else failure
            ),
        ),
    )
    previous_tasks = asyncio.all_tasks()
    replay = asyncio.create_task(
        tests.formal.helpers.monitor_tasks.replay(
            (1, 2, 3),
            2,
            stop=True,
            fails=fails,
        ),
    )
    try:
        completed, _ = await asyncio.wait((replay,), timeout=5)
        assert completed
        with pytest.raises(AssertionError, match="scenario assertion failed") as caught:
            await replay
        assert caught.value is failure
        assert scenario.owner.closed.is_set()
        assert not scenario.active
        assert not asyncio.all_tasks() - previous_tasks
    finally:
        scenario.worker.release.set()
        await asyncio.gather(
            replay,
            *(asyncio.all_tasks() - previous_tasks),
            return_exceptions=True,
        )
        await scenario.owner.close(scenario.release)


@pytest.mark.asyncio
async def test_replay_preserves_assertion_when_owner_cleanup_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = tests.helpers.doubles.peri_scribe.monitor.tasks.Scenario()
    close = peri_scribe.monitor.tasks.Owner.close
    monkeypatch.setattr(
        tests.helpers.doubles.peri_scribe.monitor.tasks,
        "Scenario",
        unittest.mock.Mock(return_value=scenario),
    )
    failure = AssertionError("scenario assertion failed")
    cleanup_failure = OSError("cleanup failed")
    monkeypatch.setattr(
        tests.helpers.doubles.peri_scribe.monitor.tasks,
        "cancelled",
        unittest.mock.AsyncMock(side_effect=failure),
    )
    monkeypatch.setattr(
        peri_scribe.monitor.tasks.Owner,
        "close",
        unittest.mock.AsyncMock(side_effect=cleanup_failure),
    )
    try:
        with pytest.raises(AssertionError, match="scenario assertion failed") as caught:
            await tests.formal.helpers.monitor_tasks.replay(
                (1, 2, 3),
                2,
                stop=True,
                fails=False,
            )
        assert caught.value is failure
        assert caught.value.__cause__ is cleanup_failure
    finally:
        scenario.worker.release.set()
        await close(scenario.owner, scenario.release)


@pytest.mark.parametrize("lock", [False, True])
@pytest.mark.asyncio
async def test_application_replay_closes_its_session_after_assertion_failure(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    lock: bool,
) -> None:
    directory = tmp_path / "2026"
    session = peri_scribe.monitor.session.MonitorSession(
        directory,
        directory / "report.md",
    )
    monkeypatch.setattr(
        peri_scribe.monitor.session,
        "MonitorSession",
        unittest.mock.Mock(return_value=session),
    )
    failure = AssertionError("scenario assertion failed")
    monkeypatch.setattr(
        tests.helpers.doubles.peri_scribe.monitor.tasks,
        "cancelled",
        unittest.mock.AsyncMock(side_effect=failure),
    )
    previous_tasks = asyncio.all_tasks()
    replay = asyncio.create_task(
        tests.formal.helpers.monitor_tasks.application_replay(
            tmp_path,
            monkeypatch,
            stop=True,
            cancel=True,
            lock=lock,
        ),
    )
    try:
        completed, _ = await asyncio.wait((replay,), timeout=5)
        assert completed
        with pytest.raises(AssertionError, match="scenario assertion failed") as caught:
            await replay
        assert caught.value is failure
        assert session.owner.closed.is_set()
        assert not asyncio.all_tasks() - previous_tasks
    finally:
        await session.close()
        await asyncio.gather(
            replay,
            *(asyncio.all_tasks() - previous_tasks),
            return_exceptions=True,
        )


@pytest.mark.asyncio
async def test_application_replay_preserves_replay_failure_when_cleanup_fails(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = tmp_path / "2026"
    session = peri_scribe.monitor.session.MonitorSession(
        directory,
        directory / "report.md",
    )
    close = session.close
    monkeypatch.setattr(
        peri_scribe.monitor.session,
        "MonitorSession",
        unittest.mock.Mock(return_value=session),
    )
    failure = AssertionError("scenario assertion failed")
    cleanup_failure = OSError("cleanup failed")
    monkeypatch.setattr(
        tests.helpers.doubles.peri_scribe.monitor.tasks,
        "session_replay",
        unittest.mock.AsyncMock(side_effect=failure),
    )
    monkeypatch.setattr(
        session,
        "close",
        unittest.mock.AsyncMock(side_effect=cleanup_failure),
    )
    try:
        with pytest.raises(AssertionError, match="scenario assertion failed") as caught:
            await tests.formal.helpers.monitor_tasks.application_replay(
                tmp_path,
                monkeypatch,
                stop=True,
                cancel=True,
            )
        assert caught.value is failure
        assert caught.value.__cause__ is cleanup_failure
    finally:
        await close()
