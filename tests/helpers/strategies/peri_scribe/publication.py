"""Generate publication examples with constrained domains."""

from __future__ import annotations

import datetime
import typing

import hypothesis.strategies

import tests.helpers.factories.peri_scribe.publication


if typing.TYPE_CHECKING:
    import peri_scribe.publication


@hypothesis.strategies.composite
def mapping_decision_cases(
    draw: hypothesis.strategies.DrawFn,
) -> tuple[
    list[tests.helpers.factories.peri_scribe.publication.MappingComparison],
    int,
]:
    """Generate competing changes, missing measurements, and exact threshold boundaries.

    Args:
        draw: The current example's strategy sampler.

    Returns:
        Independent per-fire observations and a positive threshold measured in acres.
    """
    acreage = hypothesis.strategies.one_of(
        hypothesis.strategies.none(),
        hypothesis.strategies.integers(0, 10_000),
    )
    comparisons = draw(
        hypothesis.strategies.lists(
            hypothesis.strategies.builds(
                tests.helpers.factories.peri_scribe.publication.MappingComparison,
                current_acres=acreage,
                baseline_acres=acreage,
                current_minutes=hypothesis.strategies.integers(-2, 2),
            ),
            max_size=8,
        ),
    )
    changes = {
        abs(
            item.current_acres
            - ((item.baseline_acres or 0) if item.baseline_present else 0),
        )
        for item in comparisons
        if item.current_acres is not None
        and (not item.baseline_present or item.baseline_acres is not None)
    }
    boundaries = sorted(changes - {0})
    threshold = hypothesis.strategies.integers(1, 10_000)
    if boundaries:
        threshold |= hypothesis.strategies.sampled_from(boundaries)
    return comparisons, draw(threshold)


@hypothesis.strategies.composite
def mapping_snapshots(
    draw: hypothesis.strategies.DrawFn,
) -> dict[str, tuple[peri_scribe.publication.Mapping, ...]]:
    """Exercise alias chains without conflating different geometries or unnamed fires.

    Args:
        draw: The current example's strategy sampler.

    Returns:
        Snapshots with repeated shapes, shared aliases, and varied capture dates.
    """
    rows = draw(
        hypothesis.strategies.lists(
            hypothesis.strategies.tuples(
                hypothesis.strategies.sets(
                    hypothesis.strategies.sampled_from(["a", "b", "c", "d"]),
                    max_size=3,
                ),
                hypothesis.strategies.integers(0, 2),
                hypothesis.strategies.integers(0, 30),
            ),
            max_size=12,
        ),
    )
    measurements = [
        tests.helpers.factories.peri_scribe.publication.mapping(
            100,
            serial=index,
            identifiers=tuple(sorted(identifiers)),
            captured_at=tests.helpers.factories.peri_scribe.publication.NOW
            + datetime.timedelta(days=day),
        ).model_copy(update={"shape": f"shape-{shape}"})
        for index, (identifiers, shape, day) in enumerate(rows)
    ]
    return tests.helpers.factories.peri_scribe.publication.collection(
        *measurements,
    ).mappings
