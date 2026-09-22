"""Tests for peri_scribe.presentation.fire_data."""

from __future__ import annotations

import datetime

import shapely.geometry

import peri_scribe.models
import peri_scribe.presentation.fire_data
import spatial_data.measurements
import tests.helpers.factories.geometry
import tests.helpers.factories.peri_scribe.kml.parsing
import tests.helpers.factories.peri_scribe.presentation.fire_data


def test_fire_perimeters_matches_identifier() -> None:
    perimeters = (
        tests.helpers.factories.peri_scribe.kml.parsing.perimeter_with_time(
            tests.helpers.factories.geometry.square(1.0),
        ),
        tests.helpers.factories.peri_scribe.kml.parsing.perimeter_with_time(
            tests.helpers.factories.geometry.square(2.0),
        ),
    )
    result = peri_scribe.presentation.fire_data.fire_perimeters(
        frozenset({"id-a"}),
        "Bug",
        {"id-a": list(perimeters)},
        {},
    )
    assert result == perimeters


def test_fire_perimeters_falls_back_to_name() -> None:
    perimeters = (
        tests.helpers.factories.peri_scribe.kml.parsing.perimeter_with_time(
            tests.helpers.factories.geometry.square(1.0),
        ),
    )
    result = peri_scribe.presentation.fire_data.fire_perimeters(
        frozenset(),
        "Bug",
        {},
        {"Bug": list(perimeters)},
    )
    assert result == perimeters


def test_fire_perimeters_returns_empty_when_unknown() -> None:
    assert (
        peri_scribe.presentation.fire_data.fire_perimeters(
            frozenset({"id-a"}),
            "Bug",
            {},
            {},
        )
        == ()
    )


def test_fire_summaries_matches_aliases_and_sorts_by_name() -> None:
    index = tests.helpers.factories.peri_scribe.kml.parsing.fire_index([
        tests.helpers.factories.peri_scribe.kml.parsing.fire_index_entry(
            "Sorrento",
            "active",
            identifier="2026-casnd-150541",
            aliases=["2026-casnd-26150541"],
        ),
        tests.helpers.factories.peri_scribe.kml.parsing.fire_index_entry(
            "Bug",
            "inactive",
            identifier="id-bug",
        ),
    ])
    sorrento_perimeter = tests.helpers.factories.geometry.square(3.0)
    perimeters = tests.helpers.factories.peri_scribe.kml.parsing.geometry_frame([
        ("2026-casnd-26150541", "Sorrento", sorrento_perimeter),
        ("id-bug", "Bug", tests.helpers.factories.geometry.square(1.0)),
    ])
    bug_point = shapely.geometry.Point(1.0, 1.0)
    points = tests.helpers.factories.peri_scribe.kml.parsing.geometry_frame([
        ("id-bug", "Bug", bug_point),
    ])
    fires = peri_scribe.presentation.fire_data.fire_summaries(
        index,
        perimeters,
        points,
        tests.helpers.factories.peri_scribe.kml.parsing.geometry_frame([]),
    )
    assert [fire.name for fire in fires] == ["Bug", "Sorrento"]
    bug, sorrento = fires
    assert bug.status is peri_scribe.models.FireStatus.INACTIVE
    assert bug.point is bug_point
    assert bug.perimeters == (
        tests.helpers.factories.peri_scribe.kml.parsing.perimeter_with_time(
            tests.helpers.factories.geometry.square(1.0),
        ),
    )
    assert sorrento.status is peri_scribe.models.FireStatus.ACTIVE
    assert sorrento.point == sorrento_perimeter.representative_point()
    assert sorrento.perimeters == (
        tests.helpers.factories.peri_scribe.kml.parsing.perimeter_with_time(
            sorrento_perimeter,
        ),
    )


def test_fire_summaries_derives_point_for_inactive_fire_without_location() -> None:
    index = tests.helpers.factories.peri_scribe.kml.parsing.fire_index([
        tests.helpers.factories.peri_scribe.kml.parsing.fire_index_entry(
            "ALTA",
            "inactive",
            identifier="id-alta",
        ),
    ])
    perimeter = tests.helpers.factories.geometry.square(2.0)
    fires = peri_scribe.presentation.fire_data.fire_summaries(
        index,
        tests.helpers.factories.peri_scribe.kml.parsing.geometry_frame([
            ("id-alta", "ALTA", perimeter),
        ]),
        tests.helpers.factories.peri_scribe.kml.parsing.geometry_frame([]),
        tests.helpers.factories.peri_scribe.kml.parsing.geometry_frame([]),
    )
    (fire,) = fires
    assert fire.status is peri_scribe.models.FireStatus.INACTIVE
    assert fire.point == perimeter.representative_point()
    assert fire.perimeters == (
        tests.helpers.factories.peri_scribe.kml.parsing.perimeter_with_time(perimeter),
    )


def test_fire_summaries_sorts_by_case_folded_name() -> None:
    index = tests.helpers.factories.peri_scribe.kml.parsing.fire_index([
        tests.helpers.factories.peri_scribe.kml.parsing.fire_index_entry(
            name,
            "active",
            identifier=f"id-{name}",
        )
        for name in ("aB", "Ac", "AD", "ae")
    ])
    fires = peri_scribe.presentation.fire_data.fire_summaries(
        index,
        tests.helpers.factories.peri_scribe.kml.parsing.geometry_frame([]),
        tests.helpers.factories.peri_scribe.kml.parsing.geometry_frame([]),
        tests.helpers.factories.peri_scribe.kml.parsing.geometry_frame([]),
    )
    assert [fire.name for fire in fires] == ["aB", "Ac", "AD", "ae"]


def test_fire_summaries_puts_score_explanation_in_balloon() -> None:
    index = tests.helpers.factories.peri_scribe.kml.parsing.fire_index([
        tests.helpers.factories.peri_scribe.kml.parsing.fire_index_entry(
            "Bug",
            "active",
            identifier="id-bug",
        ),
    ])
    perimeters = tests.helpers.factories.peri_scribe.kml.parsing.geometry_frame([
        ("id-bug", "Bug", tests.helpers.factories.geometry.square(1.0)),
    ])
    scores = peri_scribe.models.FireScores(
        version="test",
        fires=[
            peri_scribe.models.FireScoreEntry(
                name="Bug",
                identifier="id-bug",
                score=389,
                explanation="Over 100,000 acres, and a Type 1 Incident.",
            ),
        ],
    )
    (with_scores,) = peri_scribe.presentation.fire_data.fire_summaries(
        index,
        perimeters,
        tests.helpers.factories.peri_scribe.kml.parsing.geometry_frame([]),
        tests.helpers.factories.peri_scribe.kml.parsing.geometry_frame([]),
        scores=scores,
    )
    assert with_scores.description is not None
    assert (
        with_scores.description.of_note == "Over 100,000 acres, and a Type 1 Incident."
    )
    (without_scores,) = peri_scribe.presentation.fire_data.fire_summaries(
        index,
        perimeters,
        tests.helpers.factories.peri_scribe.kml.parsing.geometry_frame([]),
        tests.helpers.factories.peri_scribe.kml.parsing.geometry_frame([]),
    )
    assert without_scores.description is not None
    assert without_scores.description.of_note is None


def test_fire_summaries_marks_type_one_incident_from_point_rows() -> None:
    index = tests.helpers.factories.peri_scribe.kml.parsing.fire_index([
        tests.helpers.factories.peri_scribe.kml.parsing.fire_index_entry(
            "Bug",
            "active",
            identifier="id-bug",
        ),
    ])
    perimeters = tests.helpers.factories.peri_scribe.kml.parsing.geometry_frame([
        ("id-bug", "Bug", tests.helpers.factories.geometry.square(1.0)),
    ])

    (fire,) = peri_scribe.presentation.fire_data.fire_summaries(
        index,
        perimeters,
        tests.helpers.factories.peri_scribe.presentation.fire_data.type_one_point_frame(
            "Type 1 Incident",
        ),
        tests.helpers.factories.peri_scribe.kml.parsing.geometry_frame([]),
    )

    assert fire.type_one


def test_fire_summaries_leaves_lower_complexity_fire_unmarked() -> None:
    index = tests.helpers.factories.peri_scribe.kml.parsing.fire_index([
        tests.helpers.factories.peri_scribe.kml.parsing.fire_index_entry(
            "Bug",
            "active",
            identifier="id-bug",
        ),
    ])
    perimeters = tests.helpers.factories.peri_scribe.kml.parsing.geometry_frame([
        ("id-bug", "Bug", tests.helpers.factories.geometry.square(1.0)),
    ])

    (fire,) = peri_scribe.presentation.fire_data.fire_summaries(
        index,
        perimeters,
        tests.helpers.factories.peri_scribe.presentation.fire_data.type_one_point_frame(
            "Type 2 Incident",
        ),
        tests.helpers.factories.peri_scribe.kml.parsing.geometry_frame([]),
    )

    assert not fire.type_one


def test_fire_summaries_leaves_fire_unmarked_without_complexity_level() -> None:
    index = tests.helpers.factories.peri_scribe.kml.parsing.fire_index([
        tests.helpers.factories.peri_scribe.kml.parsing.fire_index_entry(
            "Bug",
            "active",
            identifier="id-bug",
        ),
    ])
    perimeters = tests.helpers.factories.peri_scribe.kml.parsing.geometry_frame([
        ("id-bug", "Bug", tests.helpers.factories.geometry.square(1.0)),
    ])

    (fire,) = peri_scribe.presentation.fire_data.fire_summaries(
        index,
        perimeters,
        tests.helpers.factories.peri_scribe.presentation.fire_data.type_one_point_frame(
            None,
        ),
        tests.helpers.factories.peri_scribe.kml.parsing.geometry_frame([]),
    )

    assert not fire.type_one


def test_fire_summaries_leaves_fire_unmarked_without_point_attributes() -> None:
    index = tests.helpers.factories.peri_scribe.kml.parsing.fire_index([
        tests.helpers.factories.peri_scribe.kml.parsing.fire_index_entry(
            "Bug",
            "active",
            identifier="id-bug",
        ),
    ])
    perimeters = tests.helpers.factories.peri_scribe.kml.parsing.geometry_frame([
        ("id-bug", "Bug", tests.helpers.factories.geometry.square(1.0)),
    ])
    points = tests.helpers.factories.peri_scribe.kml.parsing.geometry_frame([
        ("id-bug", "Bug", shapely.geometry.Point(1.0, 1.0)),
    ])

    (fire,) = peri_scribe.presentation.fire_data.fire_summaries(
        index,
        perimeters,
        points,
        tests.helpers.factories.peri_scribe.kml.parsing.geometry_frame([]),
    )

    assert not fire.type_one


def test_fire_summaries_matches_score_explanation_by_identifier() -> None:
    index = tests.helpers.factories.peri_scribe.kml.parsing.fire_index([
        tests.helpers.factories.peri_scribe.kml.parsing.fire_index_entry(
            "Timber",
            "active",
            identifier="id-big",
        ),
        tests.helpers.factories.peri_scribe.kml.parsing.fire_index_entry(
            "Timber",
            "inactive",
            identifier="id-small",
        ),
    ])
    perimeters = tests.helpers.factories.peri_scribe.kml.parsing.geometry_frame([
        ("id-big", "Timber", tests.helpers.factories.geometry.square(2.0)),
        ("id-small", "Timber", tests.helpers.factories.geometry.square(1.0)),
    ])
    scores = peri_scribe.models.FireScores(
        version="test",
        fires=[
            peri_scribe.models.FireScoreEntry(
                name="Timber",
                identifier="id-small",
                score=4,
                explanation="Over 5 structures within a mile.",
            ),
            peri_scribe.models.FireScoreEntry(
                name="Timber",
                identifier="id-big",
                score=470,
                explanation=(
                    "Over 250 structures within a mile, and a Type 1 Incident."
                ),
            ),
        ],
    )
    big, small = peri_scribe.presentation.fire_data.fire_summaries(
        index,
        perimeters,
        tests.helpers.factories.peri_scribe.kml.parsing.geometry_frame([]),
        tests.helpers.factories.peri_scribe.kml.parsing.geometry_frame([]),
        scores=scores,
    )
    assert big.description is not None
    assert (
        big.description.of_note
        == "Over 250 structures within a mile, and a Type 1 Incident."
    )
    assert small.description is not None
    assert small.description.of_note == "Over 5 structures within a mile."


def test_fire_summaries_includes_progression_rings() -> None:
    index = tests.helpers.factories.peri_scribe.kml.parsing.fire_index([
        tests.helpers.factories.peri_scribe.kml.parsing.fire_index_entry(
            "Bug",
            "active",
            identifier="id-bug",
        ),
    ])
    first_time = datetime.datetime(2026, 8, 5, 20, 0, tzinfo=datetime.UTC)
    second_time = datetime.datetime(2026, 8, 7, 20, 0, tzinfo=datetime.UTC)
    rings = tests.helpers.factories.peri_scribe.kml.parsing.geometry_frame(
        [
            ("id-bug", "Bug", tests.helpers.factories.geometry.square(1.0)),
            ("id-bug", "Bug", tests.helpers.factories.geometry.square(2.0)),
        ],
        observation_times=[first_time, second_time],
    )
    fires = peri_scribe.presentation.fire_data.fire_summaries(
        index,
        tests.helpers.factories.peri_scribe.kml.parsing.geometry_frame([]),
        tests.helpers.factories.peri_scribe.kml.parsing.geometry_frame([]),
        rings,
    )
    (fire,) = fires
    assert [
        (ring.geometry, ring.observation_time) for ring in fire.progression_rings
    ] == [
        (tests.helpers.factories.geometry.square(1.0), first_time),
        (tests.helpers.factories.geometry.square(2.0), second_time),
    ]
    assert [ring.area for ring in fire.progression_rings] == [
        spatial_data.measurements.area(ring.geometry) for ring in fire.progression_rings
    ]


def test_fire_summaries_drops_tiny_rings() -> None:
    index = tests.helpers.factories.peri_scribe.kml.parsing.fire_index([
        tests.helpers.factories.peri_scribe.kml.parsing.fire_index_entry(
            "Bug",
            "active",
            identifier="id-bug",
        ),
    ])
    observation_time = datetime.datetime(2026, 8, 5, 20, 0, tzinfo=datetime.UTC)
    rings = tests.helpers.factories.peri_scribe.kml.parsing.geometry_frame(
        [
            ("id-bug", "Bug", tests.helpers.factories.geometry.square(1.0)),
            ("id-bug", "Bug", shapely.geometry.box(0.0, 0.0, 1e-6, 1e-6)),
        ],
        observation_times=[observation_time, observation_time],
    )
    fires = peri_scribe.presentation.fire_data.fire_summaries(
        index,
        tests.helpers.factories.peri_scribe.kml.parsing.geometry_frame([]),
        tests.helpers.factories.peri_scribe.kml.parsing.geometry_frame([]),
        rings,
    )
    (fire,) = fires
    assert [ring.geometry for ring in fire.progression_rings] == [
        tests.helpers.factories.geometry.square(1.0),
    ]
