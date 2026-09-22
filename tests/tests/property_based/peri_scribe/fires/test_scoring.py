"""Tests for peri_scribe.fires.scores."""

from __future__ import annotations

import hypothesis
import hypothesis.strategies
import pytest

import peri_scribe.fires.scoring
from measurement_units import units


@hypothesis.given(
    first=hypothesis.strategies.integers(0, 1_000_000),
    second=hypothesis.strategies.integers(0, 1_000_000),
    tiers=hypothesis.strategies.sampled_from((
        peri_scribe.fires.scoring.SIZE_TIERS,
        peri_scribe.fires.scoring.GROWTH_TIERS,
        peri_scribe.fires.scoring.FIRST_MAPPING_TIERS,
        peri_scribe.fires.scoring.BUILDING_COUNT_TIERS,
    )),
)
def test_tiered_points_never_decreases_for_increasing_signal(
    first: int,
    second: int,
    tiers: tuple[peri_scribe.fires.scoring.SignalTier, ...],
) -> None:
    smaller, larger = sorted((first, second))
    assert peri_scribe.fires.scoring.tiered_points(
        smaller,
        tiers,
    ) <= peri_scribe.fires.scoring.tiered_points(larger, tiers)


@hypothesis.given(
    value=hypothesis.strategies.floats(0, 1_000_000),
    unit=hypothesis.strategies.sampled_from(("meters**2", "hectares", "acres")),
)
def test_acre_magnitude_is_independent_of_area_units(value: float, unit: str) -> None:
    quantity = (value * units.acres).to(unit)
    assert peri_scribe.fires.scoring.acre_magnitude(quantity) == pytest.approx(value)
