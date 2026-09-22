"""Tests for peri_scribe.presentation.folders."""

from __future__ import annotations

import datetime

import pytest
import shapely.geometry

import peri_scribe.models
import peri_scribe.presentation.descriptions
import peri_scribe.presentation.fire_data
import peri_scribe.presentation.perimeters
import peri_scribe.presentation.views
import spatial_data.measurements
import tests.helpers.factories.geometry
import tests.helpers.factories.peri_scribe.presentation.views
from measurement_units import units


def test_fire_growth_is_unknown_with_only_future_measurements() -> None:
    now = tests.helpers.factories.peri_scribe.presentation.views.REFERENCE_TIME
    fire = tests.helpers.factories.peri_scribe.presentation.views.active_fire(
        "Future",
        perimeters=(
            peri_scribe.presentation.perimeters.Perimeter(
                geometry=tests.helpers.factories.geometry.square(0.01),
                observation_time=now + datetime.timedelta(hours=1),
                area=0 * units.acres,
            ),
        ),
    )
    assert peri_scribe.presentation.views.fire_growth(fire, now) == (None, None)


def test_fire_growth_ignores_a_future_increase() -> None:
    now = tests.helpers.factories.peri_scribe.presentation.views.REFERENCE_TIME
    fire = tests.helpers.factories.peri_scribe.presentation.views.active_fire(
        "Current",
        perimeters=(
            peri_scribe.presentation.perimeters.Perimeter(
                geometry=tests.helpers.factories.geometry.square(0.01),
                observation_time=now,
                area=0 * units.acres,
            ),
            peri_scribe.presentation.perimeters.Perimeter(
                geometry=tests.helpers.factories.geometry.square(0.01),
                observation_time=now + datetime.timedelta(hours=1),
                area=1 * units.acres,
            ),
        ),
    )
    growth, percent = peri_scribe.presentation.views.fire_growth(fire, now)
    assert growth == 0 * units.acres
    assert percent is None


def test_top_fires_matches_by_identifier() -> None:
    big = peri_scribe.presentation.fire_data.FireSummary(
        name="Timber",
        status=peri_scribe.models.FireStatus.ACTIVE,
        point=None,
        perimeters=(),
        identifiers=frozenset({"id-big", "alias-big"}),
    )
    small = peri_scribe.presentation.fire_data.FireSummary(
        name="Timber",
        status=peri_scribe.models.FireStatus.INACTIVE,
        point=None,
        perimeters=(),
        identifiers=frozenset({"id-small"}),
    )
    scores = peri_scribe.models.FireScores(
        version="test",
        fires=[
            tests.helpers.factories.peri_scribe.presentation.views.score_entry(
                "Timber",
                "id-small",
                4,
                "Over 5 structures within a mile.",
            ),
            tests.helpers.factories.peri_scribe.presentation.views.score_entry(
                "Timber",
                "id-big",
                470,
                "Over 250 structures within a mile.",
            ),
        ],
    )
    assert peri_scribe.presentation.views.top_fires([big, small], scores) == [
        big,
        small,
    ]


def test_top_fires_matches_any_fire_identifier() -> None:
    fire = peri_scribe.presentation.fire_data.FireSummary(
        name="Timber",
        status=peri_scribe.models.FireStatus.ACTIVE,
        point=None,
        perimeters=(),
        identifiers=frozenset({"alias-big", "id-big"}),
    )
    scores = peri_scribe.models.FireScores(
        version="test",
        fires=[
            tests.helpers.factories.peri_scribe.presentation.views.score_entry(
                "Timber",
                "id-big",
                470,
                "Over 250 structures within a mile.",
            ),
        ],
    )
    assert peri_scribe.presentation.views.top_fires([fire], scores) == [fire]


def test_top_fires_falls_back_to_name_without_identifier_match() -> None:
    fire = peri_scribe.presentation.fire_data.FireSummary(
        name="Bug",
        status=peri_scribe.models.FireStatus.ACTIVE,
        point=None,
        perimeters=(),
    )
    scores = peri_scribe.models.FireScores(
        version="test",
        fires=[
            tests.helpers.factories.peri_scribe.presentation.views.score_entry(
                "Bug",
                None,
                12,
                "A Type 1 Incident.",
            ),
        ],
    )
    assert peri_scribe.presentation.views.top_fires([fire], scores) == [fire]


def test_top_fires_excludes_scores_without_matching_fire() -> None:
    fire = peri_scribe.presentation.fire_data.FireSummary(
        name="Bug",
        status=peri_scribe.models.FireStatus.ACTIVE,
        point=None,
        perimeters=(),
        identifiers=frozenset({"id-bug"}),
    )
    scores = peri_scribe.models.FireScores(
        version="test",
        fires=[
            tests.helpers.factories.peri_scribe.presentation.views.score_entry(
                "Missing",
                "id-missing",
                500,
                "A Type 1 Incident.",
            ),
        ],
    )
    assert peri_scribe.presentation.views.top_fires([fire], scores) == []


def test_score_maps_partitions_entries_by_identity() -> None:
    identified = tests.helpers.factories.peri_scribe.presentation.views.score_entry(
        "Timber",
        "id-big",
        470,
        "Large.",
    )
    named = tests.helpers.factories.peri_scribe.presentation.views.score_entry(
        "Bug",
        None,
        12,
        "A Type 1 Incident.",
    )
    scores = peri_scribe.models.FireScores(version="test", fires=[identified, named])

    by_identifier, by_name = peri_scribe.presentation.views.score_maps(scores)

    assert by_identifier == {"id-big": identified}
    assert by_name == {"Bug": named}


def test_score_value_for_fire_matches_by_identifier() -> None:
    identified = tests.helpers.factories.peri_scribe.presentation.views.score_entry(
        "Timber",
        "id-big",
        470,
        "Large.",
    )
    scores = peri_scribe.models.FireScores(version="test", fires=[identified])
    by_identifier, by_name = peri_scribe.presentation.views.score_maps(scores)
    fire = tests.helpers.factories.peri_scribe.presentation.views.active_fire(
        "Timber",
        identifiers=frozenset({"id-big", "alias-big"}),
    )

    assert (
        peri_scribe.presentation.views.score_value_for_fire(
            fire,
            by_identifier,
            by_name,
        )
        == identified.score
    )


def test_score_value_for_fire_falls_back_to_name() -> None:
    named = tests.helpers.factories.peri_scribe.presentation.views.score_entry(
        "Bug",
        None,
        12,
        "A Type 1 Incident.",
    )
    scores = peri_scribe.models.FireScores(version="test", fires=[named])
    by_identifier, by_name = peri_scribe.presentation.views.score_maps(scores)
    fire = tests.helpers.factories.peri_scribe.presentation.views.active_fire("Bug")

    assert (
        peri_scribe.presentation.views.score_value_for_fire(
            fire,
            by_identifier,
            by_name,
        )
        == named.score
    )


def test_score_value_for_fire_returns_none_without_match() -> None:
    named = tests.helpers.factories.peri_scribe.presentation.views.score_entry(
        "Bug",
        None,
        12,
        "A Type 1 Incident.",
    )
    scores = peri_scribe.models.FireScores(version="test", fires=[named])
    by_identifier, by_name = peri_scribe.presentation.views.score_maps(scores)
    fire = tests.helpers.factories.peri_scribe.presentation.views.active_fire(
        "Missing",
        identifiers=frozenset({"id-missing"}),
    )

    assert (
        peri_scribe.presentation.views.score_value_for_fire(
            fire,
            by_identifier,
            by_name,
        )
        is None
    )


def test_notable_score_threshold_uses_top_fraction() -> None:
    fires = [
        tests.helpers.factories.peri_scribe.presentation.views.active_fire(
            f"Fire {index}",
        )
        for index in range(10)
    ]
    scores = peri_scribe.models.FireScores(
        version="test",
        fires=[
            tests.helpers.factories.peri_scribe.presentation.views.score_entry(
                f"Fire {index}",
                None,
                index + 1,
                "Notable.",
            )
            for index in range(10)
        ],
    )
    # Ten fires keep the highest-scoring fifth, so the cutoff is the second-highest
    # score.
    expected_threshold = sorted((entry.score for entry in scores.fires), reverse=True)[
        1
    ]
    assert (
        peri_scribe.presentation.views.notable_score_threshold(fires, scores)
        == expected_threshold
    )


def test_notable_score_threshold_ignores_inactive_fires() -> None:
    fire = peri_scribe.presentation.fire_data.FireSummary(
        name="Old",
        status=peri_scribe.models.FireStatus.INACTIVE,
        point=None,
        perimeters=(),
    )
    scores = peri_scribe.models.FireScores(
        version="test",
        fires=[
            tests.helpers.factories.peri_scribe.presentation.views.score_entry(
                "Old",
                None,
                500,
                "A Type 1 Incident.",
            ),
        ],
    )

    assert (
        peri_scribe.presentation.views.notable_score_threshold([fire], scores) is None
    )


def test_notable_score_threshold_returns_none_without_active_score() -> None:
    fire = tests.helpers.factories.peri_scribe.presentation.views.active_fire(
        "Unscored",
    )
    scores = peri_scribe.models.FireScores(version="test", fires=[])

    assert (
        peri_scribe.presentation.views.notable_score_threshold([fire], scores) is None
    )


def test_new_notable_fires_returns_empty_without_reference_time() -> None:
    fire = tests.helpers.factories.peri_scribe.presentation.views.active_fire(
        "New",
        description=peri_scribe.presentation.descriptions.FireDescription(
            discovery_time=tests.helpers.factories.peri_scribe.presentation.views.REFERENCE_TIME,
        ),
    )
    scores = peri_scribe.models.FireScores(
        version="test",
        fires=[
            tests.helpers.factories.peri_scribe.presentation.views.score_entry(
                "New",
                None,
                10,
                "Notable.",
            ),
        ],
    )

    assert peri_scribe.presentation.views.new_notable_fires([fire], scores, None) == []


def test_new_notable_fires_returns_empty_without_active_score() -> None:
    fire = tests.helpers.factories.peri_scribe.presentation.views.active_fire(
        "Unscored",
        description=peri_scribe.presentation.descriptions.FireDescription(
            discovery_time=tests.helpers.factories.peri_scribe.presentation.views.REFERENCE_TIME,
        ),
    )
    scores = peri_scribe.models.FireScores(version="test", fires=[])

    assert (
        peri_scribe.presentation.views.new_notable_fires(
            [fire],
            scores,
            tests.helpers.factories.peri_scribe.presentation.views.REFERENCE_TIME,
        )
        == []
    )


def test_new_notable_fires_includes_recent_high_score_fire() -> None:
    fires = [
        tests.helpers.factories.peri_scribe.presentation.views.active_fire(
            f"Fire {index}",
        )
        for index in range(10)
    ]
    scores = peri_scribe.models.FireScores(
        version="test",
        fires=[
            tests.helpers.factories.peri_scribe.presentation.views.score_entry(
                f"Fire {index}",
                None,
                index + 1,
                "Notable.",
            )
            for index in range(10)
        ],
    )
    recent = (
        tests.helpers.factories.peri_scribe.presentation.views.REFERENCE_TIME
        - datetime.timedelta(
            days=1,
        )
    )
    candidate = tests.helpers.factories.peri_scribe.presentation.views.active_fire(
        "New",
        description=peri_scribe.presentation.descriptions.FireDescription(
            discovery_time=recent,
        ),
    )
    scores.fires.append(
        tests.helpers.factories.peri_scribe.presentation.views.score_entry(
            "New",
            None,
            10,
            "Notable.",
        ),
    )
    fires.append(candidate)

    assert peri_scribe.presentation.views.new_notable_fires(
        fires,
        scores,
        tests.helpers.factories.peri_scribe.presentation.views.REFERENCE_TIME,
    ) == [candidate]


def test_new_notable_fires_sorts_by_score_descending() -> None:
    fires = [
        tests.helpers.factories.peri_scribe.presentation.views.active_fire(
            f"Fire {index}",
        )
        for index in range(10)
    ]
    scores = peri_scribe.models.FireScores(
        version="test",
        fires=[
            tests.helpers.factories.peri_scribe.presentation.views.score_entry(
                f"Fire {index}",
                None,
                index + 1,
                "Notable.",
            )
            for index in range(10)
        ],
    )
    recent = (
        tests.helpers.factories.peri_scribe.presentation.views.REFERENCE_TIME
        - datetime.timedelta(
            days=1,
        )
    )
    lower = tests.helpers.factories.peri_scribe.presentation.views.active_fire(
        "Lower",
        description=peri_scribe.presentation.descriptions.FireDescription(
            discovery_time=recent,
        ),
    )
    higher = tests.helpers.factories.peri_scribe.presentation.views.active_fire(
        "Higher",
        description=peri_scribe.presentation.descriptions.FireDescription(
            discovery_time=recent,
        ),
    )
    scores.fires.append(
        tests.helpers.factories.peri_scribe.presentation.views.score_entry(
            "Lower",
            None,
            10,
            "Notable.",
        ),
    )
    scores.fires.append(
        tests.helpers.factories.peri_scribe.presentation.views.score_entry(
            "Higher",
            None,
            12,
            "Notable.",
        ),
    )
    fires.extend([lower, higher])

    assert peri_scribe.presentation.views.new_notable_fires(
        fires,
        scores,
        tests.helpers.factories.peri_scribe.presentation.views.REFERENCE_TIME,
    ) == [higher, lower]


def test_new_notable_fires_excludes_stale_discovery() -> None:
    fires = [
        tests.helpers.factories.peri_scribe.presentation.views.active_fire(
            f"Fire {index}",
        )
        for index in range(10)
    ]
    scores = peri_scribe.models.FireScores(
        version="test",
        fires=[
            tests.helpers.factories.peri_scribe.presentation.views.score_entry(
                f"Fire {index}",
                None,
                index + 1,
                "Notable.",
            )
            for index in range(10)
        ],
    )
    stale = (
        tests.helpers.factories.peri_scribe.presentation.views.REFERENCE_TIME
        - datetime.timedelta(
            days=6,
        )
    )
    candidate = tests.helpers.factories.peri_scribe.presentation.views.active_fire(
        "Old",
        description=peri_scribe.presentation.descriptions.FireDescription(
            discovery_time=stale,
        ),
    )
    scores.fires.append(
        tests.helpers.factories.peri_scribe.presentation.views.score_entry(
            "Old",
            None,
            20,
            "Notable.",
        ),
    )
    fires.append(candidate)

    assert (
        peri_scribe.presentation.views.new_notable_fires(
            fires,
            scores,
            tests.helpers.factories.peri_scribe.presentation.views.REFERENCE_TIME,
        )
        == []
    )


def test_new_notable_fires_excludes_future_discovery() -> None:
    fires = [
        tests.helpers.factories.peri_scribe.presentation.views.active_fire(
            f"Fire {index}",
        )
        for index in range(10)
    ]
    scores = peri_scribe.models.FireScores(
        version="test",
        fires=[
            tests.helpers.factories.peri_scribe.presentation.views.score_entry(
                f"Fire {index}",
                None,
                index + 1,
                "Notable.",
            )
            for index in range(10)
        ],
    )
    future = (
        tests.helpers.factories.peri_scribe.presentation.views.REFERENCE_TIME
        + datetime.timedelta(
            hours=1,
        )
    )
    candidate = tests.helpers.factories.peri_scribe.presentation.views.active_fire(
        "Future",
        description=peri_scribe.presentation.descriptions.FireDescription(
            discovery_time=future,
        ),
    )
    scores.fires.append(
        tests.helpers.factories.peri_scribe.presentation.views.score_entry(
            "Future",
            None,
            20,
            "Notable.",
        ),
    )
    fires.append(candidate)

    assert (
        peri_scribe.presentation.views.new_notable_fires(
            fires,
            scores,
            tests.helpers.factories.peri_scribe.presentation.views.REFERENCE_TIME,
        )
        == []
    )


def test_new_notable_fires_excludes_missing_description() -> None:
    fires = [
        tests.helpers.factories.peri_scribe.presentation.views.active_fire(
            f"Fire {index}",
        )
        for index in range(10)
    ]
    scores = peri_scribe.models.FireScores(
        version="test",
        fires=[
            tests.helpers.factories.peri_scribe.presentation.views.score_entry(
                f"Fire {index}",
                None,
                index + 1,
                "Notable.",
            )
            for index in range(10)
        ],
    )
    candidate = tests.helpers.factories.peri_scribe.presentation.views.active_fire(
        "NoDescription",
    )
    scores.fires.append(
        tests.helpers.factories.peri_scribe.presentation.views.score_entry(
            "NoDescription",
            None,
            20,
            "Notable.",
        ),
    )
    fires.append(candidate)

    assert (
        peri_scribe.presentation.views.new_notable_fires(
            fires,
            scores,
            tests.helpers.factories.peri_scribe.presentation.views.REFERENCE_TIME,
        )
        == []
    )


def test_new_notable_fires_excludes_missing_discovery_time() -> None:
    fires = [
        tests.helpers.factories.peri_scribe.presentation.views.active_fire(
            f"Fire {index}",
        )
        for index in range(10)
    ]
    scores = peri_scribe.models.FireScores(
        version="test",
        fires=[
            tests.helpers.factories.peri_scribe.presentation.views.score_entry(
                f"Fire {index}",
                None,
                index + 1,
                "Notable.",
            )
            for index in range(10)
        ],
    )
    candidate = tests.helpers.factories.peri_scribe.presentation.views.active_fire(
        "NoDiscovery",
        description=peri_scribe.presentation.descriptions.FireDescription(),
    )
    scores.fires.append(
        tests.helpers.factories.peri_scribe.presentation.views.score_entry(
            "NoDiscovery",
            None,
            20,
            "Notable.",
        ),
    )
    fires.append(candidate)

    assert (
        peri_scribe.presentation.views.new_notable_fires(
            fires,
            scores,
            tests.helpers.factories.peri_scribe.presentation.views.REFERENCE_TIME,
        )
        == []
    )


def test_new_notable_fires_excludes_below_threshold() -> None:
    fires = [
        tests.helpers.factories.peri_scribe.presentation.views.active_fire(
            f"Fire {index}",
        )
        for index in range(10)
    ]
    scores = peri_scribe.models.FireScores(
        version="test",
        fires=[
            tests.helpers.factories.peri_scribe.presentation.views.score_entry(
                f"Fire {index}",
                None,
                index + 1,
                "Notable.",
            )
            for index in range(10)
        ],
    )
    recent = (
        tests.helpers.factories.peri_scribe.presentation.views.REFERENCE_TIME
        - datetime.timedelta(
            days=1,
        )
    )
    candidate = tests.helpers.factories.peri_scribe.presentation.views.active_fire(
        "Low",
        description=peri_scribe.presentation.descriptions.FireDescription(
            discovery_time=recent,
        ),
    )
    scores.fires.append(
        tests.helpers.factories.peri_scribe.presentation.views.score_entry(
            "Low",
            None,
            5,
            "Notable.",
        ),
    )
    fires.append(candidate)

    assert (
        peri_scribe.presentation.views.new_notable_fires(
            fires,
            scores,
            tests.helpers.factories.peri_scribe.presentation.views.REFERENCE_TIME,
        )
        == []
    )


def test_new_notable_fires_excludes_unscored_fire() -> None:
    fires = [
        tests.helpers.factories.peri_scribe.presentation.views.active_fire(
            f"Fire {index}",
        )
        for index in range(10)
    ]
    scores = peri_scribe.models.FireScores(
        version="test",
        fires=[
            tests.helpers.factories.peri_scribe.presentation.views.score_entry(
                f"Fire {index}",
                None,
                index + 1,
                "Notable.",
            )
            for index in range(10)
        ],
    )
    recent = (
        tests.helpers.factories.peri_scribe.presentation.views.REFERENCE_TIME
        - datetime.timedelta(
            days=1,
        )
    )
    candidate = tests.helpers.factories.peri_scribe.presentation.views.active_fire(
        "Unscored",
        description=peri_scribe.presentation.descriptions.FireDescription(
            discovery_time=recent,
        ),
    )
    fires.append(candidate)

    assert (
        peri_scribe.presentation.views.new_notable_fires(
            fires,
            scores,
            tests.helpers.factories.peri_scribe.presentation.views.REFERENCE_TIME,
        )
        == []
    )


def test_new_notable_signals_qualify_by_size() -> None:
    entry = tests.helpers.factories.peri_scribe.presentation.views.score_entry(
        "Big",
        None,
        5,
        "Over 1,000 acres.",
        area=1_500.0,
    )
    assert peri_scribe.presentation.views.new_notable_signals_qualify(entry)


def test_new_notable_signals_qualify_by_evacuation() -> None:
    entry = tests.helpers.factories.peri_scribe.presentation.views.score_entry(
        "Zone",
        None,
        5,
        "Overlap with an evacuation zone.",
        area=150.0,
        evacuation_overlap=True,
    )
    assert peri_scribe.presentation.views.new_notable_signals_qualify(entry)


def test_new_notable_signals_qualify_by_buildings() -> None:
    entry = tests.helpers.factories.peri_scribe.presentation.views.score_entry(
        "Near",
        None,
        5,
        "Over 100 structures within a mile.",
        area=150.0,
        building_count=100,
    )
    assert peri_scribe.presentation.views.new_notable_signals_qualify(entry)


def test_new_notable_signals_qualify_requires_minimum_area() -> None:
    entry = tests.helpers.factories.peri_scribe.presentation.views.score_entry(
        "Small",
        None,
        5,
        "Over 100 structures within a mile.",
        area=99.0,
        building_count=100,
    )
    assert not peri_scribe.presentation.views.new_notable_signals_qualify(entry)


def test_new_notable_signals_qualify_requires_known_area() -> None:
    entry = tests.helpers.factories.peri_scribe.presentation.views.score_entry(
        "Unknown",
        None,
        5,
        "Over 100 structures within a mile.",
        building_count=100,
    )
    assert not peri_scribe.presentation.views.new_notable_signals_qualify(entry)


def test_new_notable_fires_includes_fire_qualifying_by_signals() -> None:
    fires = [
        tests.helpers.factories.peri_scribe.presentation.views.active_fire(
            f"Fire {index}",
        )
        for index in range(10)
    ]
    scores = peri_scribe.models.FireScores(
        version="test",
        fires=[
            tests.helpers.factories.peri_scribe.presentation.views.score_entry(
                f"Fire {index}",
                None,
                index + 1,
                "Notable.",
            )
            for index in range(10)
        ],
    )
    recent = (
        tests.helpers.factories.peri_scribe.presentation.views.REFERENCE_TIME
        - datetime.timedelta(
            days=1,
        )
    )
    candidate = tests.helpers.factories.peri_scribe.presentation.views.active_fire(
        "Big",
        description=peri_scribe.presentation.descriptions.FireDescription(
            discovery_time=recent,
        ),
    )
    scores.fires.append(
        tests.helpers.factories.peri_scribe.presentation.views.score_entry(
            "Big",
            None,
            5,
            "Over 1,000 acres.",
            area=1_500.0,
        ),
    )
    fires.append(candidate)

    assert peri_scribe.presentation.views.new_notable_fires(
        fires,
        scores,
        tests.helpers.factories.peri_scribe.presentation.views.REFERENCE_TIME,
    ) == [candidate]


def test_new_notable_fires_excludes_below_minimum_area_by_signals() -> None:
    fires = [
        tests.helpers.factories.peri_scribe.presentation.views.active_fire(
            f"Fire {index}",
        )
        for index in range(10)
    ]
    scores = peri_scribe.models.FireScores(
        version="test",
        fires=[
            tests.helpers.factories.peri_scribe.presentation.views.score_entry(
                f"Fire {index}",
                None,
                index + 1,
                "Notable.",
            )
            for index in range(10)
        ],
    )
    recent = (
        tests.helpers.factories.peri_scribe.presentation.views.REFERENCE_TIME
        - datetime.timedelta(
            days=1,
        )
    )
    candidate = tests.helpers.factories.peri_scribe.presentation.views.active_fire(
        "Tiny",
        description=peri_scribe.presentation.descriptions.FireDescription(
            discovery_time=recent,
        ),
    )
    scores.fires.append(
        tests.helpers.factories.peri_scribe.presentation.views.score_entry(
            "Tiny",
            None,
            5,
            "Over 100 structures within a mile.",
            area=50.0,
            building_count=300,
        ),
    )
    fires.append(candidate)

    assert (
        peri_scribe.presentation.views.new_notable_fires(
            fires,
            scores,
            tests.helpers.factories.peri_scribe.presentation.views.REFERENCE_TIME,
        )
        == []
    )


def test_type_one_fires_includes_active_type_one_fires_sorted_by_name() -> None:
    zulu = tests.helpers.factories.peri_scribe.presentation.views.type_one_fire("Zulu")
    alpha = tests.helpers.factories.peri_scribe.presentation.views.type_one_fire(
        "alpha",
    )

    assert peri_scribe.presentation.views.type_one_fires([zulu, alpha]) == [alpha, zulu]


def test_type_one_fires_excludes_inactive_fire() -> None:
    done = tests.helpers.factories.peri_scribe.presentation.views.type_one_fire(
        "Done",
        active=False,
    )

    assert peri_scribe.presentation.views.type_one_fires([done]) == []


def test_type_one_fires_excludes_unmarked_active_fire() -> None:
    plain = tests.helpers.factories.peri_scribe.presentation.views.active_fire("Plain")

    assert peri_scribe.presentation.views.type_one_fires([plain]) == []


def test_fire_growth_compares_latest_area_with_window_start() -> None:
    fire = tests.helpers.factories.peri_scribe.presentation.views.growing_fire(
        "Grower",
        0.02,
        0.03,
        tests.helpers.factories.peri_scribe.presentation.views.REFERENCE_TIME,
    )
    baseline = spatial_data.measurements.area(
        tests.helpers.factories.geometry.square(0.02),
    )
    latest = spatial_data.measurements.area(
        tests.helpers.factories.geometry.square(0.03),
    )

    growth, growth_percent = peri_scribe.presentation.views.fire_growth(
        fire,
        tests.helpers.factories.peri_scribe.presentation.views.REFERENCE_TIME,
    )

    assert growth is not None
    assert growth.m_as("meters ** 2") == pytest.approx(
        (latest - baseline).m_as("meters ** 2"),
    )
    assert growth_percent is not None
    assert growth_percent.m_as("percent") == pytest.approx(
        ((latest - baseline) / baseline * 100.0).magnitude,
    )


def test_fire_growth_sorts_perimeters_chronologically() -> None:
    fire = tests.helpers.factories.peri_scribe.presentation.views.active_fire(
        "Scrambled",
        perimeters=(
            peri_scribe.presentation.perimeters.Perimeter(
                geometry=tests.helpers.factories.geometry.square(0.03),
                observation_time=tests.helpers.factories.peri_scribe.presentation.views.REFERENCE_TIME,
            ),
            peri_scribe.presentation.perimeters.Perimeter(
                geometry=tests.helpers.factories.geometry.square(0.02),
                observation_time=tests.helpers.factories.peri_scribe.presentation.views.REFERENCE_TIME
                - datetime.timedelta(hours=48),
            ),
        ),
    )
    baseline = spatial_data.measurements.area(
        tests.helpers.factories.geometry.square(0.02),
    )
    latest = spatial_data.measurements.area(
        tests.helpers.factories.geometry.square(0.03),
    )

    growth, _growth_percent = peri_scribe.presentation.views.fire_growth(
        fire,
        tests.helpers.factories.peri_scribe.presentation.views.REFERENCE_TIME,
    )

    assert growth is not None
    assert growth.m_as("meters ** 2") == pytest.approx(
        (latest - baseline).m_as("meters ** 2"),
    )


def test_fire_growth_without_timed_perimeters_is_unknown() -> None:
    fire = tests.helpers.factories.peri_scribe.presentation.views.active_fire(
        "Timeless",
        perimeters=(
            peri_scribe.presentation.perimeters.Perimeter(
                geometry=tests.helpers.factories.geometry.square(0.02),
                observation_time=None,
            ),
        ),
    )

    assert peri_scribe.presentation.views.fire_growth(
        fire,
        tests.helpers.factories.peri_scribe.presentation.views.REFERENCE_TIME,
    ) == (None, None)


def test_fire_growth_without_window_start_counts_whole_area() -> None:
    fire = tests.helpers.factories.peri_scribe.presentation.views.active_fire(
        "Newborn",
        perimeters=(
            peri_scribe.presentation.perimeters.Perimeter(
                geometry=tests.helpers.factories.geometry.square(0.03),
                observation_time=tests.helpers.factories.peri_scribe.presentation.views.REFERENCE_TIME
                - datetime.timedelta(hours=24),
            ),
            peri_scribe.presentation.perimeters.Perimeter(
                geometry=tests.helpers.factories.geometry.square(0.04),
                observation_time=tests.helpers.factories.peri_scribe.presentation.views.REFERENCE_TIME,
            ),
        ),
    )

    growth, growth_percent = peri_scribe.presentation.views.fire_growth(
        fire,
        tests.helpers.factories.peri_scribe.presentation.views.REFERENCE_TIME,
    )

    assert growth is not None
    assert growth.m_as("meters ** 2") == pytest.approx(
        spatial_data.measurements.area(
            tests.helpers.factories.geometry.square(0.04),
        ).m_as(
            "meters ** 2",
        ),
    )
    assert growth_percent is None


def test_fire_growth_percent_is_unknown_without_baseline_area() -> None:
    fire = tests.helpers.factories.peri_scribe.presentation.views.active_fire(
        "FromNothing",
        perimeters=(
            peri_scribe.presentation.perimeters.Perimeter(
                geometry=shapely.geometry.Point(0.0, 0.0),
                observation_time=tests.helpers.factories.peri_scribe.presentation.views.REFERENCE_TIME
                - datetime.timedelta(hours=48),
            ),
            peri_scribe.presentation.perimeters.Perimeter(
                geometry=tests.helpers.factories.geometry.square(0.03),
                observation_time=tests.helpers.factories.peri_scribe.presentation.views.REFERENCE_TIME,
            ),
        ),
    )

    growth, growth_percent = peri_scribe.presentation.views.fire_growth(
        fire,
        tests.helpers.factories.peri_scribe.presentation.views.REFERENCE_TIME,
    )

    assert growth_percent is None
    assert growth is not None
    assert growth.m_as("meters ** 2") == pytest.approx(
        spatial_data.measurements.area(
            tests.helpers.factories.geometry.square(0.03),
        ).m_as(
            "meters ** 2",
        ),
    )


def test_fast_growing_fires_by_acres_filters_and_sorts() -> None:
    fires = [
        tests.helpers.factories.peri_scribe.presentation.views.growing_fire(
            "Small",
            0.01,
            0.015,
            tests.helpers.factories.peri_scribe.presentation.views.REFERENCE_TIME,
        ),
        tests.helpers.factories.peri_scribe.presentation.views.growing_fire(
            "Huge",
            0.02,
            0.04,
            tests.helpers.factories.peri_scribe.presentation.views.REFERENCE_TIME,
        ),
        tests.helpers.factories.peri_scribe.presentation.views.growing_fire(
            "Big",
            0.02,
            0.03,
            tests.helpers.factories.peri_scribe.presentation.views.REFERENCE_TIME,
        ),
    ]

    assert [
        fire.name
        for fire in peri_scribe.presentation.views.fast_growing_fires_by_acres(
            fires,
            tests.helpers.factories.peri_scribe.presentation.views.REFERENCE_TIME,
        )
    ] == ["Huge", "Big"]


def test_fast_growing_fires_by_acres_returns_empty_without_reference_time() -> None:
    fires = [
        tests.helpers.factories.peri_scribe.presentation.views.growing_fire(
            "Big",
            0.02,
            0.03,
            tests.helpers.factories.peri_scribe.presentation.views.REFERENCE_TIME,
        ),
    ]

    assert peri_scribe.presentation.views.fast_growing_fires_by_acres(fires, None) == []


def test_fast_growing_fires_by_acres_includes_zero_baseline_growth() -> None:
    fire = tests.helpers.factories.peri_scribe.presentation.views.active_fire(
        "Newborn",
        perimeters=(
            peri_scribe.presentation.perimeters.Perimeter(
                geometry=tests.helpers.factories.geometry.square(0.03),
                observation_time=tests.helpers.factories.peri_scribe.presentation.views.REFERENCE_TIME,
            ),
        ),
    )

    assert peri_scribe.presentation.views.fast_growing_fires_by_acres(
        [fire],
        tests.helpers.factories.peri_scribe.presentation.views.REFERENCE_TIME,
    ) == [fire]


def test_fast_growing_fires_by_acres_limits_to_top_count() -> None:
    fires = [
        tests.helpers.factories.peri_scribe.presentation.views.growing_fire(
            f"Grower {index}",
            0.02,
            0.03,
            tests.helpers.factories.peri_scribe.presentation.views.REFERENCE_TIME,
        )
        for index in range(51)
    ]

    assert (
        len(
            peri_scribe.presentation.views.fast_growing_fires_by_acres(
                fires,
                tests.helpers.factories.peri_scribe.presentation.views.REFERENCE_TIME,
            ),
        )
        == peri_scribe.presentation.views.TOP_FIRE_COUNT
    )


def test_fast_growing_fires_by_percent_filters_and_sorts() -> None:
    fires = [
        tests.helpers.factories.peri_scribe.presentation.views.growing_fire(
            "Small",
            0.1,
            0.102,
            tests.helpers.factories.peri_scribe.presentation.views.REFERENCE_TIME,
        ),
        tests.helpers.factories.peri_scribe.presentation.views.growing_fire(
            "Huge",
            0.03,
            0.04,
            tests.helpers.factories.peri_scribe.presentation.views.REFERENCE_TIME,
        ),
        tests.helpers.factories.peri_scribe.presentation.views.growing_fire(
            "Big",
            0.02,
            0.03,
            tests.helpers.factories.peri_scribe.presentation.views.REFERENCE_TIME,
        ),
    ]

    assert [
        fire.name
        for fire in peri_scribe.presentation.views.fast_growing_fires_by_percent(
            fires,
            tests.helpers.factories.peri_scribe.presentation.views.REFERENCE_TIME,
        )
    ] == ["Big", "Huge"]


def test_fast_growing_fires_by_percent_returns_empty_without_reference_time() -> None:
    fires = [
        tests.helpers.factories.peri_scribe.presentation.views.growing_fire(
            "Big",
            0.02,
            0.03,
            tests.helpers.factories.peri_scribe.presentation.views.REFERENCE_TIME,
        ),
    ]

    assert (
        peri_scribe.presentation.views.fast_growing_fires_by_percent(fires, None) == []
    )


def test_fast_growing_fires_by_percent_excludes_zero_baseline_growth() -> None:
    fire = tests.helpers.factories.peri_scribe.presentation.views.active_fire(
        "Newborn",
        perimeters=(
            peri_scribe.presentation.perimeters.Perimeter(
                geometry=tests.helpers.factories.geometry.square(0.03),
                observation_time=tests.helpers.factories.peri_scribe.presentation.views.REFERENCE_TIME,
            ),
        ),
    )

    assert (
        peri_scribe.presentation.views.fast_growing_fires_by_percent(
            [fire],
            tests.helpers.factories.peri_scribe.presentation.views.REFERENCE_TIME,
        )
        == []
    )


def test_fast_growing_fires_by_percent_limits_to_top_count() -> None:
    fires = [
        tests.helpers.factories.peri_scribe.presentation.views.growing_fire(
            f"Grower {index}",
            0.02,
            0.03,
            tests.helpers.factories.peri_scribe.presentation.views.REFERENCE_TIME,
        )
        for index in range(51)
    ]

    assert (
        len(
            peri_scribe.presentation.views.fast_growing_fires_by_percent(
                fires,
                tests.helpers.factories.peri_scribe.presentation.views.REFERENCE_TIME,
            ),
        )
        == peri_scribe.presentation.views.TOP_FIRE_COUNT
    )


def test_most_personnel_fires_sorts_known_personnel() -> None:
    low = tests.helpers.factories.peri_scribe.presentation.views.active_fire(
        "Low",
        description=peri_scribe.presentation.descriptions.FireDescription(
            total_personnel=10.0,
            observation_time=tests.helpers.factories.peri_scribe.presentation.views.REFERENCE_TIME,
        ),
    )
    high = tests.helpers.factories.peri_scribe.presentation.views.active_fire(
        "High",
        description=peri_scribe.presentation.descriptions.FireDescription(
            total_personnel=100.0,
            observation_time=tests.helpers.factories.peri_scribe.presentation.views.REFERENCE_TIME,
        ),
    )

    assert [
        fire.name
        for fire in peri_scribe.presentation.views.most_personnel_fires(
            [low, high],
            tests.helpers.factories.peri_scribe.presentation.views.REFERENCE_TIME,
        )
    ] == ["High", "Low"]


def test_most_personnel_fires_excludes_missing_personnel() -> None:
    missing_description = (
        tests.helpers.factories.peri_scribe.presentation.views.active_fire(
            "NoDescription",
        )
    )
    missing_count = tests.helpers.factories.peri_scribe.presentation.views.active_fire(
        "NoCount",
        description=peri_scribe.presentation.descriptions.FireDescription(
            observation_time=tests.helpers.factories.peri_scribe.presentation.views.REFERENCE_TIME,
        ),
    )
    staffed = tests.helpers.factories.peri_scribe.presentation.views.active_fire(
        "Staffed",
        description=peri_scribe.presentation.descriptions.FireDescription(
            total_personnel=5.0,
            observation_time=tests.helpers.factories.peri_scribe.presentation.views.REFERENCE_TIME,
        ),
    )

    assert [
        fire.name
        for fire in peri_scribe.presentation.views.most_personnel_fires(
            [missing_description, missing_count, staffed],
            tests.helpers.factories.peri_scribe.presentation.views.REFERENCE_TIME,
        )
    ] == ["Staffed"]


def test_most_personnel_fires_excludes_stale_update() -> None:
    stale = tests.helpers.factories.peri_scribe.presentation.views.active_fire(
        "Stale",
        description=peri_scribe.presentation.descriptions.FireDescription(
            total_personnel=50.0,
            observation_time=tests.helpers.factories.peri_scribe.presentation.views.REFERENCE_TIME
            - datetime.timedelta(days=8),
        ),
    )

    assert (
        peri_scribe.presentation.views.most_personnel_fires(
            [stale],
            tests.helpers.factories.peri_scribe.presentation.views.REFERENCE_TIME,
        )
        == []
    )


def test_most_personnel_fires_excludes_missing_update() -> None:
    fire = tests.helpers.factories.peri_scribe.presentation.views.active_fire(
        "NoUpdate",
        description=peri_scribe.presentation.descriptions.FireDescription(
            total_personnel=50.0,
        ),
    )

    assert (
        peri_scribe.presentation.views.most_personnel_fires(
            [fire],
            tests.helpers.factories.peri_scribe.presentation.views.REFERENCE_TIME,
        )
        == []
    )


def test_most_personnel_fires_excludes_future_update() -> None:
    fire = tests.helpers.factories.peri_scribe.presentation.views.active_fire(
        "Future",
        description=peri_scribe.presentation.descriptions.FireDescription(
            total_personnel=50.0,
            observation_time=tests.helpers.factories.peri_scribe.presentation.views.REFERENCE_TIME
            + datetime.timedelta(hours=1),
        ),
    )

    assert (
        peri_scribe.presentation.views.most_personnel_fires(
            [fire],
            tests.helpers.factories.peri_scribe.presentation.views.REFERENCE_TIME,
        )
        == []
    )


def test_most_personnel_fires_returns_empty_without_reference_time() -> None:
    fire = tests.helpers.factories.peri_scribe.presentation.views.active_fire(
        "Staffed",
        description=peri_scribe.presentation.descriptions.FireDescription(
            total_personnel=5.0,
            observation_time=tests.helpers.factories.peri_scribe.presentation.views.REFERENCE_TIME,
        ),
    )

    assert peri_scribe.presentation.views.most_personnel_fires([fire], None) == []


def test_most_personnel_fires_limits_to_top_count() -> None:
    fires = [
        tests.helpers.factories.peri_scribe.presentation.views.active_fire(
            f"Staffed {index}",
            description=peri_scribe.presentation.descriptions.FireDescription(
                total_personnel=float(index),
                observation_time=tests.helpers.factories.peri_scribe.presentation.views.REFERENCE_TIME,
            ),
        )
        for index in range(51)
    ]

    assert (
        len(
            peri_scribe.presentation.views.most_personnel_fires(
                fires,
                tests.helpers.factories.peri_scribe.presentation.views.REFERENCE_TIME,
            ),
        )
        == peri_scribe.presentation.views.TOP_FIRE_COUNT
    )
