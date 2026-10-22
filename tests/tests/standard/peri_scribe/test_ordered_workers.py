"""Completion-driven admission preserves ordering and resource ownership."""

import threading
import typing

import pytest

import peri_scribe.concurrency
import tests.helpers.doubles.concurrency


def test_ordered_parallel_map_refills_behind_blocked_first_result() -> None:
    calls = tests.helpers.doubles.concurrency.OrderedCalls()
    with peri_scribe.concurrency.ordered_parallel_map(
        calls.refill,
        range(3),
        max_workers=2,
        max_pending=2,
    ) as results:
        assert list(results) == [0, 1, 2]
    assert calls.refilled.is_set()


def test_ordered_parallel_map_delivers_earliest_input_error() -> None:
    calls = tests.helpers.doubles.concurrency.OrderedCalls()
    with (
        pytest.raises(RuntimeError, match=r"^0$"),
        peri_scribe.concurrency.ordered_parallel_map(
            calls.failure,
            range(3),
            max_workers=2,
            max_pending=2,
        ) as results,
    ):
        list(results)


def test_ordered_parallel_map_joins_after_input_error() -> None:
    calls = tests.helpers.doubles.concurrency.OrderedCalls()
    owner = threading.Thread(target=calls.consume_failure)
    owner.start()
    try:
        assert calls.started.wait(5)
        assert not calls.consumer_finished.is_set()
    finally:
        calls.release.set()
        owner.join(5)
    assert not owner.is_alive()
    assert calls.finished.is_set()
    assert isinstance(calls.errors[0], LookupError)


def test_ordered_parallel_map_joins_when_consumer_stops() -> None:
    calls = tests.helpers.doubles.concurrency.OrderedCalls()
    owner = threading.Thread(target=calls.close_early)
    owner.start()
    try:
        assert calls.started.wait(5)
        assert not calls.consumer_finished.is_set()
    finally:
        calls.release.set()
        owner.join(5)
    assert not owner.is_alive()
    assert calls.finished.is_set()
    assert calls.values == [0]


@pytest.mark.parametrize("items", [[], [None, 0, False]])
def test_ordered_parallel_map_preserves_empty_and_false_results(
    items: list[object],
) -> None:
    with peri_scribe.concurrency.ordered_parallel_map(
        lambda value: value,
        items,
        max_workers=1,
    ) as results:
        assert list(results) == items


@pytest.mark.parametrize(
    "limits",
    [{"max_workers": 0}, {"max_pending": 0}, {"max_weight": 0}],
)
def test_ordered_parallel_map_rejects_nonpositive_limits(
    limits: dict[str, int],
) -> None:
    with (
        pytest.raises(ValueError, match="limits must be positive"),
        peri_scribe.concurrency.ordered_parallel_map(
            str,
            [1],
            max_workers=limits.get("max_workers", 1),
            max_pending=limits.get("max_pending", 64),
            max_weight=limits.get("max_weight"),
        ),
    ):
        pass


@pytest.mark.parametrize("value", [-1, 0.5])
def test_ordered_parallel_map_rejects_invalid_weights(value: float) -> None:
    with (
        pytest.raises(ValueError, match="nonnegative integers"),
        peri_scribe.concurrency.ordered_parallel_map(
            str,
            [1],
            max_workers=1,
            weight=lambda _: typing.cast("int", value),
        ) as results,
    ):
        list(results)


def test_ordered_parallel_map_admits_oversized_and_zero_weight_inputs() -> None:
    items = [1, 3, 0, 2, 1]
    with peri_scribe.concurrency.ordered_parallel_map(
        str,
        items,
        max_workers=2,
        max_pending=2,
        weight=int,
        max_weight=2,
    ) as results:
        assert list(results) == list(map(str, items))


def test_ordered_parallel_map_does_not_submit_unconsumed_inputs() -> None:
    calls: list[int] = []
    with peri_scribe.concurrency.ordered_parallel_map(
        calls.append,
        [1],
        max_workers=1,
    ):
        pass
    assert calls == []
