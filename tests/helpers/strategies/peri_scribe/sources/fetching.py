"""Generate fetching examples with constrained domains."""

from __future__ import annotations

import dataclasses

import hypothesis.strategies

import tests.helpers.factories.peri_scribe.sources.fetching


@hypothesis.strategies.composite
def fetch_scenarios(
    draw: hypothesis.strategies.DrawFn,
) -> tuple[
    dict[int, tests.helpers.factories.peri_scribe.sources.fetching.FetchFeature],
    dict[int, tests.helpers.factories.peri_scribe.sources.fetching.FetchFeature],
]:
    """Mix overlapping fetch signals, geometry edits, removals, and unchanged rows.

    The stored anchors establish the latest modification time and both raw status
    spellings, which are prerequisites for the feed's status-change query.

    Args:
        draw: The current example's strategy sampler.

    Returns:
        Stored and current source features, each with unique object IDs.
    """
    feature = hypothesis.strategies.builds(
        tests.helpers.factories.peri_scribe.sources.fetching.FetchFeature,
        name=hypothesis.strategies.sampled_from(["River", "Cañon", "Cedar"]),
        modified_minute=hypothesis.strategies.one_of(
            hypothesis.strategies.none(),
            hypothesis.strategies.integers(-10, 10),
        ),
        longitude=hypothesis.strategies.integers(-2, 2),
    )
    stored = draw(
        hypothesis.strategies.dictionaries(
            hypothesis.strategies.integers(2, 6),
            feature,
            max_size=5,
        ),
    )
    stored = {
        identifier: dataclasses.replace(
            item,
            modified_minute=None
            if item.modified_minute is None
            else min(item.modified_minute, 0),
        )
        for identifier, item in stored.items()
    }
    stored.update({
        0: tests.helpers.factories.peri_scribe.sources.fetching.FetchFeature(
            name="Cedar",
            active=False,
            modified_minute=0,
            longitude=0,
        ),
        1: tests.helpers.factories.peri_scribe.sources.fetching.FetchFeature(
            name="River",
            active=True,
            modified_minute=0,
            longitude=1,
        ),
    })
    current = draw(
        hypothesis.strategies.dictionaries(
            hypothesis.strategies.integers(0, 8),
            hypothesis.strategies.one_of(
                hypothesis.strategies.sampled_from(list(stored.values())),
                feature,
            ),
            min_size=1,
            max_size=9,
        ),
    )
    return stored, current
