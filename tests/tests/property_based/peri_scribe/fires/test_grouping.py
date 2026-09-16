"""Tests for peri_scribe.fires.grouping."""

from __future__ import annotations

import typing

import hypothesis
import hypothesis.strategies

import peri_scribe.fires.grouping
import peri_scribe.models
import tests.helpers.reference.peri_scribe.fires.grouping
import tests.helpers.strategies.peri_scribe.fires.grouping


if typing.TYPE_CHECKING:
    import shapely.geometry


@hypothesis.given(
    records=tests.helpers.strategies.peri_scribe.fires.grouping.fire_records(),
)
def test_group_fire_record_indices_matches_connected_components(
    records: list[peri_scribe.models.FireRecord],
) -> None:
    assert peri_scribe.fires.grouping.group_fire_record_indices(records) == (
        tests.helpers.reference.peri_scribe.fires.grouping.reference_groups(records)
    )


@hypothesis.given(
    records=tests.helpers.strategies.peri_scribe.fires.grouping.fire_records(),
    data=hypothesis.strategies.data(),
)
def test_group_fire_record_indices_preserves_membership_under_permutation(
    records: list[peri_scribe.models.FireRecord],
    data: hypothesis.strategies.DataObject,
) -> None:
    permutation = data.draw(hypothesis.strategies.permutations(range(len(records))))
    original = peri_scribe.fires.grouping.group_fire_record_indices(records)
    reordered = peri_scribe.fires.grouping.group_fire_record_indices([
        records[index] for index in permutation
    ])
    assert {frozenset(group) for group in original} == {
        frozenset(permutation[index] for index in group) for group in reordered
    }


@hypothesis.given(
    geometries=hypothesis.strategies.lists(
        tests.helpers.strategies.peri_scribe.fires.grouping.local_geometries(),
        max_size=15,
    ),
)
def test_matched_within_outlier_tolerance_matches_exhaustive_comparisons(
    geometries: list[shapely.Geometry],
) -> None:
    tolerance = peri_scribe.fires.grouping.FIRE_OUTLIER_TOLERANCE.m_as("degrees")
    expected = {
        index
        for index, geometry in enumerate(geometries)
        if any(
            index != other_index and geometry.distance(other) <= tolerance
            for other_index, other in enumerate(geometries)
        )
    }
    assert (
        peri_scribe.fires.grouping.matched_within_outlier_tolerance(
            list(enumerate(geometries)),
        )
        == expected
    )
