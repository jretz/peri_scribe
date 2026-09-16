"""Verify fire identities, complex membership, and model validation."""

from __future__ import annotations

import datetime

import hypothesis
import hypothesis.strategies

import peri_scribe.models
import tests.helpers.strategies.peri_scribe.models


@hypothesis.given(
    identifiers=tests.helpers.strategies.peri_scribe.models.identifier_collections(),
)
def test_canonical_fire_identifier_accepts_single_pass_iterators(
    identifiers: list[str],
) -> None:
    assert peri_scribe.models.canonical_fire_identifier(iter(identifiers)) == (
        peri_scribe.models.canonical_fire_identifier(identifiers)
    )


@hypothesis.given(
    scenario=tests.helpers.strategies.peri_scribe.models.clock_change_comparisons(),
)
def test_times_are_contemporaneous_is_independent_of_time_zone_representation(
    scenario: tuple[datetime.datetime, datetime.datetime, datetime.timedelta],
) -> None:
    left, right, tolerance = scenario
    expected = peri_scribe.models.times_are_contemporaneous(
        left.astimezone(datetime.UTC),
        right.astimezone(datetime.UTC),
        tolerance,
    )
    assert (
        peri_scribe.models.times_are_contemporaneous(left, right, tolerance) == expected
    )


@hypothesis.given(name=hypothesis.infer)
def test_normalize_fire_name_is_idempotent(name: str) -> None:
    normalized = peri_scribe.models.normalize_fire_name(name)
    assert peri_scribe.models.normalize_fire_name(normalized) == normalized


@hypothesis.given(
    identifiers=hypothesis.strategies.lists(hypothesis.strategies.text(), max_size=20),
    data=hypothesis.strategies.data(),
)
def test_canonical_fire_identifier_ignores_order_and_duplicates(
    identifiers: list[str],
    data: hypothesis.strategies.DataObject,
) -> None:
    reordered = data.draw(hypothesis.strategies.permutations(identifiers))
    assert peri_scribe.models.canonical_fire_identifier(
        [*reordered, *identifiers],
    ) == peri_scribe.models.canonical_fire_identifier(identifiers)
