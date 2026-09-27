"""Actual async owners retain resources through cancellation and reject stale writes."""

import asyncio
import itertools
import pathlib

import pytest

import tests.formal.helpers.monitor_tasks


@pytest.mark.asyncio
async def test_owner_matches_tlc_execution_for_competing_monitor_operations(
    tmp_path: pathlib.Path,
) -> None:
    contract = await asyncio.to_thread(
        tests.formal.helpers.monitor_tasks.contract,
        tmp_path,
    )
    for order, cancellations, stop, fails in itertools.product(
        itertools.permutations((1, 2, 3)),
        (0, 1, 2, 5),
        (False, True),
        (False, True),
    ):
        observations = await tests.formal.helpers.monitor_tasks.replay(
            order,
            cancellations,
            stop=stop,
            fails=fails,
        )
        execution = contract.start(observations[0])
        for observation in observations[1:]:
            execution = execution.observe(observation)


@pytest.mark.asyncio
async def test_monitor_app_public_operations_match_tlc_execution(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = await asyncio.to_thread(
        tests.formal.helpers.monitor_tasks.contract,
        tmp_path / "checked",
    )
    for stop, cancel in itertools.product((False, True), repeat=2):
        with monkeypatch.context() as patch:
            observations = await tests.formal.helpers.monitor_tasks.application_replay(
                tmp_path / f"app-{stop}-{cancel}",
                patch,
                stop=stop,
                cancel=cancel,
            )
        execution = contract.start(observations[0])
        for observation in observations[1:]:
            execution = execution.observe(observation)
    with monkeypatch.context() as patch:
        observations = await tests.formal.helpers.monitor_tasks.application_replay(
            tmp_path / "app-shared-lock",
            patch,
            stop=True,
            cancel=True,
            lock=True,
        )
    execution = contract.start(observations[0])
    for observation in observations[1:]:
        execution = execution.observe(observation)


def test_owner_tlc_contract_rejects_retirement_before_operation_exit(
    tmp_path: pathlib.Path,
) -> None:
    contract = tests.formal.helpers.monitor_tasks.contract(tmp_path)
    execution = contract.start((False, False, (), ()))
    execution = execution.observe((False, False, (1,), ()))
    execution = execution.observe((True, False, (1,), ()))
    with pytest.raises(AssertionError, match="no compatible TLC execution"):
        execution.observe((True, True, (1,), ()))


def test_owner_tlc_contract_rejects_reachable_but_reordered_publication(
    tmp_path: pathlib.Path,
) -> None:
    contract = tests.formal.helpers.monitor_tasks.contract(tmp_path)
    execution = contract.start((False, False, (), ()))
    execution = execution.observe((False, False, (1,), ()))
    execution = execution.observe((False, False, (1,), (1,)))
    execution = execution.observe((False, False, (), (1,)))
    stale = (False, False, (2,), ())
    assert stale in contract.values.values()
    with pytest.raises(AssertionError, match="no compatible TLC execution"):
        execution.observe(stale)
