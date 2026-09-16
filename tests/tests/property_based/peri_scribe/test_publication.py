"""Publication decisions must survive skipped downloads and failed output writes."""

from __future__ import annotations

import datetime

import hypothesis
import hypothesis.strategies
import pytest

import peri_scribe.publication
import tests.helpers.factories.peri_scribe.publication
import tests.helpers.reference.peri_scribe.publication
import tests.helpers.strategies.peri_scribe.publication
from peri_scribe.units import units


@hypothesis.given(
    case=tests.helpers.strategies.peri_scribe.publication.mapping_decision_cases(),
    area_unit=hypothesis.strategies.sampled_from(["acres", "hectares", "meters ** 2"]),
)
def test_mapping_decision_matches_the_largest_eligible_absolute_change(
    case: tuple[
        list[tests.helpers.factories.peri_scribe.publication.MappingComparison],
        int,
    ],
    area_unit: str,
) -> None:
    comparisons, threshold_acres = case
    decision = peri_scribe.publication.mapping_decision(
        tests.helpers.factories.peri_scribe.publication.mapping_candidates(comparisons),
        peri_scribe.publication.Threshold(
            area=(threshold_acres * units.acres).to(area_unit),
            interval=datetime.timedelta(minutes=5),
        ),
    )
    eligible = {
        f"Fire {index}": item
        for index, item in enumerate(comparisons)
        if not item.baseline_present or item.current_minutes >= 0
    }
    if any(
        item.current_acres is None
        or (item.baseline_present and item.baseline_acres is None)
        for item in eligible.values()
    ):
        assert decision.proceed
        assert decision.reason == peri_scribe.publication.Reason.UNCERTAIN_MAPPING
        return
    changes = {
        name: item.current_acres
        - ((item.baseline_acres or 0) if item.baseline_present else 0)
        for name, item in eligible.items()
        if item.current_acres is not None
        and (not item.baseline_present or item.baseline_acres is not None)
    }
    largest = max(map(abs, changes.values()), default=0)
    assert abs(decision.change.m_as("acres")) == pytest.approx(largest)
    assert decision.proceed == (largest >= threshold_acres)
    assert decision.reason == (
        peri_scribe.publication.Reason.AREA
        if largest >= threshold_acres
        else peri_scribe.publication.Reason.BELOW_THRESHOLD
    )
    if largest:
        assert decision.fire in changes
        assert abs(changes[decision.fire]) == largest
        assert decision.change.m_as("acres") == pytest.approx(changes[decision.fire])
    else:
        assert decision.fire is None


@hypothesis.given(
    snapshots=tests.helpers.strategies.peri_scribe.publication.mapping_snapshots(),
)
def test_first_captures_is_idempotent(
    snapshots: dict[str, tuple[peri_scribe.publication.Mapping, ...]],
) -> None:
    once = peri_scribe.publication.first_captures(snapshots)
    assert peri_scribe.publication.first_captures(once) == once


@hypothesis.given(
    snapshots=tests.helpers.strategies.peri_scribe.publication.mapping_snapshots(),
)
def test_first_captures_matches_earliest_connected_alias_capture(
    snapshots: dict[str, tuple[peri_scribe.publication.Mapping, ...]],
) -> None:
    measurements = [item for mappings in snapshots.values() for item in mappings]
    expected = {
        path: tuple(
            item.model_copy(
                update={
                    "captured_at": (
                        tests.helpers.reference.peri_scribe.publication.earliest_linked_capture(
                            item,
                            measurements,
                        )
                    ),
                },
            )
            for item in mappings
        )
        for path, mappings in snapshots.items()
    }
    assert peri_scribe.publication.first_captures(snapshots) == expected
