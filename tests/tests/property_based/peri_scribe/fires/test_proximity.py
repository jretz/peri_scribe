"""Check active-envelope forest coverage against every exact geometric edge."""

from __future__ import annotations

import itertools

import hypothesis
import hypothesis.strategies
import shapely

import peri_scribe.fires.proximity
import tests.helpers.reference.peri_scribe.fires.grouping
import tests.helpers.strategies.peri_scribe.fires.grouping
from measurement_units import units


@hypothesis.given(
    geometries=hypothesis.strategies.lists(
        tests.helpers.strategies.peri_scribe.fires.grouping.local_geometries(),
        min_size=32,
        max_size=60,
    ),
)
@hypothesis.settings(max_examples=40)
def test_spanning_pairs_preserves_exhaustive_components(
    geometries: list[shapely.Geometry],
) -> None:
    full = [
        (left, right)
        for left, right in itertools.combinations(range(len(geometries)), 2)
        if shapely.dwithin(geometries[left], geometries[right], 0.05)
    ]
    forest = list(
        peri_scribe.fires.proximity.spanning_pairs(
            geometries,
            tolerance=0.05 * units.degrees,
        ),
    )
    assert set(forest) | {(right, left) for left, right in forest} <= (
        set(full) | {(right, left) for left, right in full}
    )
    assert tests.helpers.reference.peri_scribe.fires.grouping.edge_groups(
        len(geometries),
        forest,
    ) == tests.helpers.reference.peri_scribe.fires.grouping.edge_groups(
        len(geometries),
        full,
    )
