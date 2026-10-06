"""Cancellation cannot outlive the thread while releasing its shared resource."""

import asyncio
import json
import pathlib
import threading

import pytest

import peri_scribe.concurrency
import tests.formal.helpers.corpus
import tests.formal.helpers.worker_lifetime


@pytest.mark.asyncio
async def test_run_blocking_matches_checked_cancel_and_failure_outcomes(
    tmp_path: pathlib.Path,
) -> None:
    states = await asyncio.to_thread(
        tests.formal.helpers.corpus.states,
        "WorkerLifetime",
        "WorkerLifetime",
        tmp_path,
    )
    cases = {
        (
            int(state["cancellations"]),
            state["fails"] == "TRUE",
            json.loads(state["outcome"]),
        )
        for state in states
        if state["owner"] == '"returned"'
    }
    assert {(count, failed) for count, failed, _ in cases} == {
        (count, failed) for count in range(3) for failed in (False, True)
    }
    saturated = max(count for count, _fails, _expected in cases)
    for cancellations, fails, expected in cases:
        repetitions = (cancellations,) if cancellations < saturated else (saturated, 5)
        for repeated in repetitions:
            assert (
                await tests.formal.helpers.worker_lifetime.replay(
                    cancellations=repeated,
                    fails=fails,
                )
                == expected
            )


def test_cancellable_matches_checked_late_read_suppression(
    tmp_path: pathlib.Path,
) -> None:
    states = tests.formal.helpers.corpus.states(
        "WorkerLifetime",
        "WorkerLifetime",
        tmp_path,
    )
    checked = next(
        state
        for state in states
        if state["stopped"] == "TRUE"
        and state["reads"] == "1"
        and state["delivered"] == "0"
        and state["reading"] == "FALSE"
    )
    stopped = threading.Event()
    source = tests.formal.helpers.worker_lifetime.InterruptedRead(stopped)
    with pytest.raises(asyncio.CancelledError):
        next(peri_scribe.concurrency.cancellable(source, stopped))
    assert source.reads == int(checked["reads"])
