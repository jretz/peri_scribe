"""Generate versions examples with constrained domains."""

from __future__ import annotations

import hypothesis.strategies


def attribute_histories() -> hypothesis.strategies.SearchStrategy[
    list[tuple[int | None, int | None]]
]:
    """Make repeated states and reversions common in incident location histories.

    Returns:
        Canonical incident size and personnel states in snapshot order.
    """
    value = hypothesis.strategies.one_of(
        hypothesis.strategies.none(),
        hypothesis.strategies.integers(0, 3),
    )
    return hypothesis.strategies.lists(
        hypothesis.strategies.tuples(value, value),
        max_size=20,
    )
