"""Tests for peri_scribe.fires.scores."""

from __future__ import annotations

import datetime
import json

import pytest

import peri_scribe.fires.scoring
import peri_scribe.models
import tests.peri_scribe.fires.fire_helpers


def test_tiered_points_returns_zero_for_missing() -> None:
    assert peri_scribe.fires.scoring.tiered_points(None, ((10.0, 1),)) == 0


def test_tiered_points_returns_zero_when_no_tier_is_met() -> None:
    assert peri_scribe.fires.scoring.tiered_points(3.0, ((100.0, 5), (10.0, 1))) == 0


def test_tiered_points_returns_first_met_tier() -> None:
    assert peri_scribe.fires.scoring.tiered_points(50.0, ((100.0, 5), (10.0, 1))) == 1


def test_tiered_points_meets_exact_threshold() -> None:
    assert peri_scribe.fires.scoring.tiered_points(
        100.0,
        ((100.0, 5), (10.0, 1)),
    ) == pytest.approx(5)


def test_importance_points_returns_points_for_known_level() -> None:
    assert peri_scribe.fires.scoring.importance_points(
        "Type 2 Incident",
    ) == pytest.approx(2)


def test_importance_points_returns_zero_for_unknown_level() -> None:
    assert peri_scribe.fires.scoring.importance_points("Type 4 Incident") == 0


def test_importance_points_returns_zero_for_missing() -> None:
    assert peri_scribe.fires.scoring.importance_points(None) == 0


def test_complexity_level_reads_level_from_json() -> None:
    assert (
        peri_scribe.fires.scoring.complexity_level(
            json.dumps({"IncidentComplexityLevel": "Type 1 Incident"}),
        )
        == "Type 1 Incident"
    )


def test_complexity_level_returns_none_without_level() -> None:
    assert peri_scribe.fires.scoring.complexity_level(json.dumps({"Other": 1})) is None


def test_complexity_level_returns_none_for_invalid_json() -> None:
    assert peri_scribe.fires.scoring.complexity_level("{not json") is None


def test_complexity_level_returns_none_for_non_object_json() -> None:
    assert peri_scribe.fires.scoring.complexity_level(json.dumps([1, 2])) is None


def test_complexity_level_returns_none_for_missing() -> None:
    assert peri_scribe.fires.scoring.complexity_level(None) is None


def test_fire_importance_points_returns_zero_for_empty() -> None:
    assert (
        peri_scribe.fires.scoring.fire_importance_points(
            tests.peri_scribe.fires.fire_helpers.empty_frame(),
        )
        == 0
    )


def test_fire_importance_points_takes_highest_level() -> None:
    frame = tests.peri_scribe.fires.fire_helpers.point_frame(
        [
            {
                "source_attributes": json.dumps(
                    {"IncidentComplexityLevel": "Type 3 Incident"},
                ),
            },
            {
                "source_attributes": json.dumps(
                    {"IncidentComplexityLevel": "Type 1 Incident"},
                ),
            },
        ],
        [
            tests.peri_scribe.fires.fire_helpers.point(0, 0),
            tests.peri_scribe.fires.fire_helpers.point(1, 1),
        ],
    )
    assert peri_scribe.fires.scoring.fire_importance_points(
        frame,
    ) == pytest.approx(3)


def test_fire_score_total_sums_all_signals() -> None:
    score = peri_scribe.fires.scoring.FireScore(
        name="Bug",
        identifier="2026-a",
        size_points=135,
        growth_points=60,
        first_mapping_points=33,
        building_points=8,
        evacuation_points=33,
        importance_points=120,
    )
    assert score.total == pytest.approx(389)


def test_fire_score_for_combines_all_signals() -> None:
    perimeters = tests.peri_scribe.fires.fire_helpers.perimeter_frame(
        [
            {
                "fire_name": "Bug",
                "fire_identifier": "2026-a",
                "area_acres": 120_000.0,
                "area_acres_differential": 60_000.0,
                "observation_time": datetime.datetime(2026, 8, 1),
            },
        ],
        [tests.peri_scribe.fires.fire_helpers.square(0.01)],
    )
    points = tests.peri_scribe.fires.fire_helpers.point_frame(
        [
            {
                "fire_name": "Bug",
                "fire_identifier": "2026-a",
                "source_attributes": json.dumps(
                    {"IncidentComplexityLevel": "Type 2 Incident"},
                ),
            },
        ],
        [tests.peri_scribe.fires.fire_helpers.point(0, 0)],
    )
    record = peri_scribe.fires.scoring.FireRecords(
        name="Bug",
        identifier="2026-a",
        perimeters=perimeters,
        points=points,
    )
    score = peri_scribe.fires.scoring.fire_score_for(
        record,
        peri_scribe.fires.scoring.PerimeterMetrics(
            area_acres=120_000.0,
            growth_acres=60_000.0,
            first_mapping_acres=120_000.0,
            geometry=None,
        ),
        building_count=5,
        evacuation_overlap=True,
    )
    assert score.size_points == pytest.approx(135)
    assert score.growth_points == pytest.approx(60)
    assert score.first_mapping_points == pytest.approx(33)
    assert score.building_points == pytest.approx(4)
    assert score.evacuation_points == pytest.approx(33)
    assert score.importance_points == pytest.approx(240)
    assert score.total == pytest.approx(505)


def test_fire_score_for_awards_no_overlap_points_without_overlaps() -> None:
    points = tests.peri_scribe.fires.fire_helpers.point_frame(
        [{"fire_name": "Point Only", "fire_identifier": None}],
        [tests.peri_scribe.fires.fire_helpers.point(0, 0)],
    )
    record = peri_scribe.fires.scoring.FireRecords(
        name="Point Only",
        identifier=None,
        perimeters=tests.peri_scribe.fires.fire_helpers.perimeter_frame([], []),
        points=points,
    )
    score = peri_scribe.fires.scoring.fire_score_for(
        record,
        peri_scribe.fires.scoring.PerimeterMetrics(
            area_acres=None,
            growth_acres=None,
            first_mapping_acres=None,
            geometry=None,
        ),
        building_count=0,
        evacuation_overlap=False,
    )
    assert score.name == "Point Only"
    assert score.identifier is None
    assert score.building_points == 0
    assert score.evacuation_points == 0
    assert score.importance_points == 0


def test_score_entry_maps_components_and_total() -> None:
    fire_score = peri_scribe.fires.scoring.FireScore(
        name="Bug",
        identifier="2026-a",
        size_points=135,
        growth_points=60,
        first_mapping_points=33,
        building_points=8,
        evacuation_points=33,
        importance_points=120,
    )
    entry = peri_scribe.fires.scoring.score_entry(fire_score)
    assert entry.name == "Bug"
    assert entry.identifier == "2026-a"
    assert entry.score == pytest.approx(389)
    assert entry.components.model_dump() == {
        "size": 135,
        "growth": 60,
        "first_mapping": 33,
        "buildings": 8,
        "evacuation": 33,
        "importance": 120,
    }
    assert entry.explanation == (
        "Over 100,000 acres, a single growth step over "
        "50,000 acres, already over 5,000 acres when first mapped, over "
        "50 structures within a mile, overlap with an evacuation zone, and "
        "a Type 3 Incident."
    )


def test_score_explanation_describes_each_contributing_signal() -> None:
    fire_score = peri_scribe.fires.scoring.FireScore(
        name="Bug",
        identifier="2026-a",
        size_points=27,
        growth_points=15,
        first_mapping_points=11,
        building_points=0,
        evacuation_points=0,
        importance_points=0,
    )
    assert peri_scribe.fires.scoring.score_explanation(fire_score) == (
        "Over 1,000 acres, a single growth step over "
        "5,000 acres, and already over 100 acres when first mapped."
    )


def test_score_explanation_mentions_evacuation_and_importance() -> None:
    fire_score = peri_scribe.fires.scoring.FireScore(
        name="Bug",
        identifier="2026-a",
        size_points=0,
        growth_points=0,
        first_mapping_points=0,
        building_points=0,
        evacuation_points=33,
        importance_points=360,
    )
    assert peri_scribe.fires.scoring.score_explanation(fire_score) == (
        "Overlap with an evacuation zone, and a Type 1 Incident."
    )


def test_score_explanation_says_no_signals_when_score_is_zero() -> None:
    fire_score = peri_scribe.fires.scoring.FireScore(
        name="Bug",
        identifier="2026-a",
        size_points=0,
        growth_points=0,
        first_mapping_points=0,
        building_points=0,
        evacuation_points=0,
        importance_points=0,
    )
    assert peri_scribe.fires.scoring.score_explanation(fire_score) == (
        "No notable size, growth, threat, or official-importance signals."
    )


def test_signal_description_returns_none_without_points() -> None:
    assert (
        peri_scribe.fires.scoring.signal_description(
            0,
            peri_scribe.fires.scoring.SIZE_WEIGHT,
            peri_scribe.fires.scoring.SIZE_DESCRIPTIONS,
        )
        is None
    )


def test_signal_description_names_the_tier() -> None:
    assert (
        peri_scribe.fires.scoring.signal_description(
            4 * peri_scribe.fires.scoring.BUILDINGS_WEIGHT,
            peri_scribe.fires.scoring.BUILDINGS_WEIGHT,
            peri_scribe.fires.scoring.BUILDING_COUNT_DESCRIPTIONS,
        )
        == "over 1,000 structures within a mile"
    )


def test_fire_scores_document_wraps_entries_with_version() -> None:
    entry = peri_scribe.models.FireScoreEntry(
        name="Bug",
        identifier=None,
        score=5,
        components=peri_scribe.models.FireScoreComponents(
            size=5,
            growth=0,
            first_mapping=0,
            buildings=0,
            evacuation=0,
            importance=0,
        ),
        explanation="Over 1,000 acres.",
    )
    document = peri_scribe.fires.scoring.fire_scores_document([entry])
    assert document.version == peri_scribe.fires.scoring.FIRE_SCORES_VERSION
    assert document.fires == [entry]
