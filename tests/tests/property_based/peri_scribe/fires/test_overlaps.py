"""Tests for peri_scribe.fires.overlaps."""

from __future__ import annotations

import hypothesis
import hypothesis.strategies
import numpy as np
import shapely.geometry

import peri_scribe.fires.overlaps
import tests.helpers.strategies.geometry


@hypothesis.given(
    fires=hypothesis.strategies.lists(
        tests.helpers.strategies.geometry.local_shapes(),
        max_size=12,
    ),
    candidates=hypothesis.strategies.lists(
        hypothesis.strategies.one_of(
            hypothesis.strategies.none(),
            hypothesis.strategies.just(shapely.Polygon()),
            tests.helpers.strategies.geometry.local_shapes(),
        ),
        max_size=12,
    ),
    data=hypothesis.strategies.data(),
)
def test_overlapping_indices_matches_exhaustive_intersections(
    fires: list[shapely.Geometry],
    candidates: list[shapely.Geometry | None],
    data: hypothesis.strategies.DataObject,
) -> None:
    indices = data.draw(
        hypothesis.strategies.lists(
            hypothesis.strategies.integers(0, 100),
            min_size=len(fires),
            max_size=len(fires),
            unique=True,
        ),
    )
    expected = {
        index
        for index, fire in zip(indices, fires, strict=True)
        if any(
            candidate is not None and fire.intersects(candidate)
            for candidate in candidates
        )
    }
    tree_geometries = np.asarray(fires, dtype=object)
    assert (
        peri_scribe.fires.overlaps.overlapping_indices(
            np.asarray(candidates, dtype=object),
            shapely.STRtree(tree_geometries),
            tree_geometries,
            list(zip(indices, fires, strict=True)),
        )
        == expected
    )
