"""Tests for peri_scribe.kml.fire_data."""

from __future__ import annotations

import datetime

import pytest
import shapely.geometry

import peri_scribe.kml.colormap
import peri_scribe.kml.fire_data
import peri_scribe.models
import peri_scribe.perimeters.progression
import peri_scribe.units
import tests.helpers.doubles.peri_scribe.kml.fire_data
import tests.helpers.factories.geography
import tests.helpers.factories.geometry
import tests.helpers.factories.peri_scribe.kml.fire_data
import tests.helpers.factories.peri_scribe.kml.parsing
import tests.helpers.factories.time


def test_fire_perimeters_matches_identifier() -> None:
    perimeters = (
        tests.helpers.factories.peri_scribe.kml.parsing.perimeter_with_time(
            tests.helpers.factories.geometry.square(1.0),
        ),
        tests.helpers.factories.peri_scribe.kml.parsing.perimeter_with_time(
            tests.helpers.factories.geometry.square(2.0),
        ),
    )
    result = peri_scribe.kml.fire_data.fire_perimeters(
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
    result = peri_scribe.kml.fire_data.fire_perimeters(
        frozenset(),
        "Bug",
        {},
        {"Bug": list(perimeters)},
    )
    assert result == perimeters


def test_fire_perimeters_returns_empty_when_unknown() -> None:
    assert (
        peri_scribe.kml.fire_data.fire_perimeters(frozenset({"id-a"}), "Bug", {}, {})
        == ()
    )


def test_fire_geometries_matches_aliases_and_sorts_by_name() -> None:
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
    fires = peri_scribe.kml.fire_data.fire_geometries(
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


def test_fire_geometries_derives_point_for_inactive_fire_without_location() -> None:
    index = tests.helpers.factories.peri_scribe.kml.parsing.fire_index([
        tests.helpers.factories.peri_scribe.kml.parsing.fire_index_entry(
            "ALTA",
            "inactive",
            identifier="id-alta",
        ),
    ])
    perimeter = tests.helpers.factories.geometry.square(2.0)
    fires = peri_scribe.kml.fire_data.fire_geometries(
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


def test_fire_geometries_sorts_by_case_folded_name() -> None:
    index = tests.helpers.factories.peri_scribe.kml.parsing.fire_index([
        tests.helpers.factories.peri_scribe.kml.parsing.fire_index_entry(
            name,
            "active",
            identifier=f"id-{name}",
        )
        for name in ("aB", "Ac", "AD", "ae")
    ])
    fires = peri_scribe.kml.fire_data.fire_geometries(
        index,
        tests.helpers.factories.peri_scribe.kml.parsing.geometry_frame([]),
        tests.helpers.factories.peri_scribe.kml.parsing.geometry_frame([]),
        tests.helpers.factories.peri_scribe.kml.parsing.geometry_frame([]),
    )
    assert [fire.name for fire in fires] == ["aB", "Ac", "AD", "ae"]


def test_fire_geometries_attaches_plot_images() -> None:
    index = tests.helpers.factories.peri_scribe.kml.parsing.fire_index([
        tests.helpers.factories.peri_scribe.kml.parsing.fire_index_entry(
            "Bug",
            "active",
            identifier="id-bug",
        ),
    ])
    perimeters = tests.helpers.factories.peri_scribe.kml.parsing.geometry_frame(
        [
            ("id-bug", "Bug", tests.helpers.factories.geometry.square(1.0)),
            ("id-bug", "Bug", tests.helpers.factories.geometry.square(2.0)),
        ],
        observation_times=[
            datetime.datetime(2026, 8, 5, 20, 0, tzinfo=datetime.UTC),
            datetime.datetime(2026, 8, 6, 20, 0, tzinfo=datetime.UTC),
        ],
    )
    fires = peri_scribe.kml.fire_data.fire_geometries(
        index,
        perimeters,
        tests.helpers.factories.peri_scribe.kml.parsing.geometry_frame([]),
        tests.helpers.factories.peri_scribe.kml.parsing.geometry_frame([]),
    )
    (fire,) = fires
    assert [image.filename for image in fire.images] == [
        "id-bug-area.svg",
        "id-bug-perimeter.svg",
    ]
    assert fire.images[0].content
    assert fire.description is not None
    assert fire.description.identifier == "id-bug"


def test_fire_geometries_skips_plot_images_when_render_plots_is_false() -> None:
    index = tests.helpers.factories.peri_scribe.kml.parsing.fire_index([
        tests.helpers.factories.peri_scribe.kml.parsing.fire_index_entry(
            "Bug",
            "active",
            identifier="id-bug",
        ),
    ])
    perimeters = tests.helpers.factories.peri_scribe.kml.parsing.geometry_frame(
        [
            ("id-bug", "Bug", tests.helpers.factories.geometry.square(1.0)),
            ("id-bug", "Bug", tests.helpers.factories.geometry.square(2.0)),
        ],
        observation_times=[
            datetime.datetime(2026, 8, 5, 20, 0, tzinfo=datetime.UTC),
            datetime.datetime(2026, 8, 6, 20, 0, tzinfo=datetime.UTC),
        ],
    )
    fires = peri_scribe.kml.fire_data.fire_geometries(
        index,
        perimeters,
        tests.helpers.factories.peri_scribe.kml.parsing.geometry_frame([]),
        tests.helpers.factories.peri_scribe.kml.parsing.geometry_frame([]),
        render_plots=False,
    )
    (fire,) = fires
    assert fire.images == ()
    assert fire.description is not None
    assert fire.description.identifier == "id-bug"


def test_fire_geometries_matches_identifier_less_fire_by_name() -> None:
    index = tests.helpers.factories.peri_scribe.kml.parsing.fire_index([
        tests.helpers.factories.peri_scribe.kml.parsing.fire_index_entry(
            "Bug",
            "active",
        ),
    ])
    # The fire has no identifier, yet its history rows carry one; the name match must
    # still include those rows for the plots and description.
    first_area = peri_scribe.units.area(tests.helpers.factories.geometry.square(1.0))
    second_area = peri_scribe.units.area(tests.helpers.factories.geometry.square(2.0))
    perimeters = tests.helpers.factories.peri_scribe.kml.parsing.geometry_frame(
        [
            ("id-bug", "Bug", tests.helpers.factories.geometry.square(1.0)),
            ("id-bug", "Bug", tests.helpers.factories.geometry.square(2.0)),
        ],
        observation_times=[
            datetime.datetime(2026, 8, 5, 20, 0, tzinfo=datetime.UTC),
            datetime.datetime(2026, 8, 6, 20, 0, tzinfo=datetime.UTC),
        ],
        area_acres=[first_area.m_as("acres"), second_area.m_as("acres")],
    )
    (fire,) = peri_scribe.kml.fire_data.fire_geometries(
        index,
        perimeters,
        tests.helpers.factories.peri_scribe.kml.parsing.geometry_frame([]),
        tests.helpers.factories.peri_scribe.kml.parsing.geometry_frame([]),
    )
    assert fire.name == "Bug"
    assert fire.images
    assert fire.description is not None
    assert fire.description.area is not None
    assert fire.description.area.m_as("acres") == pytest.approx(
        second_area.m_as("acres"),
    )


def test_fire_geometries_puts_score_explanation_in_balloon() -> None:
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
    (with_scores,) = peri_scribe.kml.fire_data.fire_geometries(
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
    (without_scores,) = peri_scribe.kml.fire_data.fire_geometries(
        index,
        perimeters,
        tests.helpers.factories.peri_scribe.kml.parsing.geometry_frame([]),
        tests.helpers.factories.peri_scribe.kml.parsing.geometry_frame([]),
    )
    assert without_scores.description is not None
    assert without_scores.description.of_note is None


def test_fire_geometries_marks_type_one_incident_from_point_rows() -> None:
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

    (fire,) = peri_scribe.kml.fire_data.fire_geometries(
        index,
        perimeters,
        tests.helpers.factories.peri_scribe.kml.fire_data.type_one_point_frame(
            "Type 1 Incident",
        ),
        tests.helpers.factories.peri_scribe.kml.parsing.geometry_frame([]),
    )

    assert fire.type_one


def test_fire_geometries_leaves_lower_complexity_fire_unmarked() -> None:
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

    (fire,) = peri_scribe.kml.fire_data.fire_geometries(
        index,
        perimeters,
        tests.helpers.factories.peri_scribe.kml.fire_data.type_one_point_frame(
            "Type 2 Incident",
        ),
        tests.helpers.factories.peri_scribe.kml.parsing.geometry_frame([]),
    )

    assert not fire.type_one


def test_fire_geometries_leaves_fire_unmarked_without_complexity_level() -> None:
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

    (fire,) = peri_scribe.kml.fire_data.fire_geometries(
        index,
        perimeters,
        tests.helpers.factories.peri_scribe.kml.fire_data.type_one_point_frame(None),
        tests.helpers.factories.peri_scribe.kml.parsing.geometry_frame([]),
    )

    assert not fire.type_one


def test_fire_geometries_leaves_fire_unmarked_without_point_attributes() -> None:
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

    (fire,) = peri_scribe.kml.fire_data.fire_geometries(
        index,
        perimeters,
        points,
        tests.helpers.factories.peri_scribe.kml.parsing.geometry_frame([]),
    )

    assert not fire.type_one


def test_fire_geometries_matches_score_explanation_by_identifier() -> None:
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
    big, small = peri_scribe.kml.fire_data.fire_geometries(
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


def test_fire_geometries_skips_images_without_enough_dates() -> None:
    index = tests.helpers.factories.peri_scribe.kml.parsing.fire_index([
        tests.helpers.factories.peri_scribe.kml.parsing.fire_index_entry(
            "Bug",
            "active",
            identifier="id-bug",
        ),
    ])
    fires = peri_scribe.kml.fire_data.fire_geometries(
        index,
        tests.helpers.factories.peri_scribe.kml.parsing.geometry_frame([
            ("id-bug", "Bug", tests.helpers.factories.geometry.square(1.0)),
        ]),
        tests.helpers.factories.peri_scribe.kml.parsing.geometry_frame([]),
        tests.helpers.factories.peri_scribe.kml.parsing.geometry_frame([]),
    )
    (fire,) = fires
    assert fire.images == ()


def test_fire_geometries_includes_progression_rings() -> None:
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
    fires = peri_scribe.kml.fire_data.fire_geometries(
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
        peri_scribe.units.area(ring.geometry) for ring in fire.progression_rings
    ]


def test_fire_geometries_drops_tiny_rings() -> None:
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
    fires = peri_scribe.kml.fire_data.fire_geometries(
        index,
        tests.helpers.factories.peri_scribe.kml.parsing.geometry_frame([]),
        tests.helpers.factories.peri_scribe.kml.parsing.geometry_frame([]),
        rings,
    )
    (fire,) = fires
    assert [ring.geometry for ring in fire.progression_rings] == [
        tests.helpers.factories.geometry.square(1.0),
    ]


def test_ring_added_areas_measure_disjoint_rings_own_areas() -> None:
    first_geometry = tests.helpers.factories.geometry.square(1.0)
    second_geometry = shapely.geometry.box(2.0, -0.5, 3.0, 0.5)
    added_areas_in_acres = peri_scribe.kml.fire_data.ring_added_areas((
        peri_scribe.perimeters.progression.Ring(
            geometry=first_geometry,
            observation_time=None,
        ),
        peri_scribe.perimeters.progression.Ring(
            geometry=second_geometry,
            observation_time=None,
        ),
    ))
    magnitudes = [area.m_as("meters ** 2") for area in added_areas_in_acres]
    assert magnitudes == pytest.approx([
        peri_scribe.units.area(first_geometry).m_as("meters ** 2"),
        peri_scribe.units.area(second_geometry).m_as("meters ** 2"),
    ])


def test_ring_added_areas_measure_net_of_earlier_fire_when_overlapping() -> None:
    inner_geometry = tests.helpers.factories.geometry.square(1.0)
    outer_geometry = tests.helpers.factories.geometry.square(2.0)
    inner_area = peri_scribe.units.area(inner_geometry)
    added_areas_in_acres = peri_scribe.kml.fire_data.ring_added_areas((
        peri_scribe.perimeters.progression.Ring(
            geometry=inner_geometry,
            observation_time=None,
        ),
        peri_scribe.perimeters.progression.Ring(
            geometry=outer_geometry,
            observation_time=None,
        ),
    ))
    # The outer ring redraws the ground the inner ring already claimed, so it adds only
    # the area beyond the earlier fire rather than its whole geometry.
    magnitudes = [area.m_as("meters ** 2") for area in added_areas_in_acres]
    assert magnitudes == pytest.approx([
        inner_area.m_as("meters ** 2"),
        (peri_scribe.units.area(outer_geometry) - inner_area).m_as("meters ** 2"),
    ])


def test_ring_added_areas_returns_nothing_without_rings() -> None:
    assert peri_scribe.kml.fire_data.ring_added_areas(()) == ()


def test_ring_added_areas_measure_zero_for_ground_already_claimed() -> None:
    geometry = tests.helpers.factories.geometry.square(1.0)
    added_areas_in_acres = peri_scribe.kml.fire_data.ring_added_areas((
        peri_scribe.perimeters.progression.Ring(
            geometry=geometry,
            observation_time=None,
        ),
        peri_scribe.perimeters.progression.Ring(
            geometry=geometry,
            observation_time=None,
        ),
    ))
    magnitudes = [area.m_as("meters ** 2") for area in added_areas_in_acres]
    assert magnitudes == pytest.approx(
        [peri_scribe.units.area(geometry).m_as("meters ** 2"), 0.0],
        abs=1e-6,
    )


def test_interior_ring_colors_draws_only_dated_rings() -> None:
    first_time = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    second_time = datetime.datetime(2026, 1, 2, tzinfo=datetime.UTC)
    first_ring = (
        tests.helpers.factories.peri_scribe.kml.fire_data.dated_progression_ring(
            1.0,
            first_time,
        )
    )
    second_ring = (
        tests.helpers.factories.peri_scribe.kml.fire_data.dated_progression_ring(
            2.0,
            second_time,
        )
    )
    undated_ring = peri_scribe.perimeters.progression.Ring(
        geometry=tests.helpers.factories.geometry.square(3.0),
        observation_time=None,
    )
    drawn = peri_scribe.kml.fire_data.interior_ring_colors(
        (first_ring, undated_ring, second_ring),
        (
            tests.helpers.factories.peri_scribe.kml.parsing.perimeter_with_time(
                tests.helpers.factories.geometry.square(4.0),
            ),
        ),
    )
    assert [ring for ring, _color in drawn] == [first_ring, second_ring]
    assert [color for _ring, color in drawn] == [
        peri_scribe.kml.colormap.color_hex(rgb)
        for _ring, rgb in peri_scribe.kml.colormap.progression_ring_colors((
            first_ring,
            second_ring,
        ))
    ]


def test_interior_ring_colors_falls_back_to_latest_perimeter_without_dated_rings() -> (
    None
):
    first_time = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    second_time = datetime.datetime(2026, 1, 2, tzinfo=datetime.UTC)
    first_geometry = tests.helpers.factories.geometry.square(1.0)
    latest_geometry = tests.helpers.factories.geometry.square(2.0)
    undated_ring = peri_scribe.perimeters.progression.Ring(
        geometry=tests.helpers.factories.geometry.square(3.0),
        observation_time=None,
    )
    ((ring, color),) = peri_scribe.kml.fire_data.interior_ring_colors(
        (undated_ring,),
        (
            tests.helpers.factories.peri_scribe.kml.parsing.perimeter_with_time(
                first_geometry,
                first_time,
            ),
            tests.helpers.factories.peri_scribe.kml.parsing.perimeter_with_time(
                latest_geometry,
                second_time,
            ),
        ),
    )
    assert ring.geometry == latest_geometry
    assert ring.observation_time == second_time
    assert color == peri_scribe.kml.colormap.color_hex(
        peri_scribe.kml.colormap.TURBO_RAMP[-1],
    )


def test_interior_ring_colors_returns_nothing_without_rings_or_perimeters() -> None:
    assert peri_scribe.kml.fire_data.interior_ring_colors((), ()) == ()


@pytest.mark.usefixtures("isolated_added_area_cache")
def test_precompute_interior_added_areas_warms_drawn_ring_sequences() -> None:
    first_time = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    second_time = datetime.datetime(2026, 1, 2, tzinfo=datetime.UTC)
    first_ring = (
        tests.helpers.factories.peri_scribe.kml.fire_data.dated_progression_ring(
            1.0,
            first_time,
        )
    )
    second_ring = (
        tests.helpers.factories.peri_scribe.kml.fire_data.dated_progression_ring(
            2.0,
            second_time,
        )
    )
    entry = tests.helpers.factories.peri_scribe.kml.parsing.fire_index_entry(
        "Bug",
        "active",
        identifier="id-bug",
    )
    pending: list[peri_scribe.kml.fire_data.PendingFire] = [
        peri_scribe.kml.fire_data.PendingFire(
            entry=entry,
            identifiers=frozenset({"id-bug"}),
            perimeters=(),
            progression_rings=(first_ring, second_ring),
            perimeter_positions=(),
            point_positions=(),
        ),
    ]
    cache = peri_scribe.kml.fire_data.added_areas_for_rings
    before = cache.cache_info().currsize
    peri_scribe.kml.fire_data.precompute_interior_added_areas(pending)
    assert cache.cache_info().currsize == before + 1
    hits_before = cache.cache_info().hits
    added_areas = peri_scribe.kml.fire_data.ring_added_areas((first_ring, second_ring))
    assert cache.cache_info().hits == hits_before + 1
    magnitudes = [area.m_as("meters ** 2") for area in added_areas]
    first_added, second_added = magnitudes
    assert 0 < first_added < second_added


@pytest.mark.usefixtures("isolated_added_area_cache")
def test_precompute_interior_added_areas_warms_latest_perimeter_fallback() -> None:
    observation_time = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    entry = tests.helpers.factories.peri_scribe.kml.parsing.fire_index_entry(
        "Bug",
        "active",
        identifier="id-bug",
    )
    pending: list[peri_scribe.kml.fire_data.PendingFire] = [
        peri_scribe.kml.fire_data.PendingFire(
            entry=entry,
            identifiers=frozenset({"id-bug"}),
            perimeters=(
                tests.helpers.factories.peri_scribe.kml.parsing.perimeter_with_time(
                    tests.helpers.factories.geometry.square(2.0),
                    observation_time,
                ),
            ),
            progression_rings=(),
            perimeter_positions=(),
            point_positions=(),
        ),
    ]
    cache = peri_scribe.kml.fire_data.added_areas_for_rings
    before = cache.cache_info().currsize
    peri_scribe.kml.fire_data.precompute_interior_added_areas(pending)
    assert cache.cache_info().currsize == before + 1


@pytest.mark.usefixtures("isolated_added_area_cache")
def test_precompute_interior_added_areas_leaves_fire_without_drawn_rings_alone() -> (
    None
):
    entry = tests.helpers.factories.peri_scribe.kml.parsing.fire_index_entry(
        "Bug",
        "active",
        identifier="id-bug",
    )
    pending: list[peri_scribe.kml.fire_data.PendingFire] = [
        peri_scribe.kml.fire_data.PendingFire(
            entry=entry,
            identifiers=frozenset({"id-bug"}),
            perimeters=(),
            progression_rings=(),
            perimeter_positions=(),
            point_positions=(),
        ),
    ]
    cache = peri_scribe.kml.fire_data.added_areas_for_rings
    before = cache.cache_info().currsize
    peri_scribe.kml.fire_data.precompute_interior_added_areas(pending)
    assert cache.cache_info().currsize == before


@pytest.mark.usefixtures("isolated_added_area_cache")
def test_added_areas_for_rings_reuses_only_the_exact_stored_sequence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shapes = (
        tests.helpers.factories.geometry.square(1),
        tests.helpers.factories.geometry.square(2),
    )
    measured = peri_scribe.perimeters.progression.added_areas(shapes)
    digest = peri_scribe.perimeters.progression.sequence_digest(shapes)
    rings = tuple(
        peri_scribe.perimeters.progression.Ring(
            geometry=geometry,
            observation_time=None,
            added_area=area,
            sequence_digest=digest,
        )
        for geometry, area in zip(shapes, measured, strict=True)
    )
    calls: list[tuple[shapely.geometry.base.BaseGeometry, ...]] = []
    original = peri_scribe.perimeters.progression.added_areas

    tracked = tests.helpers.doubles.peri_scribe.kml.fire_data.make_added_area_recorder(
        calls=calls,
        original=original,
    )

    monkeypatch.setattr(peri_scribe.perimeters.progression, "added_areas", tracked)
    assert peri_scribe.kml.fire_data.added_areas_for_rings(rings) == measured
    assert calls == []
    assert peri_scribe.kml.fire_data.added_areas_for_rings(rings[1:]) == original(
        shapes[1:],
    )
    assert calls == [shapes[1:]]


def test_fire_geometries_uses_independent_incident_history() -> None:
    index = tests.helpers.factories.peri_scribe.kml.parsing.fire_index([
        tests.helpers.factories.peri_scribe.kml.parsing.fire_index_entry(
            "Bug",
            "active",
            identifier="id-bug",
        ),
    ])
    empty = tests.helpers.factories.peri_scribe.kml.parsing.geometry_frame([])
    incidents = tests.helpers.factories.geography.geo_frame(
        {
            "fire_identifier": ["id-bug", "id-bug"],
            "fire_name": ["Bug", "Bug"],
            "observation_time": [
                tests.helpers.factories.time.utc(2026, 9, day, 0) for day in (1, 2)
            ],
            "incident_size": [100, 200],
            "estimated_cost_to_date": [1000, 2000],
            "report_confirmed": [False, False],
        },
        [None, None],
    )
    fires = peri_scribe.kml.fire_data.fire_geometries(
        index,
        empty,
        empty,
        empty,
        incident_rows=incidents,
    )
    description = fires[0].description
    assert description is not None
    assert description.area is not None
    assert description.area.m_as("acres") == pytest.approx(200)
    assert description.area_basis is not None
    assert description.area_basis.startswith("Reported;")
    assert [item.filename for item in fires[0].images] == [
        "id-bug-area.svg",
        "id-bug-cost.svg",
    ]
