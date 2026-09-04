"""Tests for peri_scribe.kml.fire_data."""

from __future__ import annotations

import datetime
import json

import geopandas
import pytest
import shapely.geometry

import peri_scribe.kml.fire_data
import peri_scribe.kml.selection
import peri_scribe.kml.text
import peri_scribe.models
import peri_scribe.perimeters.progression
import peri_scribe.units
import tests.peri_scribe.kml.kml_helpers


def test_identifiers_includes_identifier_and_aliases() -> None:
    entry = tests.peri_scribe.kml.kml_helpers.fire_index_entry(
        "Sorrento",
        "active",
        identifier="2026-casnd-150541",
        aliases=["2026-casnd-26150541", "guid"],
    )
    assert peri_scribe.kml.selection.identifiers(entry) == {
        "2026-casnd-150541",
        "2026-casnd-26150541",
        "guid",
    }


def test_identifiers_omits_none_identifier() -> None:
    entry = tests.peri_scribe.kml.kml_helpers.fire_index_entry(
        "Bug",
        "active",
        identifier=None,
    )
    assert peri_scribe.kml.selection.identifiers(entry) == frozenset()


def test_unique_filename_prefix_uses_identifier() -> None:
    assert (
        peri_scribe.kml.selection.unique_filename_prefix(
            "id-bug",
            "Bug",
            frozenset(),
        )
        == "id-bug"
    )


def test_unique_filename_prefix_avoids_collisions() -> None:
    assert (
        peri_scribe.kml.selection.unique_filename_prefix(
            None,
            "Bug",
            frozenset({"bug"}),
        )
        == "bug-2"
    )
    assert (
        peri_scribe.kml.selection.unique_filename_prefix(
            None,
            "Bug",
            frozenset({"bug", "bug-2"}),
        )
        == "bug-3"
    )


def test_perimeter_groups_keys_by_identifier_and_preserves_order() -> None:
    first = tests.peri_scribe.kml.kml_helpers.square(1.0)
    second = tests.peri_scribe.kml.kml_helpers.square(2.0)
    nameless = tests.peri_scribe.kml.kml_helpers.square(3.0)
    first_time = datetime.datetime(2026, 8, 5, tzinfo=datetime.UTC)
    second_time = datetime.datetime(2026, 8, 6, tzinfo=datetime.UTC)
    perimeters = tests.peri_scribe.kml.kml_helpers.geometry_frame(
        [
            ("id-a", "Bug", first),
            ("id-a", "Bug", second),
            (None, "Nameless", nameless),
        ],
        observation_times=[first_time, second_time, None],
    )
    by_identifier, by_name = peri_scribe.kml.selection.perimeter_groups(perimeters)
    assert by_identifier == {
        "id-a": [
            tests.peri_scribe.kml.kml_helpers.perimeter_with_time(first, first_time),
            tests.peri_scribe.kml.kml_helpers.perimeter_with_time(second, second_time),
        ],
    }
    assert by_name == {
        "Nameless": [
            tests.peri_scribe.kml.kml_helpers.perimeter_with_time(nameless, None),
        ],
    }


def test_point_locations_keep_last_point_per_fire() -> None:
    earlier = shapely.geometry.Point(1.0, 1.0)
    later = shapely.geometry.Point(2.0, 2.0)
    points = tests.peri_scribe.kml.kml_helpers.geometry_frame([
        ("id-a", "Bug", earlier),
        ("id-a", "Bug", later),
        (None, "Nameless", shapely.geometry.Point(3.0, 3.0)),
    ])
    by_identifier, by_name = peri_scribe.kml.selection.point_locations(points)
    assert by_identifier == {"id-a": later}
    assert list(by_name) == ["Nameless"]


def test_fire_point_matches_identifier() -> None:
    point = shapely.geometry.Point(1.0, 1.0)
    result = peri_scribe.kml.selection.fire_point(
        frozenset({"id-a"}),
        "Bug",
        {"id-a": point},
        {},
    )
    assert result is point


def test_fire_point_falls_back_to_name() -> None:
    point = shapely.geometry.Point(1.0, 1.0)
    result = peri_scribe.kml.selection.fire_point(
        frozenset(),
        "Bug",
        {},
        {"Bug": point},
    )
    assert result is point


def test_fire_point_returns_none_when_name_missing() -> None:
    assert peri_scribe.kml.selection.fire_point(frozenset(), "Bug", {}, {}) is None


def test_fire_point_returns_none_when_identifier_missing() -> None:
    assert (
        peri_scribe.kml.selection.fire_point(
            frozenset({"id-a"}),
            "Bug",
            {},
            {},
        )
        is None
    )


def test_fire_perimeters_matches_identifier() -> None:
    perimeters = (
        tests.peri_scribe.kml.kml_helpers.perimeter_with_time(
            tests.peri_scribe.kml.kml_helpers.square(1.0),
        ),
        tests.peri_scribe.kml.kml_helpers.perimeter_with_time(
            tests.peri_scribe.kml.kml_helpers.square(2.0),
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
        tests.peri_scribe.kml.kml_helpers.perimeter_with_time(
            tests.peri_scribe.kml.kml_helpers.square(1.0),
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
        peri_scribe.kml.fire_data.fire_perimeters(
            frozenset({"id-a"}),
            "Bug",
            {},
            {},
        )
        == ()
    )


def area_frame(
    column: str,
    rows: list[tuple[str | None, str]],
    values: list[float | None],
) -> geopandas.GeoDataFrame:
    """Build a history frame with one area column populated.

    Args:
        column: The area column to add.
        rows: The identifier and name of each row.
        values: The area value of each row.

    Returns:
        The rows as a GeoDataFrame with *column* populated.
    """
    return geopandas.GeoDataFrame(
        {
            "fire_identifier": [identifier for identifier, _name in rows],
            "fire_name": [name for _identifier, name in rows],
            column: values,
        },
        geometry=[shapely.geometry.Point(0.0, 0.0) for _row in rows],
        crs="EPSG:4326",
    )


def test_fire_area_key_keys_by_identifier() -> None:
    assert peri_scribe.kml.selection.fire_area_key("id-bug", "Bug") == (
        "id",
        "id-bug",
    )


def test_fire_area_key_keys_by_name_when_identifier_missing() -> None:
    assert peri_scribe.kml.selection.fire_area_key(None, "Bug") == ("name", "Bug")


def test_fires_with_qualifying_area_keeps_fire_at_minimum() -> None:
    perimeters = area_frame(
        "area_acres",
        [("id-bug", "Bug")],
        [peri_scribe.kml.selection.MINIMUM_FIRE_AREA_IN_ACRES],
    )
    points = area_frame("incident_size", [("id-bug", "Bug")], [None])
    assert peri_scribe.kml.selection.fires_with_qualifying_area(
        perimeters,
        points,
        peri_scribe.kml.selection.MINIMUM_FIRE_AREA_IN_ACRES,
    ) == {("id", "id-bug")}


def test_fires_with_qualifying_area_keeps_fire_with_reported_area() -> None:
    perimeters = tests.peri_scribe.kml.kml_helpers.geometry_frame([])
    points = area_frame(
        "discovery_acres",
        [("id-bug", "Bug")],
        [100.0],
    )
    assert peri_scribe.kml.selection.fires_with_qualifying_area(
        perimeters,
        points,
        peri_scribe.kml.selection.MINIMUM_FIRE_AREA_IN_ACRES,
    ) == {("id", "id-bug")}


def test_fires_with_qualifying_area_keeps_fire_with_any_qualifying_indication() -> None:
    perimeters = area_frame(
        "area_acres",
        [("id-bug", "Bug")],
        [10.0],
    )
    points = area_frame(
        "incident_size",
        [("id-bug", "Bug")],
        [30.0],
    )
    assert peri_scribe.kml.selection.fires_with_qualifying_area(
        perimeters,
        points,
        peri_scribe.kml.selection.MINIMUM_FIRE_AREA_IN_ACRES,
    ) == {("id", "id-bug")}


def test_fires_with_qualifying_area_excludes_fire_below_minimum() -> None:
    perimeters = area_frame(
        "area_acres",
        [("id-bug", "Bug")],
        [10.0],
    )
    points = area_frame(
        "final_acres",
        [("id-bug", "Bug")],
        [20.0],
    )
    assert (
        peri_scribe.kml.selection.fires_with_qualifying_area(
            perimeters,
            points,
            peri_scribe.kml.selection.MINIMUM_FIRE_AREA_IN_ACRES,
        )
        == frozenset()
    )


def test_fires_with_qualifying_area_excludes_fire_with_missing_areas() -> None:
    perimeters = area_frame(
        "area_acres",
        [("id-bug", "Bug")],
        [None],
    )
    points = area_frame(
        "incident_size",
        [("id-bug", "Bug")],
        [None],
    )
    assert (
        peri_scribe.kml.selection.fires_with_qualifying_area(
            perimeters,
            points,
            peri_scribe.kml.selection.MINIMUM_FIRE_AREA_IN_ACRES,
        )
        == frozenset()
    )


def test_fires_with_qualifying_area_excludes_fire_without_area_columns() -> None:
    perimeters = tests.peri_scribe.kml.kml_helpers.geometry_frame([
        ("id-bug", "Bug", shapely.geometry.Point(0.0, 0.0)),
    ])
    points = tests.peri_scribe.kml.kml_helpers.geometry_frame([])
    assert (
        peri_scribe.kml.selection.fires_with_qualifying_area(
            perimeters,
            points,
            peri_scribe.kml.selection.MINIMUM_FIRE_AREA_IN_ACRES,
        )
        == frozenset()
    )


def test_fire_qualifies_matches_any_identifier() -> None:
    assert peri_scribe.kml.selection.fire_qualifies(
        frozenset({"id-alias", "id-bug"}),
        "Bug",
        frozenset({("id", "id-bug")}),
    )


def test_fire_qualifies_matches_name_when_no_identifier() -> None:
    assert peri_scribe.kml.selection.fire_qualifies(
        frozenset(),
        "Bug",
        frozenset({("name", "Bug")}),
    )


def test_fire_qualifies_rejects_unmatched_fire() -> None:
    assert not peri_scribe.kml.selection.fire_qualifies(
        frozenset({"id-bug"}),
        "Bug",
        frozenset({("id", "id-other"), ("name", "Bug")}),
    )


def test_fire_geometries_matches_aliases_and_sorts_by_name() -> None:
    index = tests.peri_scribe.kml.kml_helpers.fire_index([
        tests.peri_scribe.kml.kml_helpers.fire_index_entry(
            "Sorrento",
            "active",
            identifier="2026-casnd-150541",
            aliases=["2026-casnd-26150541"],
        ),
        tests.peri_scribe.kml.kml_helpers.fire_index_entry(
            "Bug",
            "inactive",
            identifier="id-bug",
        ),
    ])
    sorrento_perimeter = tests.peri_scribe.kml.kml_helpers.square(3.0)
    perimeters = tests.peri_scribe.kml.kml_helpers.geometry_frame([
        ("2026-casnd-26150541", "Sorrento", sorrento_perimeter),
        ("id-bug", "Bug", tests.peri_scribe.kml.kml_helpers.square(1.0)),
    ])
    bug_point = shapely.geometry.Point(1.0, 1.0)
    points = tests.peri_scribe.kml.kml_helpers.geometry_frame([
        ("id-bug", "Bug", bug_point),
    ])
    fires = peri_scribe.kml.fire_data.fire_geometries(
        index,
        perimeters,
        points,
        tests.peri_scribe.kml.kml_helpers.geometry_frame([]),
    )
    assert [fire.name for fire in fires] == ["Bug", "Sorrento"]
    bug, sorrento = fires
    assert bug.status is peri_scribe.models.FireStatus.INACTIVE
    assert bug.point is bug_point
    assert bug.perimeters == (
        tests.peri_scribe.kml.kml_helpers.perimeter_with_time(
            tests.peri_scribe.kml.kml_helpers.square(1.0),
        ),
    )
    assert sorrento.status is peri_scribe.models.FireStatus.ACTIVE
    assert sorrento.point == sorrento_perimeter.representative_point()
    assert sorrento.perimeters == (
        tests.peri_scribe.kml.kml_helpers.perimeter_with_time(sorrento_perimeter),
    )


def test_fire_point_location_uses_known_point() -> None:
    point = shapely.geometry.Point(1.0, 1.0)
    result = peri_scribe.kml.selection.fire_point_location(
        frozenset({"id-a"}),
        "Bug",
        {"id-a": point},
        {},
        (
            tests.peri_scribe.kml.kml_helpers.perimeter_with_time(
                tests.peri_scribe.kml.kml_helpers.square(2.0),
            ),
        ),
    )
    assert result is point


def test_fire_point_location_derives_point_from_latest_perimeter() -> None:
    earlier = tests.peri_scribe.kml.kml_helpers.square(1.0)
    latest = tests.peri_scribe.kml.kml_helpers.square(2.0)
    result = peri_scribe.kml.selection.fire_point_location(
        frozenset({"id-a"}),
        "Bug",
        {},
        {},
        (
            tests.peri_scribe.kml.kml_helpers.perimeter_with_time(earlier),
            tests.peri_scribe.kml.kml_helpers.perimeter_with_time(latest),
        ),
    )
    assert result == latest.representative_point()


def test_fire_point_location_returns_none_without_geometry() -> None:
    assert (
        peri_scribe.kml.selection.fire_point_location(
            frozenset({"id-a"}),
            "Bug",
            {},
            {},
            (),
        )
        is None
    )


def test_fire_geometries_derives_point_for_inactive_fire_without_location() -> None:
    index = tests.peri_scribe.kml.kml_helpers.fire_index([
        tests.peri_scribe.kml.kml_helpers.fire_index_entry(
            "ALTA",
            "inactive",
            identifier="id-alta",
        ),
    ])
    perimeter = tests.peri_scribe.kml.kml_helpers.square(2.0)
    fires = peri_scribe.kml.fire_data.fire_geometries(
        index,
        tests.peri_scribe.kml.kml_helpers.geometry_frame([
            ("id-alta", "ALTA", perimeter),
        ]),
        tests.peri_scribe.kml.kml_helpers.geometry_frame([]),
        tests.peri_scribe.kml.kml_helpers.geometry_frame([]),
    )
    (fire,) = fires
    assert fire.status is peri_scribe.models.FireStatus.INACTIVE
    assert fire.point == perimeter.representative_point()
    assert fire.perimeters == (
        tests.peri_scribe.kml.kml_helpers.perimeter_with_time(perimeter),
    )


def test_fire_geometries_sorts_by_case_folded_name() -> None:
    index = tests.peri_scribe.kml.kml_helpers.fire_index([
        tests.peri_scribe.kml.kml_helpers.fire_index_entry(
            name,
            "active",
            identifier=f"id-{name}",
        )
        for name in ("aB", "Ac", "AD", "ae")
    ])
    fires = peri_scribe.kml.fire_data.fire_geometries(
        index,
        tests.peri_scribe.kml.kml_helpers.geometry_frame([]),
        tests.peri_scribe.kml.kml_helpers.geometry_frame([]),
        tests.peri_scribe.kml.kml_helpers.geometry_frame([]),
    )
    assert [fire.name for fire in fires] == ["aB", "Ac", "AD", "ae"]


def test_fire_geometries_attaches_plot_images(
    in_process_plot_image_bundles: None,
) -> None:
    index = tests.peri_scribe.kml.kml_helpers.fire_index([
        tests.peri_scribe.kml.kml_helpers.fire_index_entry(
            "Bug",
            "active",
            identifier="id-bug",
        ),
    ])
    perimeters = tests.peri_scribe.kml.kml_helpers.geometry_frame(
        [
            ("id-bug", "Bug", tests.peri_scribe.kml.kml_helpers.square(1.0)),
            ("id-bug", "Bug", tests.peri_scribe.kml.kml_helpers.square(2.0)),
        ],
        observation_times=[
            datetime.datetime(2026, 8, 5, 20, 0, tzinfo=datetime.UTC),
            datetime.datetime(2026, 8, 6, 20, 0, tzinfo=datetime.UTC),
        ],
    )
    fires = peri_scribe.kml.fire_data.fire_geometries(
        index,
        perimeters,
        tests.peri_scribe.kml.kml_helpers.geometry_frame([]),
        tests.peri_scribe.kml.kml_helpers.geometry_frame([]),
    )
    (fire,) = fires
    assert [image.filename for image in fire.images] == ["id-bug-perimeter.png"]
    assert fire.images[0].content
    assert fire.description is not None
    assert fire.description.identifier == "id-bug"


def test_fire_geometries_skips_plot_images_when_render_plots_is_false(
    in_process_plot_image_bundles: None,
) -> None:
    index = tests.peri_scribe.kml.kml_helpers.fire_index([
        tests.peri_scribe.kml.kml_helpers.fire_index_entry(
            "Bug",
            "active",
            identifier="id-bug",
        ),
    ])
    perimeters = tests.peri_scribe.kml.kml_helpers.geometry_frame(
        [
            ("id-bug", "Bug", tests.peri_scribe.kml.kml_helpers.square(1.0)),
            ("id-bug", "Bug", tests.peri_scribe.kml.kml_helpers.square(2.0)),
        ],
        observation_times=[
            datetime.datetime(2026, 8, 5, 20, 0, tzinfo=datetime.UTC),
            datetime.datetime(2026, 8, 6, 20, 0, tzinfo=datetime.UTC),
        ],
    )
    fires = peri_scribe.kml.fire_data.fire_geometries(
        index,
        perimeters,
        tests.peri_scribe.kml.kml_helpers.geometry_frame([]),
        tests.peri_scribe.kml.kml_helpers.geometry_frame([]),
        render_plots=False,
    )
    (fire,) = fires
    assert fire.images == ()
    assert fire.description is not None
    assert fire.description.identifier == "id-bug"


def test_fire_geometries_matches_identifier_less_fire_by_name(
    in_process_plot_image_bundles: None,
) -> None:
    index = tests.peri_scribe.kml.kml_helpers.fire_index([
        tests.peri_scribe.kml.kml_helpers.fire_index_entry(
            "Bug",
            "active",
        ),
    ])
    # The fire has no identifier, yet its history rows carry one; the name match must
    # still include those rows for the plots and description.
    perimeters = tests.peri_scribe.kml.kml_helpers.geometry_frame(
        [
            ("id-bug", "Bug", tests.peri_scribe.kml.kml_helpers.square(1.0)),
            ("id-bug", "Bug", tests.peri_scribe.kml.kml_helpers.square(2.0)),
        ],
        observation_times=[
            datetime.datetime(2026, 8, 5, 20, 0, tzinfo=datetime.UTC),
            datetime.datetime(2026, 8, 6, 20, 0, tzinfo=datetime.UTC),
        ],
        area_acres=[10.0, 20.0],
    )
    (fire,) = peri_scribe.kml.fire_data.fire_geometries(
        index,
        perimeters,
        tests.peri_scribe.kml.kml_helpers.geometry_frame([]),
        tests.peri_scribe.kml.kml_helpers.geometry_frame([]),
    )
    assert fire.name == "Bug"
    assert fire.images
    assert fire.description is not None
    assert fire.description.area_in_acres == pytest.approx(20.0)


def test_score_explanation_for_prefers_identifier() -> None:
    assert (
        peri_scribe.kml.text.score_explanation_for(
            {"id-big": "Over 250 structures within a mile."},
            {"Timber": "Over 5 structures within a mile."},
            frozenset({"id-big"}),
            "Timber",
        )
        == "Over 250 structures within a mile."
    )


def test_score_explanation_for_matches_any_identifier() -> None:
    assert (
        peri_scribe.kml.text.score_explanation_for(
            {"id-big": "Over 250 structures within a mile."},
            {},
            frozenset({"alias", "id-big"}),
            "Timber",
        )
        == "Over 250 structures within a mile."
    )


def test_score_explanation_for_falls_back_to_name() -> None:
    assert (
        peri_scribe.kml.text.score_explanation_for(
            {},
            {"Timber": "Over 5 structures within a mile."},
            frozenset(),
            "Timber",
        )
        == "Over 5 structures within a mile."
    )


def test_score_explanation_for_returns_none_without_match() -> None:
    assert (
        peri_scribe.kml.text.score_explanation_for(
            {},
            {},
            frozenset({"id-other"}),
            "Timber",
        )
        is None
    )


def test_fire_geometries_puts_score_explanation_in_balloon() -> None:
    index = tests.peri_scribe.kml.kml_helpers.fire_index([
        tests.peri_scribe.kml.kml_helpers.fire_index_entry(
            "Bug",
            "active",
            identifier="id-bug",
        ),
    ])
    perimeters = tests.peri_scribe.kml.kml_helpers.geometry_frame([
        ("id-bug", "Bug", tests.peri_scribe.kml.kml_helpers.square(1.0)),
    ])
    scores = peri_scribe.models.FireScores(
        version="test",
        fires=[
            peri_scribe.models.FireScoreEntry(
                name="Bug",
                identifier="id-bug",
                score=389,
                components=peri_scribe.models.FireScoreComponents(
                    size=135,
                    growth=60,
                    first_mapping=33,
                    buildings=8,
                    evacuation=33,
                    importance=120,
                ),
                explanation="Over 100,000 acres, and a Type 1 Incident.",
            ),
        ],
    )
    (with_scores,) = peri_scribe.kml.fire_data.fire_geometries(
        index,
        perimeters,
        tests.peri_scribe.kml.kml_helpers.geometry_frame([]),
        tests.peri_scribe.kml.kml_helpers.geometry_frame([]),
        scores=scores,
    )
    assert with_scores.description is not None
    assert (
        with_scores.description.of_note == "Over 100,000 acres, and a Type 1 Incident."
    )
    (without_scores,) = peri_scribe.kml.fire_data.fire_geometries(
        index,
        perimeters,
        tests.peri_scribe.kml.kml_helpers.geometry_frame([]),
        tests.peri_scribe.kml.kml_helpers.geometry_frame([]),
    )
    assert without_scores.description is not None
    assert without_scores.description.of_note is None


def test_fire_geometries_matches_score_explanation_by_identifier() -> None:
    index = tests.peri_scribe.kml.kml_helpers.fire_index([
        tests.peri_scribe.kml.kml_helpers.fire_index_entry(
            "Timber",
            "active",
            identifier="id-big",
        ),
        tests.peri_scribe.kml.kml_helpers.fire_index_entry(
            "Timber",
            "inactive",
            identifier="id-small",
        ),
    ])
    perimeters = tests.peri_scribe.kml.kml_helpers.geometry_frame([
        ("id-big", "Timber", tests.peri_scribe.kml.kml_helpers.square(2.0)),
        ("id-small", "Timber", tests.peri_scribe.kml.kml_helpers.square(1.0)),
    ])
    scores = peri_scribe.models.FireScores(
        version="test",
        fires=[
            peri_scribe.models.FireScoreEntry(
                name="Timber",
                identifier="id-small",
                score=4,
                components=peri_scribe.models.FireScoreComponents(
                    size=0,
                    growth=0,
                    first_mapping=0,
                    buildings=4,
                    evacuation=0,
                    importance=0,
                ),
                explanation="Over 5 structures within a mile.",
            ),
            peri_scribe.models.FireScoreEntry(
                name="Timber",
                identifier="id-big",
                score=470,
                components=peri_scribe.models.FireScoreComponents(
                    size=54,
                    growth=0,
                    first_mapping=11,
                    buildings=12,
                    evacuation=33,
                    importance=360,
                ),
                explanation=(
                    "Over 250 structures within a mile, and a Type 1 Incident."
                ),
            ),
        ],
    )
    big, small = peri_scribe.kml.fire_data.fire_geometries(
        index,
        perimeters,
        tests.peri_scribe.kml.kml_helpers.geometry_frame([]),
        tests.peri_scribe.kml.kml_helpers.geometry_frame([]),
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
    index = tests.peri_scribe.kml.kml_helpers.fire_index([
        tests.peri_scribe.kml.kml_helpers.fire_index_entry(
            "Bug",
            "active",
            identifier="id-bug",
        ),
    ])
    fires = peri_scribe.kml.fire_data.fire_geometries(
        index,
        tests.peri_scribe.kml.kml_helpers.geometry_frame([
            ("id-bug", "Bug", tests.peri_scribe.kml.kml_helpers.square(1.0)),
        ]),
        tests.peri_scribe.kml.kml_helpers.geometry_frame([]),
        tests.peri_scribe.kml.kml_helpers.geometry_frame([]),
    )
    (fire,) = fires
    assert fire.images == ()


def test_fire_geometries_includes_progression_rings() -> None:
    index = tests.peri_scribe.kml.kml_helpers.fire_index([
        tests.peri_scribe.kml.kml_helpers.fire_index_entry(
            "Bug",
            "active",
            identifier="id-bug",
        ),
    ])
    first_time = datetime.datetime(2026, 8, 5, 20, 0, tzinfo=datetime.UTC)
    second_time = datetime.datetime(2026, 8, 7, 20, 0, tzinfo=datetime.UTC)
    rings = tests.peri_scribe.kml.kml_helpers.geometry_frame(
        [
            ("id-bug", "Bug", tests.peri_scribe.kml.kml_helpers.square(1.0)),
            ("id-bug", "Bug", tests.peri_scribe.kml.kml_helpers.square(2.0)),
        ],
        observation_times=[first_time, second_time],
    )
    fires = peri_scribe.kml.fire_data.fire_geometries(
        index,
        tests.peri_scribe.kml.kml_helpers.geometry_frame([]),
        tests.peri_scribe.kml.kml_helpers.geometry_frame([]),
        rings,
    )
    (fire,) = fires
    assert [
        (ring.geometry, ring.observation_time) for ring in fire.progression_rings
    ] == [
        (tests.peri_scribe.kml.kml_helpers.square(1.0), first_time),
        (tests.peri_scribe.kml.kml_helpers.square(2.0), second_time),
    ]
    assert [ring.area for ring in fire.progression_rings] == [
        peri_scribe.units.area_in_square_meters(ring.geometry)
        for ring in fire.progression_rings
    ]


def test_fire_geometries_drops_tiny_rings() -> None:
    index = tests.peri_scribe.kml.kml_helpers.fire_index([
        tests.peri_scribe.kml.kml_helpers.fire_index_entry(
            "Bug",
            "active",
            identifier="id-bug",
        ),
    ])
    observation_time = datetime.datetime(2026, 8, 5, 20, 0, tzinfo=datetime.UTC)
    rings = tests.peri_scribe.kml.kml_helpers.geometry_frame(
        [
            ("id-bug", "Bug", tests.peri_scribe.kml.kml_helpers.square(1.0)),
            ("id-bug", "Bug", shapely.geometry.box(0.0, 0.0, 1e-6, 1e-6)),
        ],
        observation_times=[observation_time, observation_time],
    )
    fires = peri_scribe.kml.fire_data.fire_geometries(
        index,
        tests.peri_scribe.kml.kml_helpers.geometry_frame([]),
        tests.peri_scribe.kml.kml_helpers.geometry_frame([]),
        rings,
    )
    (fire,) = fires
    assert [ring.geometry for ring in fire.progression_rings] == [
        tests.peri_scribe.kml.kml_helpers.square(1.0),
    ]


def test_ring_added_areas_measure_disjoint_rings_own_areas() -> None:
    first_geometry = tests.peri_scribe.kml.kml_helpers.square(1.0)
    second_geometry = shapely.geometry.box(2.0, -0.5, 3.0, 0.5)
    added_areas_in_acres = peri_scribe.kml.fire_data.ring_added_areas_in_acres(
        (
            peri_scribe.perimeters.progression.Ring(
                geometry=first_geometry,
                observation_time=None,
            ),
            peri_scribe.perimeters.progression.Ring(
                geometry=second_geometry,
                observation_time=None,
            ),
        ),
    )
    assert added_areas_in_acres == pytest.approx(
        (
            peri_scribe.units.area_in_acres(first_geometry),
            peri_scribe.units.area_in_acres(second_geometry),
        ),
    )


def test_ring_added_areas_measure_net_of_earlier_fire_when_overlapping() -> None:
    inner_geometry = tests.peri_scribe.kml.kml_helpers.square(1.0)
    outer_geometry = tests.peri_scribe.kml.kml_helpers.square(2.0)
    inner_area_in_acres = peri_scribe.units.area_in_acres(inner_geometry)
    added_areas_in_acres = peri_scribe.kml.fire_data.ring_added_areas_in_acres(
        (
            peri_scribe.perimeters.progression.Ring(
                geometry=inner_geometry,
                observation_time=None,
            ),
            peri_scribe.perimeters.progression.Ring(
                geometry=outer_geometry,
                observation_time=None,
            ),
        ),
    )
    # The outer ring redraws the ground the inner ring already claimed, so it adds
    # only the area beyond the earlier fire rather than its whole geometry.
    assert added_areas_in_acres == pytest.approx(
        (
            inner_area_in_acres,
            peri_scribe.units.area_in_acres(outer_geometry) - inner_area_in_acres,
        ),
    )


def test_ring_added_areas_returns_nothing_without_rings() -> None:
    assert peri_scribe.kml.fire_data.ring_added_areas_in_acres(()) == ()


def test_ring_added_areas_measure_zero_for_ground_already_claimed() -> None:
    geometry = tests.peri_scribe.kml.kml_helpers.square(1.0)
    added_areas_in_acres = peri_scribe.kml.fire_data.ring_added_areas_in_acres(
        (
            peri_scribe.perimeters.progression.Ring(
                geometry=geometry,
                observation_time=None,
            ),
            peri_scribe.perimeters.progression.Ring(
                geometry=geometry,
                observation_time=None,
            ),
        ),
    )
    assert added_areas_in_acres == pytest.approx(
        (peri_scribe.units.area_in_acres(geometry), 0.0),
        abs=1e-6,
    )


def description_perimeter_frame() -> geopandas.GeoDataFrame:
    """Return a perimeter history frame with attribute columns populated.

    Returns:
        The frame.
    """
    return geopandas.GeoDataFrame(
        {
            "fire_identifier": ["id-bug", "id-bug"],
            "fire_name": ["Bug", "Bug"],
            "source": ["firis_perimeter", "firis_perimeter"],
            "mission": ["CA-BUG-1", "CA-BUG-2"],
            "area_acres": [10.0, 20.0],
            "percent_contained": [10.0, 20.0],
            "estimated_cost_to_date": [1000.0, 2000.0],
            "estimated_final_cost": [1500.0, 2500.0],
            "discovery_time": [
                datetime.datetime(2026, 6, 29, 12, 4, 46, tzinfo=datetime.UTC),
                datetime.datetime(2026, 6, 29, 12, 4, 46, tzinfo=datetime.UTC),
            ],
            "observation_time": [
                datetime.datetime(2026, 8, 5, 20, 0, tzinfo=datetime.UTC),
                datetime.datetime(2026, 8, 6, 20, 0, tzinfo=datetime.UTC),
            ],
            "source_attributes": [
                json.dumps(
                    {
                        "attr_InitialResponseDateTime": "2026-07-27T19:24:00",
                        "attr_IncidentComplexityLevel": "Type 4 Incident",
                        "attr_PrimaryFuelModel": "Timber (Litter and Understory)",
                        "attr_PredominantFuelModel": "GS1",
                        "attr_PredominantFuelGroup": "Grass",
                        "attr_FireBehaviorGeneral": "Active",
                        "attr_FireBehaviorGeneral2": "Running",
                        "attr_POOLandownerCategory": "Federal",
                        "attr_TotalIncidentPersonnel": 300,
                    },
                ),
                json.dumps(
                    {
                        "attr_InitialResponseDateTime": "2026-07-27T19:24:00",
                        "attr_IncidentComplexityLevel": "Type 4 Incident",
                        "attr_PrimaryFuelModel": "Timber (Litter and Understory)",
                        "attr_PredominantFuelModel": "GS1",
                        "attr_PredominantFuelGroup": "Grass",
                        "attr_FireBehaviorGeneral": "Active",
                        "attr_FireBehaviorGeneral2": "Running",
                        "attr_POOLandownerCategory": "Federal",
                        "attr_TotalIncidentPersonnel": 400,
                    },
                ),
            ],
        },
        geometry=[
            tests.peri_scribe.kml.kml_helpers.square(1.0),
            tests.peri_scribe.kml.kml_helpers.square(2.0),
        ],
        crs="EPSG:4326",
    )


def description_point_frame() -> geopandas.GeoDataFrame:
    """Return a point history frame with attribute columns populated.

    Returns:
        The frame.
    """
    return geopandas.GeoDataFrame(
        {
            "fire_identifier": ["id-bug"],
            "fire_name": ["Bug"],
            "incident_size": [30.0],
            "percent_contained": [30.0],
            "estimated_cost_to_date": [3000.0],
            "estimated_final_cost": [3500.0],
            "discovery_time": [
                datetime.datetime(2026, 6, 29, 12, 4, 46, tzinfo=datetime.UTC),
            ],
            "observation_time": [
                datetime.datetime(2026, 8, 6, 20, 0, tzinfo=datetime.UTC),
            ],
            "source_attributes": [
                json.dumps(
                    {
                        "POOJurisdictionalUnit": "CANOD",
                        "InitialResponseDateTime": "2026-07-27T19:24:00",
                        "IncidentTypeCategory": "WF",
                        "IncidentComplexityLevel": "Type 4 Incident",
                        "FireMgmtComplexity": "Type 5 Incident",
                        "OrganizationalAssessment": "Type 3 IC",
                        "SecondaryFuelModel": "Brush (2 feet)",
                        "PredominantFuelModel": "GS1",
                        "PredominantFuelGroup": "Grass",
                        "FireBehaviorGeneral": "Active",
                        "FireBehaviorGeneral1": "Creeping",
                        "FireBehaviorGeneral2": "Smoldering",
                        "FireBehaviorGeneral3": "Smoldering",
                        "TotalIncidentPersonnel": 500,
                    },
                ),
            ],
        },
        geometry=[shapely.geometry.Point(1.0, 1.0)],
        crs="EPSG:4326",
    )


def test_fire_description_prefers_latest_perimeter_values() -> None:
    entry = tests.peri_scribe.kml.kml_helpers.fire_index_entry(
        "Bug",
        "active",
        identifier="id-bug",
    )
    description = peri_scribe.kml.text.fire_description(
        entry,
        description_perimeter_frame(),
        description_point_frame(),
        of_note="Over 100,000 acres, and a Type 1 Incident.",
    )
    assert description.area_in_acres == pytest.approx(20.0)
    assert description.percent_contained == pytest.approx(20.0)
    assert description.estimated_cost_to_date_in_dollars == pytest.approx(2000.0)
    assert description.estimated_final_cost_in_dollars == pytest.approx(2500.0)
    # Personnel comes from the sources' attributes, where the point feed's value wins
    # when both feeds carry it.
    assert description.total_personnel == pytest.approx(500.0)
    assert description.mission == "CA-BUG-2"
    assert description.source == "FIRIS / NIFC"
    assert description.identifier == "id-bug"
    assert description.observation_time == datetime.datetime(
        2026,
        8,
        6,
        20,
        0,
        tzinfo=datetime.UTC,
    )
    assert description.initial_response_time == datetime.datetime(
        2026,
        7,
        27,
        19,
        24,
        tzinfo=datetime.UTC,
    )
    assert description.protecting_unit == "CANOD"
    assert description.exterior_perimeter_in_miles == pytest.approx(551.47, rel=0.01)
    assert description.incident_type == "WF"
    assert (
        description.incident_complexity == "Type 4 Incident; Type 5 Incident; Type 3 IC"
    )
    assert (
        description.fuel_model
        == "Timber (Litter and Understory); Brush (2 feet); GS1; Grass"
    )
    assert description.fire_behavior == "Active; Creeping; Smoldering; Running"
    assert description.landowner_category == "Federal"
    assert description.of_note == "Over 100,000 acres, and a Type 1 Incident."


def test_fire_description_falls_back_to_point_when_perimeter_missing() -> None:
    entry = tests.peri_scribe.kml.kml_helpers.fire_index_entry(
        "Bug",
        "active",
        identifier="id-bug",
    )
    empty_perimeters = geopandas.GeoDataFrame(
        {
            "fire_identifier": ["id-bug"],
            "fire_name": ["Bug"],
            "source": [None],
            "mission": [None],
            "area_acres": [None],
            "percent_contained": [None],
            "estimated_cost_to_date": [None],
            "estimated_final_cost": [None],
            "discovery_time": [None],
            "observation_time": [None],
            "source_attributes": [json.dumps({})],
        },
        geometry=[tests.peri_scribe.kml.kml_helpers.square(1.0)],
        crs="EPSG:4326",
    )
    description = peri_scribe.kml.text.fire_description(
        entry,
        empty_perimeters,
        description_point_frame(),
    )
    assert description.area_in_acres == pytest.approx(30.0)
    assert description.percent_contained == pytest.approx(30.0)
    assert description.estimated_cost_to_date_in_dollars == pytest.approx(3000.0)
    assert description.estimated_final_cost_in_dollars == pytest.approx(3500.0)
    assert description.total_personnel == pytest.approx(500.0)
    assert description.observation_time == datetime.datetime(
        2026,
        8,
        6,
        20,
        0,
        tzinfo=datetime.UTC,
    )
    assert description.initial_response_time == datetime.datetime(
        2026,
        7,
        27,
        19,
        24,
        tzinfo=datetime.UTC,
    )
    assert description.exterior_perimeter_in_miles == pytest.approx(275.75, rel=0.01)
    assert description.incident_type == "WF"
    assert (
        description.incident_complexity == "Type 4 Incident; Type 5 Incident; Type 3 IC"
    )
    assert description.fuel_model == "Brush (2 feet); GS1; Grass"
    assert description.fire_behavior == "Active; Creeping; Smoldering"
    assert description.landowner_category is None


def test_fire_description_falls_back_to_protecting_agency() -> None:
    entry = tests.peri_scribe.kml.kml_helpers.fire_index_entry(
        "Bug",
        "active",
        identifier="id-bug",
    )
    point_frame = geopandas.GeoDataFrame(
        {
            "fire_identifier": ["id-bug"],
            "fire_name": ["Bug"],
            "source_attributes": [json.dumps({"POOJurisdictionalAgency": "BLM"})],
        },
        geometry=[shapely.geometry.Point(1.0, 1.0)],
        crs="EPSG:4326",
    )
    description = peri_scribe.kml.text.fire_description(
        entry,
        tests.peri_scribe.kml.kml_helpers.geometry_frame([]),
        point_frame,
    )
    assert description.protecting_unit == "BLM"
    assert description.exterior_perimeter_in_miles is None


def test_fire_description_falls_back_to_perimeter_personnel() -> None:
    entry = tests.peri_scribe.kml.kml_helpers.fire_index_entry(
        "Bug",
        "active",
        identifier="id-bug",
    )
    perimeter_frame = geopandas.GeoDataFrame(
        {
            "fire_identifier": ["id-bug"],
            "fire_name": ["Bug"],
            "source_attributes": [
                json.dumps({"attr_TotalIncidentPersonnel": 400}),
            ],
        },
        geometry=[tests.peri_scribe.kml.kml_helpers.square(1.0)],
        crs="EPSG:4326",
    )
    point_frame = geopandas.GeoDataFrame(
        {
            "fire_identifier": ["id-bug"],
            "fire_name": ["Bug"],
            "source_attributes": [json.dumps({})],
        },
        geometry=[shapely.geometry.Point(1.0, 1.0)],
        crs="EPSG:4326",
    )
    description = peri_scribe.kml.text.fire_description(
        entry,
        perimeter_frame,
        point_frame,
    )
    assert description.total_personnel == pytest.approx(400.0)
