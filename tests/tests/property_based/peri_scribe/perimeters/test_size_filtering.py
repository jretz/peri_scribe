"""Tests for peri_scribe.perimeters.size_filtering."""

from __future__ import annotations

import hypothesis
import hypothesis.strategies

import peri_scribe.perimeters.size_filtering
from peri_scribe.units import units


@hypothesis.given(
    measured=hypothesis.strategies.integers(0, 1_000_000),
    computed=hypothesis.strategies.integers(0, 10_000_000),
    incident=hypothesis.strategies.integers(0, 10_000_000),
    area_unit=hypothesis.strategies.sampled_from(("hectares", "meters ** 2")),
)
def test_area_is_implausibly_small_is_unit_independent(
    measured: int,
    computed: int,
    incident: int,
    area_unit: str,
) -> None:
    area = measured * units.acres
    attributes: dict[str, object] = {
        "area_acres": computed,
        "attr_IncidentSize": incident,
    }
    assert peri_scribe.perimeters.size_filtering.area_is_implausibly_small(
        area.to(area_unit),
        attributes,
    ) == peri_scribe.perimeters.size_filtering.area_is_implausibly_small(
        area,
        attributes,
    )


@hypothesis.given(
    measured=hypothesis.strategies.integers(0, 1_000_000),
    growth=hypothesis.strategies.integers(0, 1_000_000),
    computed=hypothesis.strategies.integers(0, 10_000_000),
    incident=hypothesis.strategies.integers(0, 10_000_000),
)
def test_area_is_implausibly_small_cannot_reject_a_larger_accepted_area(
    measured: int,
    growth: int,
    computed: int,
    incident: int,
) -> None:
    attributes: dict[str, object] = {
        "area_acres": computed,
        "attr_IncidentSize": incident,
    }
    smaller_rejected = peri_scribe.perimeters.size_filtering.area_is_implausibly_small(
        measured * units.acres,
        attributes,
    )
    larger_rejected = peri_scribe.perimeters.size_filtering.area_is_implausibly_small(
        (measured + growth) * units.acres,
        attributes,
    )
    assert smaller_rejected or not larger_rejected
