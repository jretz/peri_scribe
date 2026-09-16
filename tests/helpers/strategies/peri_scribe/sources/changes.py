"""Generate changes examples with constrained domains."""

from __future__ import annotations

import operator
import typing

import hypothesis.strategies


if typing.TYPE_CHECKING:
    import tests.helpers.factories.peri_scribe.sources.changes


@hypothesis.strategies.composite
def feature_pairs(
    draw: hypothesis.strategies.DrawFn,
) -> tuple[
    list[tests.helpers.factories.peri_scribe.sources.changes.FeatureRow],
    list[tests.helpers.factories.peri_scribe.sources.changes.FeatureRow],
]:
    """Make unchanged rows common alongside attribute edits and geometry-only edits.

    Args:
        draw: The current example's strategy sampler.

    Returns:
        Existing and fetched rows, each with unique OBJECTIDs in arbitrary order.
    """
    row = hypothesis.strategies.tuples(
        hypothesis.strategies.integers(0, 8),
        hypothesis.strategies.sampled_from(("", "River", "Cañon")),
        hypothesis.strategies.tuples(
            hypothesis.strategies.integers(-2, 2).map(float),
            hypothesis.strategies.integers(-2, 2).map(float),
        ),
    )
    existing = draw(
        hypothesis.strategies.lists(row, unique_by=operator.itemgetter(0), max_size=9),
    )
    fetched_row = (
        hypothesis.strategies.one_of(hypothesis.strategies.sampled_from(existing), row)
        if existing
        else row
    )
    fetched = draw(
        hypothesis.strategies.lists(
            fetched_row,
            unique_by=operator.itemgetter(0),
            max_size=9,
        ),
    )
    return existing, fetched
