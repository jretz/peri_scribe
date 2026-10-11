"""Observe complete session histories against the checked subscription protocol."""

import asyncio
import pathlib

import pytest

import peri_scribe.monitor.session
import tests.formal.helpers.monitor_session


@pytest.mark.asyncio
async def test_monitor_session_versions_and_subscriptions_match_tlc(
    tmp_path: pathlib.Path,
) -> None:
    contract = await asyncio.to_thread(
        tests.formal.helpers.monitor_session.contract,
        tmp_path / "checked",
    )
    directory = tmp_path / "2026"
    session = peri_scribe.monitor.session.MonitorSession(
        directory,
        directory / "report.md",
    )
    observer = tests.formal.helpers.monitor_session.Observer(session=session)
    execution = contract.start(observer.observation())
    observer.subscriptions[1] = session.subscribe()
    execution = execution.observe(observer.observation())
    await observer.receive(1)
    execution = execution.observe(observer.observation())
    observer.subscriptions[2] = session.subscribe()
    execution = execution.observe(observer.observation())
    for request in (
        peri_scribe.monitor.session.RefreshRecords(),
        peri_scribe.monitor.session.RefreshReport(),
    ):
        await session.request(request)
        execution = execution.observe(observer.observation())
    for identifier in (2, 1):
        await observer.receive(identifier)
        execution = execution.observe(observer.observation())
    observer.subscriptions[1].close()
    execution = execution.observe(observer.observation())
    await session.request(peri_scribe.monitor.session.LoadRun(identifier="missing"))
    execution = execution.observe(observer.observation())
    closing = asyncio.create_task(session.close())
    await session.owner.stopped.wait()
    execution = execution.observe(observer.observation())
    await closing
    execution.observe(observer.observation())
    assert await observer.subscriptions[2].receive() is None


def test_monitor_session_contract_rejects_obsolete_delivery(
    tmp_path: pathlib.Path,
) -> None:
    contract = tests.formal.helpers.monitor_session.contract(tmp_path)
    execution = contract.start((False, False, 0, (), (-1, -1)))
    execution = execution.observe((False, False, 0, (1,), (-1, -1)))
    execution = execution.observe((False, False, 1, (1,), (-1, -1)))
    execution = execution.observe((False, False, 2, (1,), (-1, -1)))
    with pytest.raises(AssertionError, match="no compatible TLC execution"):
        execution.observe((False, False, 2, (1,), (1, -1)))
