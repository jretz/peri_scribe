"""Area qualification uses the same evidence and history as the displayed estimate."""

from __future__ import annotations

import datetime
import re
import typing

import hypothesis
import shapely.geometry

import peri_scribe.geo.measurements
import peri_scribe.kml.fire_data
import peri_scribe.kml.selection
import peri_scribe.perimeters.progression
import peri_scribe.units
import tests.factories
import tests.peri_scribe.kml.fire_data_helpers
import tests.peri_scribe.kml.kml_helpers
import tests.peri_scribe.kml.selection_helpers
from peri_scribe.units import units


if typing.TYPE_CHECKING:
    import geopandas


@hypothesis.given(scenario=tests.peri_scribe.kml.selection_helpers.aliased_histories())
def test_area_groups_preserves_the_canonical_identity_partition(
    scenario: tuple[
        geopandas.GeoDataFrame,
        dict[str, str],
        dict[tuple[str, str], list[int]],
    ],
) -> None:
    frame, aliases, expected = scenario
    groups = peri_scribe.kml.selection.area_groups(frame, aliases)
    assert {key: group["row_id"].tolist() for key, group in groups.items()} == expected


@hypothesis.given(requests=tests.peri_scribe.kml.selection_helpers.filename_requests())
def test_unique_filename_prefix_allocates_distinct_safe_names(
    requests: list[tuple[str | None, str]],
) -> None:
    used: set[str] = set()
    for identifier, name in requests:
        prefix = peri_scribe.kml.selection.unique_filename_prefix(
            identifier,
            name,
            frozenset(used),
        )
        assert prefix not in used
        assert re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", prefix)
        used.add(prefix)


def test_fires_with_qualifying_area_includes_geometry_without_reported_acres(
    mapped_fire: geopandas.GeoDataFrame,
) -> None:
    assert peri_scribe.kml.selection.fires_with_qualifying_area(
        mapped_fire,
        mapped_fire.iloc[0:0],
        25 * units.acres,
    ) == {("id", "example")}


def test_fires_with_qualifying_area_includes_independent_incident_growth(
    mapped_fire: geopandas.GeoDataFrame,
) -> None:
    mapped_fire["geometry_area_square_meters"] = (10 * units.acres).m_as("meters**2")
    incidents = tests.factories.geo_frame(
        {
            "fire_identifier": ["alias"],
            "fire_name": ["Example"],
            "observation_time": [tests.factories.utc(2026, 9, 5, 0)],
            "report_confirmed": [False],
            "incident_size": [40],
        },
        [None],
    )
    assert peri_scribe.kml.selection.fires_with_qualifying_area(
        mapped_fire,
        mapped_fire.iloc[0:0],
        25 * units.acres,
        incidents,
        aliases={"alias": "example"},
    ) == {("id", "example")}


def test_fires_with_qualifying_area_does_not_split_alias_evidence(
    mapped_fire: geopandas.GeoDataFrame,
) -> None:
    mapped_fire["geometry_area_square_meters"] = (10 * units.acres).m_as("meters**2")
    points = tests.factories.geo_frame(
        {
            "fire_identifier": ["alias"],
            "fire_name": ["Example"],
            "observation_time": [tests.factories.utc(2026, 9, 2, 0)],
            "incident_size": [100],
        },
        [None],
    )
    assert not peri_scribe.kml.selection.fires_with_qualifying_area(
        mapped_fire,
        points,
        25 * units.acres,
        aliases={"alias": "example"},
    )


def test_fires_with_qualifying_area_keeps_historical_qualification(
    mapped_fire: geopandas.GeoDataFrame,
) -> None:
    mapped_fire.loc[1] = mapped_fire.iloc[0]
    mapped_fire.loc[1, "observation_time"] = tests.factories.utc(2026, 9, 5, 0)
    mapped_fire.loc[1, "geometry"] = tests.factories.square(0.001)
    mapped_fire.loc[1, "geometry_area_square_meters"] = (10 * units.acres).m_as(
        "meters**2",
    )
    assert peri_scribe.kml.selection.fires_with_qualifying_area(
        mapped_fire,
        mapped_fire.iloc[0:0],
        25 * units.acres,
    ) == {("id", "example")}


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
    entry = tests.peri_scribe.kml.kml_helpers.fire_index_entry("Bug", "active")
    assert peri_scribe.kml.selection.identifiers(entry) == frozenset()


def test_unique_filename_prefix_uses_identifier() -> None:
    assert (
        peri_scribe.kml.selection.unique_filename_prefix("id-bug", "Bug", frozenset())
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
    first = tests.factories.square(1.0)
    second = tests.factories.square(2.0)
    nameless = tests.factories.square(3.0)
    first_time = datetime.datetime(2026, 8, 5, tzinfo=datetime.UTC)
    second_time = datetime.datetime(2026, 8, 6, tzinfo=datetime.UTC)
    perimeters = tests.peri_scribe.kml.kml_helpers.geometry_frame(
        [("id-a", "Bug", first), ("id-a", "Bug", second), (None, "Nameless", nameless)],
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
            tests.peri_scribe.kml.kml_helpers.perimeter_with_time(nameless),
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
        peri_scribe.kml.selection.fire_point(frozenset({"id-a"}), "Bug", {}, {}) is None
    )


def test_fire_area_key_keys_by_identifier() -> None:
    assert peri_scribe.kml.selection.fire_area_key("id-bug", "Bug") == ("id", "id-bug")


def test_fire_area_key_keys_by_name_when_identifier_missing() -> None:
    assert peri_scribe.kml.selection.fire_area_key(None, "Bug") == ("name", "Bug")


def test_fires_with_qualifying_area_keeps_fire_at_minimum() -> None:
    perimeters = tests.peri_scribe.kml.fire_data_helpers.area_frame(
        "area_acres",
        [("id-bug", "Bug")],
        [peri_scribe.kml.selection.MINIMUM_FIRE_AREA.m_as("acres")],
    )
    points = tests.peri_scribe.kml.fire_data_helpers.area_frame(
        "incident_size",
        [("id-bug", "Bug")],
        [None],
    )
    assert peri_scribe.kml.selection.fires_with_qualifying_area(
        perimeters,
        points,
        peri_scribe.kml.selection.MINIMUM_FIRE_AREA,
    ) == {("id", "id-bug")}


def test_fires_with_qualifying_area_keeps_fire_with_reported_area() -> None:
    perimeters = tests.peri_scribe.kml.kml_helpers.geometry_frame([])
    points = tests.peri_scribe.kml.fire_data_helpers.area_frame(
        "discovery_acres",
        [("id-bug", "Bug")],
        [100.0],
    )
    assert peri_scribe.kml.selection.fires_with_qualifying_area(
        perimeters,
        points,
        peri_scribe.kml.selection.MINIMUM_FIRE_AREA,
    ) == {("id", "id-bug")}


def test_fires_with_qualifying_area_keeps_fire_with_any_qualifying_indication() -> None:
    perimeters = tests.peri_scribe.kml.fire_data_helpers.area_frame(
        "area_acres",
        [("id-bug", "Bug")],
        [10.0],
    )
    points = tests.peri_scribe.kml.fire_data_helpers.area_frame(
        "incident_size",
        [("id-bug", "Bug")],
        [30.0],
    )
    assert peri_scribe.kml.selection.fires_with_qualifying_area(
        perimeters,
        points,
        peri_scribe.kml.selection.MINIMUM_FIRE_AREA,
    ) == {("id", "id-bug")}


def test_fires_with_qualifying_area_excludes_fire_below_minimum() -> None:
    perimeters = tests.peri_scribe.kml.fire_data_helpers.area_frame(
        "area_acres",
        [("id-bug", "Bug")],
        [10.0],
    )
    points = tests.peri_scribe.kml.fire_data_helpers.area_frame(
        "final_acres",
        [("id-bug", "Bug")],
        [20.0],
    )
    assert (
        peri_scribe.kml.selection.fires_with_qualifying_area(
            perimeters,
            points,
            peri_scribe.kml.selection.MINIMUM_FIRE_AREA,
        )
        == frozenset()
    )


def test_fires_with_qualifying_area_excludes_fire_with_missing_areas() -> None:
    perimeters = tests.peri_scribe.kml.fire_data_helpers.area_frame(
        "area_acres",
        [("id-bug", "Bug")],
        [None],
    )
    points = tests.peri_scribe.kml.fire_data_helpers.area_frame(
        "incident_size",
        [("id-bug", "Bug")],
        [None],
    )
    assert (
        peri_scribe.kml.selection.fires_with_qualifying_area(
            perimeters,
            points,
            peri_scribe.kml.selection.MINIMUM_FIRE_AREA,
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
            peri_scribe.kml.selection.MINIMUM_FIRE_AREA,
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


def test_fire_point_location_uses_known_point() -> None:
    point = shapely.geometry.Point(1.0, 1.0)
    result = peri_scribe.kml.selection.fire_point_location(
        frozenset({"id-a"}),
        "Bug",
        {"id-a": point},
        {},
        (
            tests.peri_scribe.kml.kml_helpers.perimeter_with_time(
                tests.factories.square(2.0),
            ),
        ),
    )
    assert result is point


def test_fire_point_location_derives_point_from_latest_perimeter() -> None:
    earlier = tests.factories.square(1.0)
    latest = tests.factories.square(2.0)
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


def test_perimeter_groups_carries_shared_measurements() -> None:
    shape = tests.factories.square(1)
    expected_area = peri_scribe.units.area(shape)
    digest = peri_scribe.perimeters.progression.sequence_digest((shape,))
    frame = tests.factories.geo_frame(
        {
            "fire_identifier": ["id"],
            "fire_name": ["Example"],
            "observation_time": [tests.factories.utc(2026, 9, 1, 0)],
            peri_scribe.geo.measurements.AREA_COLUMN: [
                expected_area.m_as("meters ** 2"),
            ],
            peri_scribe.perimeters.progression.ADDED_AREA_COLUMN: [
                expected_area.m_as("meters ** 2"),
            ],
            peri_scribe.perimeters.progression.SEQUENCE_COLUMN: [digest],
        },
        [shape],
    )
    by_identifier, _by_name = peri_scribe.kml.selection.perimeter_groups(frame)
    perimeter = by_identifier["id"][0]
    assert perimeter.measured_area == expected_area
    ring = peri_scribe.kml.fire_data.progression_ring(perimeter)
    assert ring is not None
    assert ring.added_area == expected_area
    assert ring.sequence_digest == digest
