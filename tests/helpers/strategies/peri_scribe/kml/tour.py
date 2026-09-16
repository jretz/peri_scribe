"""Generate tour examples with constrained domains."""

from __future__ import annotations

import datetime

import hypothesis.strategies


@hypothesis.strategies.composite
def ring_times(
    draw: hypothesis.strategies.DrawFn,
) -> list[datetime.datetime | None]:
    """Exercise repeated times, uneven gaps, undated rings, and long-running fires.

    Args:
        draw: The current example's strategy sampler.

    Returns:
        Observation times in chronological order, with undated rings first.
    """
    observations = draw(
        hypothesis.strategies.lists(
            hypothesis.strategies.one_of(
                hypothesis.strategies.none(),
                hypothesis.strategies.integers(0, 365 * 24 * 60 * 60),
            ),
            max_size=20,
        ),
    )
    base = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    return [
        None if seconds is None else base + datetime.timedelta(seconds=seconds)
        for seconds in sorted(
            observations,
            key=lambda value: -1 if value is None else value,
        )
    ]
