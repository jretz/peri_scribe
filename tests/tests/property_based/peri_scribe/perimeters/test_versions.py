"""Tests for peri_scribe.perimeters.versions."""

from __future__ import annotations

import dataclasses
import itertools

import hypothesis
import hypothesis.strategies

import peri_scribe.perimeters.versions
import tests.helpers.factories.peri_scribe.perimeters.versions
import tests.helpers.strategies.peri_scribe.perimeters.versions


@hypothesis.given(
    states=tests.helpers.strategies.peri_scribe.perimeters.versions.attribute_histories(),
    data=hypothesis.strategies.data(),
)
def test_point_versions_matches_runs_of_attribute_states(
    states: list[tuple[int | None, int | None]],
    data: hypothesis.strategies.DataObject,
) -> None:
    observations = (
        tests.helpers.factories.peri_scribe.perimeters.versions.point_observations(
            states,
        )
    )
    expected = []
    for _state, group in itertools.groupby(
        range(len(states)),
        key=states.__getitem__,
    ):
        indices = list(group)
        first, last = observations[indices[0]], observations[indices[-1]]
        expected.append(
            dataclasses.replace(
                last,
                observation_time=first.observation_time,
                attributes=first.attributes,
            ),
        )
    reordered = data.draw(hypothesis.strategies.permutations(observations))
    assert peri_scribe.perimeters.versions.point_versions(reordered) == expected


@hypothesis.given(
    states=tests.helpers.strategies.peri_scribe.perimeters.versions.attribute_histories(),
)
def test_point_versions_is_idempotent(
    states: list[tuple[int | None, int | None]],
) -> None:
    observations = (
        tests.helpers.factories.peri_scribe.perimeters.versions.point_observations(
            states,
        )
    )
    versions = peri_scribe.perimeters.versions.point_versions(observations)
    assert peri_scribe.perimeters.versions.point_versions(versions) == versions


@hypothesis.given(
    shapes=hypothesis.strategies.lists(
        hypothesis.strategies.integers(0, 3),
        max_size=20,
    ),
    data=hypothesis.strategies.data(),
)
def test_collapse_identical_consecutive_perimeters_matches_runs_of_shapes(
    shapes: list[int],
    data: hypothesis.strategies.DataObject,
) -> None:
    observations = (
        tests.helpers.factories.peri_scribe.perimeters.versions.perimeter_observations(
            shapes,
        )
    )
    expected = []
    for _shape, group in itertools.groupby(
        range(len(shapes)),
        key=shapes.__getitem__,
    ):
        indices = list(group)
        expected.append(
            dataclasses.replace(
                observations[indices[-1]],
                observation_time=observations[indices[0]].observation_time,
            ),
        )
    reordered = data.draw(hypothesis.strategies.permutations(observations))
    assert (
        peri_scribe.perimeters.versions.collapse_identical_consecutive_perimeters(
            reordered,
        )
        == expected
    )
