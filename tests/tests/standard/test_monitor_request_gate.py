"""A failed concurrency assertion must leave its blocked monitor requests settled."""

import asyncio
import pathlib
import unittest.mock

import pytest

import peri_scribe.monitor.session
import tests.helpers.doubles.peri_scribe.monitor.session


@pytest.mark.parametrize("cancel_cleanup", [False, True])
@pytest.mark.asyncio
async def test_gate_running_releases_and_joins_requests_after_assertion_failure(
    monitor_year: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    cancel_cleanup: bool,
) -> None:
    session = peri_scribe.monitor.session.MonitorSession(
        monitor_year,
        monitor_year / "report.md",
    )
    gate = tests.helpers.doubles.peri_scribe.monitor.session.Gate()
    monkeypatch.setattr(peri_scribe.monitor.session, "execute", gate.execute)
    failure = AssertionError("scenario assertion failed")
    failing = asyncio.create_task(
        tests.helpers.doubles.peri_scribe.monitor.session.fail_after_admission(
            gate,
            session,
            failure,
            cancel_cleanup=cancel_cleanup,
        ),
    )
    try:
        completed, _ = await asyncio.wait((failing,), timeout=5)
        assert completed
        with pytest.raises(AssertionError, match="scenario assertion failed") as caught:
            await failing
        assert caught.value is failure
        assert gate.tasks
        assert all(task.done() for task in gate.tasks)
        assert session.owner.closed.is_set()
    finally:
        gate.released.set()
        await asyncio.gather(failing, return_exceptions=True)
        await session.close()


@pytest.mark.asyncio
async def test_gate_running_preserves_assertion_when_session_cleanup_fails(
    monitor_year: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = peri_scribe.monitor.session.MonitorSession(
        monitor_year,
        monitor_year / "report.md",
    )
    gate = tests.helpers.doubles.peri_scribe.monitor.session.Gate()
    monkeypatch.setattr(peri_scribe.monitor.session, "execute", gate.execute)
    close = session.close
    failure = AssertionError("scenario assertion failed")
    cleanup_failure = OSError("cleanup failed")
    monkeypatch.setattr(
        session,
        "close",
        unittest.mock.AsyncMock(side_effect=cleanup_failure),
    )
    failing = asyncio.create_task(
        tests.helpers.doubles.peri_scribe.monitor.session.fail_after_admission(
            gate,
            session,
            failure,
        ),
    )
    try:
        with pytest.raises(AssertionError, match="scenario assertion failed") as caught:
            await failing
        assert caught.value is failure
        assert caught.value.__cause__ is cleanup_failure
        assert gate.tasks
        assert all(task.done() for task in gate.tasks)
    finally:
        gate.released.set()
        await asyncio.gather(failing, return_exceptions=True)
        await close()
