"""Generate areas examples with constrained domains."""

from __future__ import annotations

import hypothesis.strategies


@hypothesis.strategies.composite
def history_entries(
    draw: hypothesis.strategies.DrawFn,
) -> list[tuple[float, float]]:
    """Give reports and mappings distinct dates without restricting growth direction.

    Args:
        draw: The current example's strategy sampler.

    Returns:
        Chronological observation days paired with positive acreages.
    """
    entries = draw(
        hypothesis.strategies.dictionaries(
            hypothesis.strategies.integers(0, 30),
            hypothesis.strategies.integers(1, 100_000),
            max_size=8,
        ),
    )
    return [(float(day), float(area)) for day, area in sorted(entries.items())]
