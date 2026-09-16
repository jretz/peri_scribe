"""Generate feed state examples with constrained domains."""

from __future__ import annotations

import hypothesis.strategies


def sql_values() -> hypothesis.strategies.SearchStrategy[str | int | float | bool]:
    """Exercise literal escaping and fractional numbers within SQLite's value domain.

    SQLite provides an independent decoder for standard SQL literals. Query text cannot
    contain NUL or unpaired surrogates, and integers must fit its signed 64-bit range.

    Returns:
        Text, booleans, finite real numbers, and signed 64-bit integers.
    """
    return hypothesis.strategies.one_of(
        hypothesis.strategies.text(
            hypothesis.strategies.characters(
                exclude_categories=("Cs",),
                exclude_characters="\0",
            ),
            max_size=80,
        ),
        hypothesis.strategies.integers(-(2**63), 2**63 - 1),
        hypothesis.strategies.floats(-1_000_000, 1_000_000),
        hypothesis.strategies.booleans(),
    )


def feature_batches() -> hypothesis.strategies.SearchStrategy[
    list[list[tuple[int, str]]]
]:
    """Make repeated identifiers common across short sequences of source snapshots.

    Returns:
        Feature batches in their source observation order.
    """
    return hypothesis.strategies.lists(
        hypothesis.strategies.lists(
            hypothesis.strategies.tuples(
                hypothesis.strategies.integers(0, 5),
                hypothesis.strategies.text(max_size=30),
            ),
            max_size=8,
        ),
        min_size=1,
        max_size=5,
    )
