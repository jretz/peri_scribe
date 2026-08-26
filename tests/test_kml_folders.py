"""Tests for peri_scribe.kml_folders."""

from __future__ import annotations

import datetime

import pytest
import shapely.geometry
import simplekml

import peri_scribe.kml_fire_data
import peri_scribe.kml_folders
import peri_scribe.kml_template
import peri_scribe.kml_template_reader
import peri_scribe.models
import peri_scribe.perimeter_progression
import tests.kml_helpers


@pytest.fixture
def style_urls() -> dict[str, str]:
    return peri_scribe.kml_template_reader.template_from(
        peri_scribe.kml_template.template_kml(),
    ).style_urls


def test_fire_folder_includes_point_and_progression(
    style_urls: dict[str, str],
) -> None:
    point = shapely.geometry.Point(1.0, 1.0)
    antepenultimate_time = datetime.datetime(2026, 8, 3, 23, 0, tzinfo=datetime.UTC)
    penultimate_time = datetime.datetime(2026, 8, 4, 16, 15, tzinfo=datetime.UTC)
    latest_time = datetime.datetime(2026, 8, 5, 20, 30, tzinfo=datetime.UTC)
    fire = peri_scribe.kml_fire_data.FireGeometry(
        name="Bug",
        status=peri_scribe.models.FireStatus.ACTIVE,
        point=point,
        perimeters=(
            tests.kml_helpers.perimeter_with_time(
                tests.kml_helpers.square(1.0),
                antepenultimate_time,
            ),
            tests.kml_helpers.perimeter_with_time(
                tests.kml_helpers.square(2.0),
                penultimate_time,
            ),
            tests.kml_helpers.perimeter_with_time(
                tests.kml_helpers.square(3.0),
                latest_time,
            ),
        ),
    )
    kml = simplekml.Kml()
    peri_scribe.kml_folders.fire_folder(kml.document, fire, style_urls)
    folder = tests.kml_helpers.folder_named(
        tests.kml_helpers.document_from(kml.kml()),
        "Bug",
    )
    assert tests.kml_helpers.placemark_names(folder) == ["Bug"]
    perimeters_folder = tests.kml_helpers.folder_named(folder, "Perimeters")
    assert tests.kml_helpers.placemark_names(perimeters_folder) == [
        "08/05 13:30 Perimeter",
        "08/04 09:15 Perimeter",
        "08/03 16:00 Perimeter",
    ]
    assert (
        tests.kml_helpers.folder_item_icon_href(perimeters_folder) == "perimeters.png"
    )
    interior_folder = tests.kml_helpers.folder_named(folder, "Interior")
    assert tests.kml_helpers.placemark_names(interior_folder) == [
        "08/05 13:30 Interior",
    ]
    assert tests.kml_helpers.folder_item_icon_href(interior_folder) == "interior.png"
    assert (
        tests.kml_helpers.placemark_style_url(
            tests.kml_helpers.placemark_named(folder, "Bug"),
        )
        == "#point-icon"
    )
    assert (
        tests.kml_helpers.placemark_style_url(
            tests.kml_helpers.placemark_named(interior_folder, "08/05 13:30 Interior"),
        )
        == "#perimeter-fill"
    )
    assert {
        name: tests.kml_helpers.draw_order(
            tests.kml_helpers.placemark_named(container, name),
        )
        for container, name in (
            (interior_folder, "08/05 13:30 Interior"),
            (perimeters_folder, "08/05 13:30 Perimeter"),
            (perimeters_folder, "08/04 09:15 Perimeter"),
            (perimeters_folder, "08/03 16:00 Perimeter"),
            (folder, "Bug"),
        )
    } == {
        "08/05 13:30 Interior": 0,
        "08/03 16:00 Perimeter": 1,
        "08/04 09:15 Perimeter": 2,
        "08/05 13:30 Perimeter": 3,
        "Bug": 4,
    }


def test_fire_folder_shows_only_available_perimeters(
    style_urls: dict[str, str],
) -> None:
    fire = peri_scribe.kml_fire_data.FireGeometry(
        name="Bug",
        status=peri_scribe.models.FireStatus.ACTIVE,
        point=shapely.geometry.Point(1.0, 1.0),
        perimeters=(
            tests.kml_helpers.perimeter_with_time(tests.kml_helpers.square(1.0)),
        ),
    )
    kml = simplekml.Kml()
    peri_scribe.kml_folders.fire_folder(kml.document, fire, style_urls)
    folder = tests.kml_helpers.folder_named(
        tests.kml_helpers.document_from(kml.kml()),
        "Bug",
    )
    assert tests.kml_helpers.placemark_names(folder) == ["Bug", "Unknown Mapping"]
    assert tests.kml_helpers.folder_names(folder) == ["Interior"]
    interior_folder = tests.kml_helpers.folder_named(folder, "Interior")
    assert tests.kml_helpers.placemark_names(interior_folder) == ["Interior"]
    assert {
        name: tests.kml_helpers.draw_order(
            tests.kml_helpers.placemark_named(container, name),
        )
        for container, name in (
            (interior_folder, "Interior"),
            (folder, "Unknown Mapping"),
            (folder, "Bug"),
        )
    } == {
        "Interior": 0,
        "Unknown Mapping": 1,
        "Bug": 2,
    }


def test_fire_folder_draws_interior_from_difference_rings(
    style_urls: dict[str, str],
) -> None:
    first_time = datetime.datetime(2026, 8, 5, 20, 0, tzinfo=datetime.UTC)
    second_time = datetime.datetime(2026, 8, 7, 20, 0, tzinfo=datetime.UTC)
    fire = peri_scribe.kml_fire_data.FireGeometry(
        name="Bug",
        status=peri_scribe.models.FireStatus.ACTIVE,
        point=shapely.geometry.Point(1.0, 1.0),
        perimeters=(
            tests.kml_helpers.perimeter_with_time(
                tests.kml_helpers.square(2.0),
                first_time,
            ),
            tests.kml_helpers.perimeter_with_time(
                tests.kml_helpers.square(4.0),
                second_time,
            ),
        ),
        progression_rings=(
            peri_scribe.perimeter_progression.Ring(
                geometry=tests.kml_helpers.square(1.0),
                observation_time=first_time,
            ),
            peri_scribe.perimeter_progression.Ring(
                geometry=tests.kml_helpers.square(2.0),
                observation_time=second_time,
            ),
        ),
    )
    kml = simplekml.Kml()
    peri_scribe.kml_folders.fire_folder(kml.document, fire, style_urls)
    folder = tests.kml_helpers.folder_named(
        tests.kml_helpers.document_from(kml.kml()),
        "Bug",
    )
    assert tests.kml_helpers.placemark_names(folder) == ["Bug"]
    perimeters_folder = tests.kml_helpers.folder_named(folder, "Perimeters")
    assert tests.kml_helpers.placemark_names(perimeters_folder) == [
        "08/07 13:00 Perimeter",
        "08/05 13:00 Perimeter",
    ]
    interior_folder = tests.kml_helpers.folder_named(folder, "Interior")
    assert tests.kml_helpers.placemark_names(interior_folder) == [
        "08/05 13:00 Interior",
        "08/07 13:00 Interior",
    ]
    first_interior = tests.kml_helpers.placemark_named(
        interior_folder,
        "08/05 13:00 Interior",
    )
    second_interior = tests.kml_helpers.placemark_named(
        interior_folder,
        "08/07 13:00 Interior",
    )
    assert tests.kml_helpers.placemark_style_url(first_interior) == "#perimeter-fill"
    assert tests.kml_helpers.placemark_style_url(second_interior) == "#perimeter-fill"
    assert {
        name: tests.kml_helpers.draw_order(
            tests.kml_helpers.placemark_named(interior_folder, name),
        )
        for name in ("08/05 13:00 Interior", "08/07 13:00 Interior")
    } == {
        "08/05 13:00 Interior": 0,
        "08/07 13:00 Interior": 0,
    }
    # The rings fill the interior instead of the complete latest perimeter.
    assert set(tests.kml_helpers.exterior_coordinates(first_interior)) == {
        (-0.5, -0.5),
        (0.5, -0.5),
        (0.5, 0.5),
        (-0.5, 0.5),
    }
    assert set(tests.kml_helpers.exterior_coordinates(second_interior)) == {
        (-1.0, -1.0),
        (1.0, -1.0),
        (1.0, 1.0),
        (-1.0, 1.0),
    }


def test_fire_folder_falls_back_to_complete_perimeter_without_dated_rings(
    style_urls: dict[str, str],
) -> None:
    fire = peri_scribe.kml_fire_data.FireGeometry(
        name="Bug",
        status=peri_scribe.models.FireStatus.ACTIVE,
        point=shapely.geometry.Point(1.0, 1.0),
        perimeters=(
            tests.kml_helpers.perimeter_with_time(tests.kml_helpers.square(1.0)),
        ),
        progression_rings=(
            peri_scribe.perimeter_progression.Ring(
                geometry=tests.kml_helpers.square(1.0),
                observation_time=None,
            ),
        ),
    )
    kml = simplekml.Kml()
    peri_scribe.kml_folders.fire_folder(kml.document, fire, style_urls)
    folder = tests.kml_helpers.folder_named(
        tests.kml_helpers.document_from(kml.kml()),
        "Bug",
    )
    assert tests.kml_helpers.placemark_names(folder) == ["Bug", "Unknown Mapping"]
    assert tests.kml_helpers.placemark_names(
        tests.kml_helpers.folder_named(folder, "Interior"),
    ) == ["Interior"]


def test_fire_folder_without_point_or_perimeters_is_empty(
    style_urls: dict[str, str],
) -> None:
    fire = peri_scribe.kml_fire_data.FireGeometry(
        name="Bug",
        status=peri_scribe.models.FireStatus.ACTIVE,
        point=None,
        perimeters=(),
    )
    kml = simplekml.Kml()
    peri_scribe.kml_folders.fire_folder(kml.document, fire, style_urls)
    folder = tests.kml_helpers.folder_named(
        tests.kml_helpers.document_from(kml.kml()),
        "Bug",
    )
    assert tests.kml_helpers.placemark_names(folder) == []
    assert tests.kml_helpers.folder_names(folder) == []


def test_fire_folder_leads_with_progression_tour(
    style_urls: dict[str, str],
) -> None:
    first_time = datetime.datetime(2026, 8, 5, 20, 0, tzinfo=datetime.UTC)
    second_time = datetime.datetime(2026, 8, 7, 20, 0, tzinfo=datetime.UTC)
    fire = peri_scribe.kml_fire_data.FireGeometry(
        name="Bug",
        status=peri_scribe.models.FireStatus.ACTIVE,
        point=shapely.geometry.Point(1.0, 1.0),
        perimeters=(),
        progression_rings=(
            peri_scribe.perimeter_progression.Ring(
                geometry=tests.kml_helpers.square(1.0),
                observation_time=first_time,
            ),
            peri_scribe.perimeter_progression.Ring(
                geometry=tests.kml_helpers.square(2.0),
                observation_time=second_time,
            ),
        ),
    )
    kml = simplekml.Kml()
    peri_scribe.kml_folders.fire_folder(kml.document, fire, style_urls)
    bug_folder = tests.kml_helpers.folder_named(
        tests.kml_helpers.document_from(kml.kml()),
        "Bug",
    )
    features = [
        child
        for child in bug_folder
        if child.tag
        in {
            tests.kml_helpers.kml_tag("Folder"),
            tests.kml_helpers.kml_tag("Placemark"),
            tests.kml_helpers.gx_tag("Tour"),
        }
    ]
    assert features[0].tag == tests.kml_helpers.gx_tag("Tour")
    tour = tests.kml_helpers.tour_named(bug_folder, "Progression")
    updates = tests.kml_helpers.tour_primitives(
        tour,
        tests.kml_helpers.gx_tag("AnimatedUpdate"),
    )
    waits = tests.kml_helpers.tour_primitives(tour, tests.kml_helpers.gx_tag("Wait"))
    interior_folder = tests.kml_helpers.folder_named(bug_folder, "Interior")
    interior = [
        tests.kml_helpers.placemark_named(interior_folder, "08/05 13:00 Interior"),
        tests.kml_helpers.placemark_named(interior_folder, "08/07 13:00 Interior"),
    ]
    assert len(updates) == len(interior)
    assert len(waits) == len(interior)
    interior_ids = [placemark.get("id") for placemark in interior]
    assert [
        tests.kml_helpers.update_visibility_by_target(update) for update in updates
    ] == [
        {interior_ids[0]: 1, interior_ids[1]: 0},
        {interior_ids[0]: 1, interior_ids[1]: 1},
    ]
    assert [tests.kml_helpers.wait_duration(wait) for wait in waits] == [2.0, 1.0]


def test_fire_folder_adds_tour_for_fallback_polygon(
    style_urls: dict[str, str],
) -> None:
    fire = peri_scribe.kml_fire_data.FireGeometry(
        name="Bug",
        status=peri_scribe.models.FireStatus.ACTIVE,
        point=shapely.geometry.Point(1.0, 1.0),
        perimeters=(
            tests.kml_helpers.perimeter_with_time(tests.kml_helpers.square(1.0)),
        ),
    )
    kml = simplekml.Kml()
    peri_scribe.kml_folders.fire_folder(kml.document, fire, style_urls)
    bug_folder = tests.kml_helpers.folder_named(
        tests.kml_helpers.document_from(kml.kml()),
        "Bug",
    )
    tour = tests.kml_helpers.tour_named(bug_folder, "Progression")
    updates = tests.kml_helpers.tour_primitives(
        tour,
        tests.kml_helpers.gx_tag("AnimatedUpdate"),
    )
    waits = tests.kml_helpers.tour_primitives(tour, tests.kml_helpers.gx_tag("Wait"))
    assert len(updates) == 1
    assert len(waits) == 1
    assert [tests.kml_helpers.wait_duration(wait) for wait in waits] == [1.0]
    interior = tests.kml_helpers.placemark_named(
        tests.kml_helpers.folder_named(bug_folder, "Interior"),
        "Interior",
    )
    assert tests.kml_helpers.update_visibility_by_target(updates[0]) == {
        interior.get("id"): 1,
    }


def test_fire_folder_without_polygons_has_no_tour(
    style_urls: dict[str, str],
) -> None:
    fire = peri_scribe.kml_fire_data.FireGeometry(
        name="Bug",
        status=peri_scribe.models.FireStatus.ACTIVE,
        point=shapely.geometry.Point(1.0, 1.0),
        perimeters=(),
    )
    kml = simplekml.Kml()
    peri_scribe.kml_folders.fire_folder(kml.document, fire, style_urls)
    bug_folder = tests.kml_helpers.folder_named(
        tests.kml_helpers.document_from(kml.kml()),
        "Bug",
    )
    assert [
        child for child in bug_folder if child.tag == tests.kml_helpers.gx_tag("Tour")
    ] == []


def test_latest_perimeters_folder_names_and_holds_fires(
    style_urls: dict[str, str],
) -> None:
    fires = [
        peri_scribe.kml_fire_data.FireGeometry(
            name="Bug",
            status=peri_scribe.models.FireStatus.ACTIVE,
            point=None,
            perimeters=(),
        ),
    ]
    kml = simplekml.Kml()
    peri_scribe.kml_folders.latest_perimeters_folder(kml.document, fires, style_urls)
    document = tests.kml_helpers.document_from(kml.kml())
    folder = tests.kml_helpers.folder_named(
        document,
        peri_scribe.kml_template.LATEST_PERIMETERS_FOLDER_NAME,
    )
    assert tests.kml_helpers.folder_names(folder) == ["Bug"]
    assert tests.kml_helpers.folder_list_item_type(folder) is None


def test_progression_folder_holds_fires_without_rings(
    style_urls: dict[str, str],
) -> None:
    fire = peri_scribe.kml_fire_data.FireGeometry(
        name="Bug",
        status=peri_scribe.models.FireStatus.ACTIVE,
        point=shapely.geometry.Point(1.0, 1.0),
        perimeters=(),
    )
    kml = simplekml.Kml()
    peri_scribe.kml_folders.progression_folder(kml.document, [fire], style_urls)
    document = tests.kml_helpers.document_from(kml.kml())
    folder = tests.kml_helpers.folder_named(
        document,
        peri_scribe.perimeter_progression.PROGRESSION_MAPS_FOLDER_NAME,
    )
    assert tests.kml_helpers.folder_names(folder) == ["Bug"]
    bug_folder = tests.kml_helpers.folder_named(folder, "Bug")
    assert tests.kml_helpers.placemark_names(bug_folder) == ["Bug"]
    assert tests.kml_helpers.folder_names(bug_folder) == []


def test_progression_folder_holds_point_and_ring_folders(
    style_urls: dict[str, str],
) -> None:
    point = shapely.geometry.Point(1.0, 1.0)
    fire = peri_scribe.kml_fire_data.FireGeometry(
        name="Bug",
        status=peri_scribe.models.FireStatus.ACTIVE,
        point=point,
        perimeters=(),
        progression_rings=(
            peri_scribe.perimeter_progression.Ring(
                geometry=tests.kml_helpers.square(1.0),
                observation_time=datetime.datetime(
                    2026,
                    8,
                    13,
                    20,
                    0,
                    tzinfo=datetime.UTC,
                ),
            ),
            peri_scribe.perimeter_progression.Ring(
                geometry=tests.kml_helpers.square(2.0),
                observation_time=datetime.datetime(
                    2026,
                    8,
                    14,
                    20,
                    0,
                    tzinfo=datetime.UTC,
                ),
            ),
            peri_scribe.perimeter_progression.Ring(
                geometry=tests.kml_helpers.square(3.0),
                observation_time=datetime.datetime(
                    2026,
                    8,
                    15,
                    20,
                    0,
                    tzinfo=datetime.UTC,
                ),
            ),
        ),
    )
    kml = simplekml.Kml()
    peri_scribe.kml_folders.progression_folder(kml.document, [fire], style_urls)
    document = tests.kml_helpers.document_from(kml.kml())
    folder = tests.kml_helpers.folder_named(
        document,
        peri_scribe.perimeter_progression.PROGRESSION_MAPS_FOLDER_NAME,
    )
    bug_folder = tests.kml_helpers.folder_named(folder, "Bug")
    assert tests.kml_helpers.placemark_names(bug_folder) == ["Bug"]
    assert tests.kml_helpers.folder_names(bug_folder) == ["08/15", "08/13 - 08/14"]

    latest_folder = tests.kml_helpers.folder_named(bug_folder, "08/15")
    two_days_folder = tests.kml_helpers.folder_named(bug_folder, "08/13 - 08/14")
    assert tests.kml_helpers.placemark_names(latest_folder) == ["08/15 13:00 Interior"]
    assert tests.kml_helpers.placemark_names(two_days_folder) == [
        "08/13 13:00 Interior",
        "08/14 13:00 Interior",
    ]

    assert (
        tests.kml_helpers.placemark_style_url(
            tests.kml_helpers.placemark_named(latest_folder, "08/15 13:00 Interior"),
        )
        == "#days-fill-1"
    )
    assert (
        tests.kml_helpers.placemark_style_url(
            tests.kml_helpers.placemark_named(two_days_folder, "08/13 13:00 Interior"),
        )
        == "#days-fill-2"
    )
    assert (
        tests.kml_helpers.placemark_style_url(
            tests.kml_helpers.placemark_named(two_days_folder, "08/14 13:00 Interior"),
        )
        == "#days-fill-2"
    )

    assert {
        name: tests.kml_helpers.draw_order(
            tests.kml_helpers.placemark_named(container, name),
        )
        for container, name in (
            (two_days_folder, "08/13 13:00 Interior"),
            (two_days_folder, "08/14 13:00 Interior"),
            (latest_folder, "08/15 13:00 Interior"),
            (bug_folder, "Bug"),
        )
    } == {
        "08/13 13:00 Interior": 0,
        "08/14 13:00 Interior": 1,
        "08/15 13:00 Interior": 2,
        "Bug": 3,
    }

    assert (
        tests.kml_helpers.folder_item_icon_href(latest_folder)
        == "progression-band-1.png"
    )
    assert (
        tests.kml_helpers.folder_item_icon_href(two_days_folder)
        == "progression-band-2.png"
    )

    assert set(
        tests.kml_helpers.exterior_coordinates(
            tests.kml_helpers.placemark_named(latest_folder, "08/15 13:00 Interior"),
        ),
    ) == {
        (-1.5, -1.5),
        (1.5, -1.5),
        (1.5, 1.5),
        (-1.5, 1.5),
    }
    assert set(
        tests.kml_helpers.exterior_coordinates(
            tests.kml_helpers.placemark_named(two_days_folder, "08/13 13:00 Interior"),
        ),
    ) == {
        (-0.5, -0.5),
        (0.5, -0.5),
        (0.5, 0.5),
        (-0.5, 0.5),
    }
    assert set(
        tests.kml_helpers.exterior_coordinates(
            tests.kml_helpers.placemark_named(two_days_folder, "08/14 13:00 Interior"),
        ),
    ) == {
        (-1.0, -1.0),
        (1.0, -1.0),
        (1.0, 1.0),
        (-1.0, 1.0),
    }


def test_progression_folder_leads_with_progression_tour(
    style_urls: dict[str, str],
) -> None:
    first_time = datetime.datetime(2026, 8, 13, 20, 0, tzinfo=datetime.UTC)
    second_time = datetime.datetime(2026, 8, 14, 20, 0, tzinfo=datetime.UTC)
    third_time = datetime.datetime(2026, 8, 15, 20, 0, tzinfo=datetime.UTC)
    fire = peri_scribe.kml_fire_data.FireGeometry(
        name="Bug",
        status=peri_scribe.models.FireStatus.ACTIVE,
        point=shapely.geometry.Point(1.0, 1.0),
        perimeters=(),
        progression_rings=(
            peri_scribe.perimeter_progression.Ring(
                geometry=tests.kml_helpers.square(1.0),
                observation_time=first_time,
            ),
            peri_scribe.perimeter_progression.Ring(
                geometry=tests.kml_helpers.square(2.0),
                observation_time=second_time,
            ),
            peri_scribe.perimeter_progression.Ring(
                geometry=tests.kml_helpers.square(3.0),
                observation_time=third_time,
            ),
        ),
    )
    kml = simplekml.Kml()
    peri_scribe.kml_folders.progression_folder(kml.document, [fire], style_urls)
    folder = tests.kml_helpers.folder_named(
        tests.kml_helpers.document_from(kml.kml()),
        peri_scribe.perimeter_progression.PROGRESSION_MAPS_FOLDER_NAME,
    )
    bug_folder = tests.kml_helpers.folder_named(folder, "Bug")
    features = [
        child
        for child in bug_folder
        if child.tag
        in {
            tests.kml_helpers.kml_tag("Folder"),
            tests.kml_helpers.kml_tag("Placemark"),
            tests.kml_helpers.gx_tag("Tour"),
        }
    ]
    assert features[0].tag == tests.kml_helpers.gx_tag("Tour")
    tour = tests.kml_helpers.tour_named(bug_folder, "Progression")
    updates = tests.kml_helpers.tour_primitives(
        tour,
        tests.kml_helpers.gx_tag("AnimatedUpdate"),
    )
    waits = tests.kml_helpers.tour_primitives(tour, tests.kml_helpers.gx_tag("Wait"))
    two_days_folder = tests.kml_helpers.folder_named(bug_folder, "08/13 - 08/14")
    latest_folder = tests.kml_helpers.folder_named(bug_folder, "08/15")
    # The rings live in different day-range subfolders, but the tour reveals them
    # in the same chronological order the latest-perimeters tour does.
    interior = [
        tests.kml_helpers.placemark_named(two_days_folder, "08/13 13:00 Interior"),
        tests.kml_helpers.placemark_named(two_days_folder, "08/14 13:00 Interior"),
        tests.kml_helpers.placemark_named(latest_folder, "08/15 13:00 Interior"),
    ]
    assert len(updates) == len(interior)
    assert len(waits) == len(interior)
    interior_ids = [placemark.get("id") for placemark in interior]
    assert [
        tests.kml_helpers.update_visibility_by_target(update) for update in updates
    ] == [
        {interior_ids[0]: 1, interior_ids[1]: 0, interior_ids[2]: 0},
        {interior_ids[0]: 1, interior_ids[1]: 1, interior_ids[2]: 0},
        {interior_ids[0]: 1, interior_ids[1]: 1, interior_ids[2]: 1},
    ]
    assert [tests.kml_helpers.wait_duration(wait) for wait in waits] == [1.0, 1.0, 1.0]


def test_progression_folder_hides_its_tree(style_urls: dict[str, str]) -> None:
    point = shapely.geometry.Point(1.0, 1.0)
    fire = peri_scribe.kml_fire_data.FireGeometry(
        name="Bug",
        status=peri_scribe.models.FireStatus.ACTIVE,
        point=point,
        perimeters=(),
        progression_rings=(
            peri_scribe.perimeter_progression.Ring(
                geometry=tests.kml_helpers.square(1.0),
                observation_time=datetime.datetime(
                    2026,
                    8,
                    15,
                    20,
                    0,
                    tzinfo=datetime.UTC,
                ),
            ),
        ),
    )
    kml = simplekml.Kml()
    peri_scribe.kml_folders.progression_folder(kml.document, [fire], style_urls)
    document = tests.kml_helpers.document_from(kml.kml())
    folder = tests.kml_helpers.folder_named(
        document,
        peri_scribe.perimeter_progression.PROGRESSION_MAPS_FOLDER_NAME,
    )
    tests.kml_helpers.assert_tree_invisible(folder)


def test_status_folder_name_for_active() -> None:
    assert (
        peri_scribe.kml_folders.status_folder_name(
            peri_scribe.models.FireStatus.ACTIVE,
        )
        == "Active Fires"
    )


def test_status_folder_name_for_inactive() -> None:
    assert (
        peri_scribe.kml_folders.status_folder_name(
            peri_scribe.models.FireStatus.INACTIVE,
        )
        == "Inactive Fires"
    )


def test_status_folder_filters_by_status(style_urls: dict[str, str]) -> None:
    active = peri_scribe.kml_fire_data.FireGeometry(
        name="Active Fire",
        status=peri_scribe.models.FireStatus.ACTIVE,
        point=None,
        perimeters=(),
    )
    inactive = peri_scribe.kml_fire_data.FireGeometry(
        name="Inactive Fire",
        status=peri_scribe.models.FireStatus.INACTIVE,
        point=None,
        perimeters=(),
    )
    kml = simplekml.Kml()
    peri_scribe.kml_folders.status_folder(
        kml.document,
        [active, inactive],
        peri_scribe.models.FireStatus.ACTIVE,
        style_urls,
    )
    document = tests.kml_helpers.document_from(kml.kml())
    folder = tests.kml_helpers.folder_named(document, "Active Fires")
    perimeters_folder = tests.kml_helpers.folder_named(
        folder,
        peri_scribe.kml_template.LATEST_PERIMETERS_FOLDER_NAME,
    )
    assert tests.kml_helpers.folder_names(perimeters_folder) == ["Active Fire"]


def test_status_folder_puts_same_fires_in_both_folders(
    style_urls: dict[str, str],
) -> None:
    first_time = datetime.datetime(2026, 8, 13, 20, 0, tzinfo=datetime.UTC)
    second_time = datetime.datetime(2026, 8, 14, 20, 0, tzinfo=datetime.UTC)
    with_rings = peri_scribe.kml_fire_data.FireGeometry(
        name="Rings",
        status=peri_scribe.models.FireStatus.ACTIVE,
        point=shapely.geometry.Point(1.0, 1.0),
        perimeters=(),
        progression_rings=(
            peri_scribe.perimeter_progression.Ring(
                geometry=tests.kml_helpers.square(1.0),
                observation_time=first_time,
            ),
            peri_scribe.perimeter_progression.Ring(
                geometry=tests.kml_helpers.square(2.0),
                observation_time=second_time,
            ),
        ),
    )
    point_only = peri_scribe.kml_fire_data.FireGeometry(
        name="Point",
        status=peri_scribe.models.FireStatus.ACTIVE,
        point=shapely.geometry.Point(2.0, 2.0),
        perimeters=(),
    )
    empty = peri_scribe.kml_fire_data.FireGeometry(
        name="Empty",
        status=peri_scribe.models.FireStatus.ACTIVE,
        point=None,
        perimeters=(),
    )
    kml = simplekml.Kml()
    peri_scribe.kml_folders.status_folder(
        kml.document,
        [with_rings, point_only, empty],
        peri_scribe.models.FireStatus.ACTIVE,
        style_urls,
    )
    document = tests.kml_helpers.document_from(kml.kml())
    folder = tests.kml_helpers.folder_named(document, "Active Fires")
    latest = tests.kml_helpers.folder_named(
        folder,
        peri_scribe.kml_template.LATEST_PERIMETERS_FOLDER_NAME,
    )
    progression = tests.kml_helpers.folder_named(
        folder,
        peri_scribe.perimeter_progression.PROGRESSION_MAPS_FOLDER_NAME,
    )
    assert (
        tests.kml_helpers.folder_names(latest)
        == tests.kml_helpers.folder_names(progression)
        == [
            "Rings",
            "Point",
            "Empty",
        ]
    )


def test_fire_folder_applies_description_to_every_placemark(
    style_urls: dict[str, str],
) -> None:
    fire = peri_scribe.kml_fire_data.FireGeometry(
        name="Bug",
        status=peri_scribe.models.FireStatus.ACTIVE,
        point=shapely.geometry.Point(1.0, 1.0),
        perimeters=(
            tests.kml_helpers.perimeter_with_time(tests.kml_helpers.square(1.0)),
        ),
        description="<![CDATA[<b>Bug</b>]]>",
    )
    kml = simplekml.Kml()
    peri_scribe.kml_folders.fire_folder(kml.document, fire, style_urls)
    folder = tests.kml_helpers.folder_named(
        tests.kml_helpers.document_from(kml.kml()),
        "Bug",
    )
    assert tests.kml_helpers.placemark_names(folder) == ["Bug", "Unknown Mapping"]
    interior_folder = tests.kml_helpers.folder_named(folder, "Interior")
    assert tests.kml_helpers.placemark_names(interior_folder) == ["Interior"]
    for container in (folder, interior_folder):
        for name in tests.kml_helpers.placemark_names(container):
            assert tests.kml_helpers.placemark_named(container, name).findtext(
                tests.kml_helpers.kml_tag("description"),
            ) == ("<b>Bug</b>")
