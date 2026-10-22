"""Optional cache cleanup agrees with checked retirement and reader traces."""

import pathlib

import pytest

import tests.formal.helpers.corpus
import tests.formal.helpers.crash_worker
import tests.formal.helpers.process_crashes
import tests.formal.helpers.product_cache
import tests.formal.helpers.product_retention


def test_retire_contexts_matches_every_checked_maintenance_prefix(
    tmp_path: pathlib.Path,
) -> None:
    states = tests.formal.helpers.corpus.states(
        "ProductRetention",
        "ProductRetention",
        tmp_path / "tlc",
    )
    assert {int(state["phase"]) for state in states} == set(range(4))
    assert {state["readerPhase"] for state in states} == {"0", "1", "2"}
    for index, state in enumerate(states):
        tests.formal.helpers.product_retention.replay(
            state,
            tmp_path / f"prefix-{index}.sqlite",
        )


@pytest.mark.parametrize("boundary", ["delete", "commit", "compact"])
@pytest.mark.parametrize("method", ["exit", "kill"])
def test_maintain_store_preserves_checked_rows_after_hard_process_termination(
    tmp_path: pathlib.Path,
    boundary: str,
    method: str,
) -> None:
    states = tests.formal.helpers.corpus.states(
        "ProductRetention",
        "ProductRetention",
        tmp_path / "tlc",
    )
    prefix = {
        "delete": (1, 3),
        "commit": (1, 2),
        "compact": (1, 2, 5),
    }[boundary]
    expected = next(
        state
        for state in states
        if tests.formal.helpers.product_cache.numbers(state["retained"]) == (1,)
        and tests.formal.helpers.product_cache.numbers(state["trace"]) == prefix
    )
    records = tests.formal.helpers.process_crashes.history(
        tests.formal.helpers.crash_worker.Request(
            root=str(tmp_path / "processes"),
            family="product_retention",
            phase="crash",
            boundary=boundary,
            after=True,
            method=method,
        ),
    )

    assert [record["value"] for record in records if record["kind"] == "recovered"] == [
        sorted(tests.formal.helpers.product_cache.numbers(expected["durable"])),
    ]
