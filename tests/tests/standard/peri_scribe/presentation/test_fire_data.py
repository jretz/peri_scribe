"""Tests for peri_scribe.presentation.fire_data."""

from __future__ import annotations

import datetime
import pathlib

import pytest
import shapely
import shapely.geometry

import peri_scribe.areas
import peri_scribe.execution
import peri_scribe.models
import peri_scribe.presentation.fire_data
import peri_scribe.presentation.selection
import spatial_data.measurements
import tests.helpers.doubles.peri_scribe.presentation.fire_data
import tests.helpers.factories.geometry
import tests.helpers.factories.peri_scribe.component_identity
import tests.helpers.factories.peri_scribe.kml.parsing
import tests.helpers.factories.peri_scribe.presentation.fire_data


@pytest.mark.parametrize("cached_count", [None, 0, 1, 2])
def test_prepare_fires_selects_only_histories_missing_from_prepared_evidence(
    monkeypatch: pytest.MonkeyPatch,
    cached_count: int | None,
) -> None:
    rows: list[tuple[str | None, str]] = [("id-bug", "Bug"), ("id-oak", "Oak")]
    index = tests.helpers.factories.peri_scribe.kml.parsing.fire_index([
        tests.helpers.factories.peri_scribe.kml.parsing.fire_index_entry(
            name,
            "active",
            identifier=identifier,
        )
        for identifier, name in rows
    ])
    points = tests.helpers.factories.peri_scribe.presentation.fire_data.area_frame(
        "incident_size",
        rows,
        [100.0, 200.0],
    )
    perimeters = points.iloc[0:0]
    incidents = points.copy()
    expected = peri_scribe.presentation.fire_data.prepare_fires(
        index=index,
        perimeters=perimeters,
        points=points,
        perimeter_by_identifier={},
        perimeter_by_name={},
        ring_by_identifier={},
        ring_by_name={},
        incident_rows=incidents,
    )
    histories = (
        None
        if cached_count is None
        else {
            peri_scribe.presentation.selection.fire_area_key(
                fire.entry.identifier,
                fire.entry.name,
            ): fire.history
            for fire in expected[:cached_count]
            if fire.history is not None
        }
    )
    calls = tests.helpers.doubles.peri_scribe.presentation.fire_data.record_selections(
        monkeypatch,
    )
    actual = peri_scribe.presentation.fire_data.prepare_fires(
        index=index,
        perimeters=perimeters,
        points=points,
        perimeter_by_identifier={},
        perimeter_by_name={},
        ring_by_identifier={},
        ring_by_name={},
        incident_rows=incidents,
        histories=histories,
    )
    assert actual == expected
    assert calls == [
        selection
        for position in range(cached_count or 0, len(rows))
        for selection in (
            (id(perimeters), ()),
            (id(points), (position,)),
            (id(incidents), (position,)),
        )
    ]


def test_prepare_fires_retains_empty_prepared_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    index = tests.helpers.factories.peri_scribe.kml.parsing.fire_index([
        tests.helpers.factories.peri_scribe.kml.parsing.fire_index_entry(
            "Bug",
            "active",
            identifier="id-bug",
        ),
    ])
    points = tests.helpers.factories.peri_scribe.presentation.fire_data.area_frame(
        "incident_size",
        [("id-bug", "Bug")],
        [100.0],
    )
    empty = points.iloc[0:0]
    history = peri_scribe.areas.prepare_history(empty, empty)
    calls = tests.helpers.doubles.peri_scribe.presentation.fire_data.record_selections(
        monkeypatch,
    )
    (fire,) = peri_scribe.presentation.fire_data.prepare_fires(
        index=index,
        perimeters=empty,
        points=points,
        perimeter_by_identifier={},
        perimeter_by_name={},
        ring_by_identifier={},
        ring_by_name={},
        histories={
            peri_scribe.presentation.selection.fire_area_key("id-bug", "Bug"): history,
        },
    )
    assert fire.history is history
    assert not calls


def test_prepare_fire_data_shares_equal_index_and_scores_within_one_run() -> None:
    index = tests.helpers.factories.peri_scribe.kml.parsing.fire_index([])
    empty = tests.helpers.factories.peri_scribe.kml.parsing.geometry_frame([])
    scores = peri_scribe.models.FireScores(version="test", fires=[])
    with peri_scribe.execution.sharing():
        first = peri_scribe.presentation.fire_data.prepare_fire_data(
            index,
            empty,
            empty,
            empty,
            scores,
        )
        second = peri_scribe.presentation.fire_data.prepare_fire_data(
            index.model_copy(deep=True),
            empty,
            empty,
            empty,
            scores.model_copy(deep=True),
        )
    assert first is second


def test_prepare_fire_data_rebuilds_between_runs() -> None:
    index = tests.helpers.factories.peri_scribe.kml.parsing.fire_index([])
    empty = tests.helpers.factories.peri_scribe.kml.parsing.geometry_frame([])
    with peri_scribe.execution.sharing():
        first = peri_scribe.presentation.fire_data.prepare_fire_data(
            index,
            empty,
            empty,
            empty,
        )
    with peri_scribe.execution.sharing():
        second = peri_scribe.presentation.fire_data.prepare_fire_data(
            index,
            empty,
            empty,
            empty,
        )
    assert first is not second


def test_prepare_fire_data_rebuilds_for_replaced_sources() -> None:
    index = tests.helpers.factories.peri_scribe.kml.parsing.fire_index([])
    empty = tests.helpers.factories.peri_scribe.kml.parsing.geometry_frame([])
    with peri_scribe.execution.sharing():
        first = peri_scribe.presentation.fire_data.prepare_fire_data(
            index,
            empty,
            empty,
            empty,
        )
        second = peri_scribe.presentation.fire_data.prepare_fire_data(
            index,
            empty.copy(),
            empty,
            empty,
        )
    assert first is not second


def test_prepare_fire_data_rebuilds_when_score_explanation_changes() -> None:
    index = tests.helpers.factories.peri_scribe.kml.parsing.fire_index([
        tests.helpers.factories.peri_scribe.kml.parsing.fire_index_entry(
            "Bug",
            "active",
            identifier="id-bug",
        ),
    ])
    empty = tests.helpers.factories.peri_scribe.kml.parsing.geometry_frame([])
    scores = peri_scribe.models.FireScores(
        version="test",
        fires=[
            peri_scribe.models.FireScoreEntry(
                name="Bug",
                identifier="id-bug",
                score=1,
                explanation="First explanation.",
            ),
        ],
    )
    with peri_scribe.execution.sharing():
        (first,) = peri_scribe.presentation.fire_data.prepare_fire_data(
            index,
            empty,
            empty,
            empty,
            scores,
        )
        scores.fires[0].explanation = "Updated explanation."
        (second,) = peri_scribe.presentation.fire_data.prepare_fire_data(
            index,
            empty,
            empty,
            empty,
            scores,
        )
    assert first.summary.description is not None
    assert second.summary.description is not None
    assert first.summary.description.of_note == "First explanation."
    assert second.summary.description.of_note == "Updated explanation."


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


def test_fire_summaries_keeps_anonymous_component_geography_separate(
    tmp_path: pathlib.Path,
) -> None:
    expected_count = 2
    factory = tests.helpers.factories.peri_scribe.component_identity
    summaries = factory.summaries(factory.sources(tmp_path), tmp_path)
    assert len(summaries) == expected_count
    assert [len(fire.perimeters) for fire in summaries] == [1, 1]


def test_prepare_fire_data_selects_component_points_and_incident_reports(
    tmp_path: pathlib.Path,
) -> None:
    factory = tests.helpers.factories.peri_scribe.component_identity
    index, full, _empty = factory.histories(factory.sources(tmp_path), tmp_path)
    points = full.copy()
    points.geometry = [shapely.Point(-121, 36), shapely.Point(-149, 64)]
    prepared = peri_scribe.presentation.fire_data.prepare_fire_data(
        index,
        full,
        points,
        full.iloc[0:0],
        incident_rows=full,
    )
    for fire in prepared:
        matching = points[points["fire_component_id"] == fire.summary.component_id]
        assert fire.summary.point is not None
        assert fire.summary.point.equals(matching.geometry.iloc[-1])
        assert len(fire.point_positions) == 1
        assert fire.history is not None
