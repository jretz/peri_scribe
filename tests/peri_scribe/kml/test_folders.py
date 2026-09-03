"""Tests for peri_scribe.kml.folders."""

from __future__ import annotations

import datetime

import pytest
import shapely.geometry

import peri_scribe.kml.builder
import peri_scribe.kml.descriptions
import peri_scribe.kml.fire_data
import peri_scribe.kml.folders
import peri_scribe.kml.geometry
import peri_scribe.kml.plot_rendering
import peri_scribe.kml.styles
import peri_scribe.models
import peri_scribe.perimeters.progression
import peri_scribe.units
import tests.peri_scribe.kml.kml_helpers


@pytest.fixture
def style_urls() -> dict[str, str]:
    return peri_scribe.kml.styles.PLACEMARK_STYLE_URLS


def ring_style_urls_for(
    fire: peri_scribe.kml.fire_data.FireGeometry,
) -> dict[str, str]:
    """Return a ring style URL for every color *fire*'s rings use.

    The mapping mirrors the builder's, so the fire's rings resolve to the styles the
    KMZ document defines.

    Args:
        fire: The fire to symbolize.

    Returns:
        The ring style URLs.
    """
    return peri_scribe.kml.builder.ring_style_urls_for([fire])


def test_fire_folder_includes_point_perimeters_and_interior(
    style_urls: dict[str, str],
) -> None:
    point = shapely.geometry.Point(1.0, 1.0)
    antepenultimate_time = datetime.datetime(2026, 8, 3, 23, 0, tzinfo=datetime.UTC)
    penultimate_time = datetime.datetime(2026, 8, 4, 16, 15, tzinfo=datetime.UTC)
    latest_time = datetime.datetime(2026, 8, 5, 20, 30, tzinfo=datetime.UTC)
    fire = peri_scribe.kml.fire_data.FireGeometry(
        name="Bug",
        status=peri_scribe.models.FireStatus.ACTIVE,
        point=point,
        perimeters=(
            tests.peri_scribe.kml.kml_helpers.perimeter_with_time(
                tests.peri_scribe.kml.kml_helpers.square(1.0),
                antepenultimate_time,
            ),
            tests.peri_scribe.kml.kml_helpers.perimeter_with_time(
                tests.peri_scribe.kml.kml_helpers.square(2.0),
                penultimate_time,
            ),
            tests.peri_scribe.kml.kml_helpers.perimeter_with_time(
                tests.peri_scribe.kml.kml_helpers.square(3.0),
                latest_time,
            ),
        ),
    )
    writer = peri_scribe.kml.geometry.KmlWriter()
    peri_scribe.kml.folders.fire_folder(
        writer,
        fire,
        style_urls,
        peri_scribe.kml.builder.ring_style_urls_for([fire]),
    )
    folder = tests.peri_scribe.kml.kml_helpers.folder_named(
        tests.peri_scribe.kml.kml_helpers.document_from_writer(writer),
        "Bug",
    )
    assert tests.peri_scribe.kml.kml_helpers.placemark_names(folder) == ["Bug"]
    assert tests.peri_scribe.kml.kml_helpers.folder_names(folder) == [
        "Perimeters",
        "Interior",
    ]
    perimeters_folder = tests.peri_scribe.kml.kml_helpers.folder_named(
        folder,
        "Perimeters",
    )
    assert tests.peri_scribe.kml.kml_helpers.placemark_names(perimeters_folder) == [
        "08/05 13:30 Perimeter",
        "08/04 09:15 Perimeter",
        "08/03 16:00 Perimeter",
    ]
    assert (
        tests.peri_scribe.kml.kml_helpers.folder_item_icon_href(perimeters_folder)
        == "perimeters.png"
    )
    interior_folder = tests.peri_scribe.kml.kml_helpers.folder_named(folder, "Interior")
    assert tests.peri_scribe.kml.kml_helpers.placemark_names(interior_folder) == [
        "08/05 13:30 Interior",
    ]
    assert (
        tests.peri_scribe.kml.kml_helpers.folder_item_icon_href(interior_folder)
        == "interior-progression.png"
    )
    assert (
        tests.peri_scribe.kml.kml_helpers.placemark_style_url(
            tests.peri_scribe.kml.kml_helpers.placemark_named(folder, "Bug"),
        )
        == "#point-icon"
    )
    # The fire has no dated rings, so the interior is its complete latest perimeter in
    # the hottest color.
    assert (
        tests.peri_scribe.kml.kml_helpers.placemark_style_url(
            tests.peri_scribe.kml.kml_helpers.placemark_named(
                interior_folder,
                "08/05 13:30 Interior",
            ),
        )
        == "#ring-fill-ac1701"
    )
    # The interior ring draws at the bottom, the outline perimeters stack above it
    # oldest to newest, and the point draws last so its icon is never covered.
    assert {
        name: tests.peri_scribe.kml.kml_helpers.draw_order(
            tests.peri_scribe.kml.kml_helpers.placemark_named(container, name),
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
        "08/03 16:00 Perimeter": 2,
        "08/04 09:15 Perimeter": 3,
        "08/05 13:30 Perimeter": 4,
        "Bug": 5,
    }


def test_fire_folder_shows_only_available_perimeters(
    style_urls: dict[str, str],
) -> None:
    fire = peri_scribe.kml.fire_data.FireGeometry(
        name="Bug",
        status=peri_scribe.models.FireStatus.ACTIVE,
        point=shapely.geometry.Point(1.0, 1.0),
        perimeters=(
            tests.peri_scribe.kml.kml_helpers.perimeter_with_time(
                tests.peri_scribe.kml.kml_helpers.square(1.0),
            ),
        ),
    )
    writer = peri_scribe.kml.geometry.KmlWriter()
    peri_scribe.kml.folders.fire_folder(
        writer,
        fire,
        style_urls,
        peri_scribe.kml.builder.ring_style_urls_for([fire]),
    )
    folder = tests.peri_scribe.kml.kml_helpers.folder_named(
        tests.peri_scribe.kml.kml_helpers.document_from_writer(writer),
        "Bug",
    )
    assert tests.peri_scribe.kml.kml_helpers.placemark_names(folder) == [
        "Bug",
        "Unknown Mapping",
    ]
    assert tests.peri_scribe.kml.kml_helpers.folder_names(folder) == ["Interior"]
    interior_folder = tests.peri_scribe.kml.kml_helpers.folder_named(folder, "Interior")
    assert tests.peri_scribe.kml.kml_helpers.placemark_names(interior_folder) == [
        "Interior",
    ]
    assert {
        name: tests.peri_scribe.kml.kml_helpers.draw_order(
            tests.peri_scribe.kml.kml_helpers.placemark_named(container, name),
        )
        for container, name in (
            (interior_folder, "Interior"),
            (folder, "Unknown Mapping"),
            (folder, "Bug"),
        )
    } == {
        "Interior": 0,
        "Unknown Mapping": 2,
        "Bug": 3,
    }


def test_fire_folder_draws_interior_from_difference_rings(
    style_urls: dict[str, str],
) -> None:
    first_time = datetime.datetime(2026, 8, 5, 20, 0, tzinfo=datetime.UTC)
    second_time = datetime.datetime(2026, 8, 7, 20, 0, tzinfo=datetime.UTC)
    fire = peri_scribe.kml.fire_data.FireGeometry(
        name="Bug",
        status=peri_scribe.models.FireStatus.ACTIVE,
        point=shapely.geometry.Point(1.0, 1.0),
        perimeters=(
            tests.peri_scribe.kml.kml_helpers.perimeter_with_time(
                tests.peri_scribe.kml.kml_helpers.square(2.0),
                first_time,
            ),
            tests.peri_scribe.kml.kml_helpers.perimeter_with_time(
                tests.peri_scribe.kml.kml_helpers.square(4.0),
                second_time,
            ),
        ),
        progression_rings=(
            peri_scribe.perimeters.progression.Ring(
                geometry=tests.peri_scribe.kml.kml_helpers.square(1.0),
                observation_time=first_time,
            ),
            peri_scribe.perimeters.progression.Ring(
                geometry=tests.peri_scribe.kml.kml_helpers.square(2.0),
                observation_time=second_time,
            ),
        ),
    )
    writer = peri_scribe.kml.geometry.KmlWriter()
    peri_scribe.kml.folders.fire_folder(
        writer,
        fire,
        style_urls,
        peri_scribe.kml.builder.ring_style_urls_for([fire]),
    )
    folder = tests.peri_scribe.kml.kml_helpers.folder_named(
        tests.peri_scribe.kml.kml_helpers.document_from_writer(writer),
        "Bug",
    )
    assert tests.peri_scribe.kml.kml_helpers.placemark_names(folder) == ["Bug"]
    perimeters_folder = tests.peri_scribe.kml.kml_helpers.folder_named(
        folder,
        "Perimeters",
    )
    assert tests.peri_scribe.kml.kml_helpers.placemark_names(perimeters_folder) == [
        "08/07 13:00 Perimeter",
        "08/05 13:00 Perimeter",
    ]
    interior_folder = tests.peri_scribe.kml.kml_helpers.folder_named(folder, "Interior")
    assert tests.peri_scribe.kml.kml_helpers.placemark_names(interior_folder) == [
        "08/07 13:00 Interior",
        "08/05 13:00 Interior",
    ]
    first_interior = tests.peri_scribe.kml.kml_helpers.placemark_named(
        interior_folder,
        "08/05 13:00 Interior",
    )
    second_interior = tests.peri_scribe.kml.kml_helpers.placemark_named(
        interior_folder,
        "08/07 13:00 Interior",
    )
    # The rings are styled by their day's color rather than a single fill; with no
    # area on any ring the active span is the first ring alone, so both clamp to the
    # hottest color.
    assert (
        tests.peri_scribe.kml.kml_helpers.placemark_style_url(first_interior)
        == "#ring-fill-ac1701"
    )
    assert (
        tests.peri_scribe.kml.kml_helpers.placemark_style_url(second_interior)
        == "#ring-fill-ac1701"
    )
    assert {
        name: tests.peri_scribe.kml.kml_helpers.draw_order(
            tests.peri_scribe.kml.kml_helpers.placemark_named(interior_folder, name),
        )
        for name in ("08/05 13:00 Interior", "08/07 13:00 Interior")
    } == {
        "08/05 13:00 Interior": 0,
        "08/07 13:00 Interior": 1,
    }
    # The outlines stack above the interior rings, and the point draws above both.
    assert {
        name: tests.peri_scribe.kml.kml_helpers.draw_order(
            tests.peri_scribe.kml.kml_helpers.placemark_named(container, name),
        )
        for container, name in (
            (perimeters_folder, "08/05 13:00 Perimeter"),
            (perimeters_folder, "08/07 13:00 Perimeter"),
            (folder, "Bug"),
        )
    } == {
        "08/05 13:00 Perimeter": 3,
        "08/07 13:00 Perimeter": 4,
        "Bug": 5,
    }
    # The rings fill the interior instead of the complete latest perimeter.
    assert set(
        tests.peri_scribe.kml.kml_helpers.exterior_coordinates(first_interior),
    ) == {
        (-0.5, -0.5),
        (0.5, -0.5),
        (0.5, 0.5),
        (-0.5, 0.5),
    }
    assert set(
        tests.peri_scribe.kml.kml_helpers.exterior_coordinates(second_interior),
    ) == {
        (-1.0, -1.0),
        (1.0, -1.0),
        (1.0, 1.0),
        (-1.0, 1.0),
    }


def test_fire_folder_falls_back_to_complete_perimeter_without_dated_rings(
    style_urls: dict[str, str],
) -> None:
    fire = peri_scribe.kml.fire_data.FireGeometry(
        name="Bug",
        status=peri_scribe.models.FireStatus.ACTIVE,
        point=shapely.geometry.Point(1.0, 1.0),
        perimeters=(
            tests.peri_scribe.kml.kml_helpers.perimeter_with_time(
                tests.peri_scribe.kml.kml_helpers.square(1.0),
            ),
        ),
        progression_rings=(
            peri_scribe.perimeters.progression.Ring(
                geometry=tests.peri_scribe.kml.kml_helpers.square(1.0),
                observation_time=None,
            ),
        ),
    )
    writer = peri_scribe.kml.geometry.KmlWriter()
    peri_scribe.kml.folders.fire_folder(
        writer,
        fire,
        style_urls,
        peri_scribe.kml.builder.ring_style_urls_for([fire]),
    )
    folder = tests.peri_scribe.kml.kml_helpers.folder_named(
        tests.peri_scribe.kml.kml_helpers.document_from_writer(writer),
        "Bug",
    )
    assert tests.peri_scribe.kml.kml_helpers.placemark_names(folder) == [
        "Bug",
        "Unknown Mapping",
    ]
    assert tests.peri_scribe.kml.kml_helpers.placemark_names(
        tests.peri_scribe.kml.kml_helpers.folder_named(folder, "Interior"),
    ) == ["Interior"]


def test_fire_folder_without_point_or_perimeters_is_empty(
    style_urls: dict[str, str],
) -> None:
    fire = peri_scribe.kml.fire_data.FireGeometry(
        name="Bug",
        status=peri_scribe.models.FireStatus.ACTIVE,
        point=None,
        perimeters=(),
    )
    writer = peri_scribe.kml.geometry.KmlWriter()
    peri_scribe.kml.folders.fire_folder(
        writer,
        fire,
        style_urls,
        peri_scribe.kml.builder.ring_style_urls_for([fire]),
    )
    folder = tests.peri_scribe.kml.kml_helpers.folder_named(
        tests.peri_scribe.kml.kml_helpers.document_from_writer(writer),
        "Bug",
    )
    assert tests.peri_scribe.kml.kml_helpers.placemark_names(folder) == []
    assert tests.peri_scribe.kml.kml_helpers.folder_names(folder) == []


def test_fire_folder_lists_point_tour_and_interior_in_order(
    style_urls: dict[str, str],
) -> None:
    first_time = datetime.datetime(2026, 8, 5, 20, 0, tzinfo=datetime.UTC)
    second_time = datetime.datetime(2026, 8, 7, 20, 0, tzinfo=datetime.UTC)
    fire = peri_scribe.kml.fire_data.FireGeometry(
        name="Bug",
        status=peri_scribe.models.FireStatus.ACTIVE,
        point=shapely.geometry.Point(1.0, 1.0),
        perimeters=(),
        progression_rings=(
            peri_scribe.perimeters.progression.Ring(
                geometry=tests.peri_scribe.kml.kml_helpers.square(1.0),
                observation_time=first_time,
            ),
            peri_scribe.perimeters.progression.Ring(
                geometry=tests.peri_scribe.kml.kml_helpers.square(2.0),
                observation_time=second_time,
            ),
        ),
    )
    writer = peri_scribe.kml.geometry.KmlWriter()
    peri_scribe.kml.folders.fire_folder(
        writer,
        fire,
        style_urls,
        peri_scribe.kml.builder.ring_style_urls_for([fire]),
    )
    bug_folder = tests.peri_scribe.kml.kml_helpers.folder_named(
        tests.peri_scribe.kml.kml_helpers.document_from_writer(writer),
        "Bug",
    )
    features = [
        child
        for child in bug_folder
        if child.tag
        in {
            tests.peri_scribe.kml.kml_helpers.kml_tag("Folder"),
            tests.peri_scribe.kml.kml_helpers.kml_tag("Placemark"),
            tests.peri_scribe.kml.kml_helpers.gx_tag("Tour"),
        }
    ]
    assert [
        (
            feature.tag,
            feature.findtext(tests.peri_scribe.kml.kml_helpers.kml_tag("name")),
        )
        for feature in features
    ] == [
        (tests.peri_scribe.kml.kml_helpers.kml_tag("Placemark"), "Bug"),
        (tests.peri_scribe.kml.kml_helpers.gx_tag("Tour"), "Progression"),
        (tests.peri_scribe.kml.kml_helpers.kml_tag("Folder"), "Interior"),
    ]
    tour = tests.peri_scribe.kml.kml_helpers.tour_named(bug_folder, "Progression")
    updates = tests.peri_scribe.kml.kml_helpers.tour_primitives(
        tour,
        tests.peri_scribe.kml.kml_helpers.gx_tag("AnimatedUpdate"),
    )
    waits = tests.peri_scribe.kml.kml_helpers.tour_primitives(
        tour,
        tests.peri_scribe.kml.kml_helpers.gx_tag("Wait"),
    )
    interior_folder = tests.peri_scribe.kml.kml_helpers.folder_named(
        bug_folder,
        "Interior",
    )
    interior = [
        tests.peri_scribe.kml.kml_helpers.placemark_named(
            interior_folder,
            "08/05 13:00 Interior",
        ),
        tests.peri_scribe.kml.kml_helpers.placemark_named(
            interior_folder,
            "08/07 13:00 Interior",
        ),
    ]
    assert len(updates) == len(interior)
    assert len(waits) == len(interior)
    interior_ids = [placemark.get("id") for placemark in interior]
    assert [
        tests.peri_scribe.kml.kml_helpers.update_visibility_by_target(update)
        for update in updates
    ] == [
        {interior_ids[0]: 1, interior_ids[1]: 0},
        {interior_ids[0]: 1, interior_ids[1]: 1},
    ]
    assert [
        tests.peri_scribe.kml.kml_helpers.wait_duration(wait) for wait in waits
    ] == [2.0, 1.0]


def test_fire_folder_adds_tour_for_fallback_polygon(
    style_urls: dict[str, str],
) -> None:
    fire = peri_scribe.kml.fire_data.FireGeometry(
        name="Bug",
        status=peri_scribe.models.FireStatus.ACTIVE,
        point=shapely.geometry.Point(1.0, 1.0),
        perimeters=(
            tests.peri_scribe.kml.kml_helpers.perimeter_with_time(
                tests.peri_scribe.kml.kml_helpers.square(1.0),
            ),
        ),
    )
    writer = peri_scribe.kml.geometry.KmlWriter()
    peri_scribe.kml.folders.fire_folder(
        writer,
        fire,
        style_urls,
        peri_scribe.kml.builder.ring_style_urls_for([fire]),
    )
    bug_folder = tests.peri_scribe.kml.kml_helpers.folder_named(
        tests.peri_scribe.kml.kml_helpers.document_from_writer(writer),
        "Bug",
    )
    tour = tests.peri_scribe.kml.kml_helpers.tour_named(bug_folder, "Progression")
    updates = tests.peri_scribe.kml.kml_helpers.tour_primitives(
        tour,
        tests.peri_scribe.kml.kml_helpers.gx_tag("AnimatedUpdate"),
    )
    waits = tests.peri_scribe.kml.kml_helpers.tour_primitives(
        tour,
        tests.peri_scribe.kml.kml_helpers.gx_tag("Wait"),
    )
    assert len(updates) == 1
    assert len(waits) == 1
    assert [
        tests.peri_scribe.kml.kml_helpers.wait_duration(wait) for wait in waits
    ] == [1.0]
    interior = tests.peri_scribe.kml.kml_helpers.placemark_named(
        tests.peri_scribe.kml.kml_helpers.folder_named(bug_folder, "Interior"),
        "Interior",
    )
    assert tests.peri_scribe.kml.kml_helpers.update_visibility_by_target(
        updates[0],
    ) == {
        interior.get("id"): 1,
    }


def test_fire_folder_without_polygons_has_no_tour(
    style_urls: dict[str, str],
) -> None:
    fire = peri_scribe.kml.fire_data.FireGeometry(
        name="Bug",
        status=peri_scribe.models.FireStatus.ACTIVE,
        point=shapely.geometry.Point(1.0, 1.0),
        perimeters=(),
    )
    writer = peri_scribe.kml.geometry.KmlWriter()
    peri_scribe.kml.folders.fire_folder(
        writer,
        fire,
        style_urls,
        peri_scribe.kml.builder.ring_style_urls_for([fire]),
    )
    bug_folder = tests.peri_scribe.kml.kml_helpers.folder_named(
        tests.peri_scribe.kml.kml_helpers.document_from_writer(writer),
        "Bug",
    )
    assert [
        child
        for child in bug_folder
        if child.tag == tests.peri_scribe.kml.kml_helpers.gx_tag("Tour")
    ] == []


def test_fire_folder_without_rings_holds_point_only(
    style_urls: dict[str, str],
) -> None:
    fire = peri_scribe.kml.fire_data.FireGeometry(
        name="Bug",
        status=peri_scribe.models.FireStatus.ACTIVE,
        point=shapely.geometry.Point(1.0, 1.0),
        perimeters=(),
    )
    writer = peri_scribe.kml.geometry.KmlWriter()
    peri_scribe.kml.folders.fire_folder(
        writer,
        fire,
        style_urls,
        peri_scribe.kml.builder.ring_style_urls_for([fire]),
    )
    bug_folder = tests.peri_scribe.kml.kml_helpers.folder_named(
        tests.peri_scribe.kml.kml_helpers.document_from_writer(writer),
        "Bug",
    )
    assert tests.peri_scribe.kml.kml_helpers.placemark_names(bug_folder) == ["Bug"]
    assert tests.peri_scribe.kml.kml_helpers.folder_names(bug_folder) == []


def test_fire_folder_holds_point_and_ring_folders(
    style_urls: dict[str, str],
) -> None:
    point = shapely.geometry.Point(1.0, 1.0)
    fire = peri_scribe.kml.fire_data.FireGeometry(
        name="Bug",
        status=peri_scribe.models.FireStatus.ACTIVE,
        point=point,
        perimeters=(),
        progression_rings=(
            peri_scribe.perimeters.progression.Ring(
                geometry=tests.peri_scribe.kml.kml_helpers.square(1.0),
                observation_time=datetime.datetime(
                    2026,
                    8,
                    13,
                    20,
                    0,
                    tzinfo=datetime.UTC,
                ),
                area=100.0,
            ),
            peri_scribe.perimeters.progression.Ring(
                geometry=tests.peri_scribe.kml.kml_helpers.square(2.0),
                observation_time=datetime.datetime(
                    2026,
                    8,
                    14,
                    20,
                    0,
                    tzinfo=datetime.UTC,
                ),
                area=100.0,
            ),
            peri_scribe.perimeters.progression.Ring(
                geometry=tests.peri_scribe.kml.kml_helpers.square(3.0),
                observation_time=datetime.datetime(
                    2026,
                    8,
                    15,
                    20,
                    0,
                    tzinfo=datetime.UTC,
                ),
                area=100.0,
            ),
        ),
    )
    ring_style_urls = ring_style_urls_for(fire)
    writer = peri_scribe.kml.geometry.KmlWriter()
    peri_scribe.kml.folders.fire_folder(
        writer,
        fire,
        style_urls,
        ring_style_urls,
    )
    bug_folder = tests.peri_scribe.kml.kml_helpers.folder_named(
        tests.peri_scribe.kml.kml_helpers.document_from_writer(writer),
        "Bug",
    )
    assert tests.peri_scribe.kml.kml_helpers.placemark_names(bug_folder) == ["Bug"]
    assert tests.peri_scribe.kml.kml_helpers.folder_names(bug_folder) == ["Interior"]

    interior_folder = tests.peri_scribe.kml.kml_helpers.folder_named(
        bug_folder,
        "Interior",
    )
    assert tests.peri_scribe.kml.kml_helpers.placemark_names(interior_folder) == [
        "08/15 13:00 Interior",
        "08/14 13:00 Interior",
        "08/13 13:00 Interior",
    ]

    # The fire has three equal-area rings, so its active span holds all three and its
    # coolest color sits partway up the ramp; the rings interpolate by timestamp.
    assert (
        tests.peri_scribe.kml.kml_helpers.placemark_style_url(
            tests.peri_scribe.kml.kml_helpers.placemark_named(
                interior_folder,
                "08/13 13:00 Interior",
            ),
        )
        == "#ring-fill-fc8524"
    )
    assert (
        tests.peri_scribe.kml.kml_helpers.placemark_style_url(
            tests.peri_scribe.kml.kml_helpers.placemark_named(
                interior_folder,
                "08/14 13:00 Interior",
            ),
        )
        == "#ring-fill-e24209"
    )
    assert (
        tests.peri_scribe.kml.kml_helpers.placemark_style_url(
            tests.peri_scribe.kml.kml_helpers.placemark_named(
                interior_folder,
                "08/15 13:00 Interior",
            ),
        )
        == "#ring-fill-ac1701"
    )

    assert {
        name: tests.peri_scribe.kml.kml_helpers.draw_order(
            tests.peri_scribe.kml.kml_helpers.placemark_named(interior_folder, name),
        )
        for name in (
            "08/13 13:00 Interior",
            "08/14 13:00 Interior",
            "08/15 13:00 Interior",
        )
    } == {
        "08/13 13:00 Interior": 0,
        "08/14 13:00 Interior": 1,
        "08/15 13:00 Interior": 2,
    }
    assert (
        tests.peri_scribe.kml.kml_helpers.draw_order(
            tests.peri_scribe.kml.kml_helpers.placemark_named(bug_folder, "Bug"),
        )
        == len(fire.progression_rings) + 1
    )

    assert (
        tests.peri_scribe.kml.kml_helpers.folder_item_icon_href(interior_folder)
        == "interior-progression.png"
    )

    assert set(
        tests.peri_scribe.kml.kml_helpers.exterior_coordinates(
            tests.peri_scribe.kml.kml_helpers.placemark_named(
                interior_folder,
                "08/15 13:00 Interior",
            ),
        ),
    ) == {
        (-1.5, -1.5),
        (1.5, -1.5),
        (1.5, 1.5),
        (-1.5, 1.5),
    }
    assert set(
        tests.peri_scribe.kml.kml_helpers.exterior_coordinates(
            tests.peri_scribe.kml.kml_helpers.placemark_named(
                interior_folder,
                "08/13 13:00 Interior",
            ),
        ),
    ) == {
        (-0.5, -0.5),
        (0.5, -0.5),
        (0.5, 0.5),
        (-0.5, 0.5),
    }
    assert set(
        tests.peri_scribe.kml.kml_helpers.exterior_coordinates(
            tests.peri_scribe.kml.kml_helpers.placemark_named(
                interior_folder,
                "08/14 13:00 Interior",
            ),
        ),
    ) == {
        (-1.0, -1.0),
        (1.0, -1.0),
        (1.0, 1.0),
        (-1.0, 1.0),
    }


def test_fire_folder_falls_back_to_latest_perimeter(
    style_urls: dict[str, str],
) -> None:
    point = shapely.geometry.Point(1.0, 1.0)
    latest_time = datetime.datetime(2026, 8, 15, 20, 0, tzinfo=datetime.UTC)
    fire = peri_scribe.kml.fire_data.FireGeometry(
        name="Bug",
        status=peri_scribe.models.FireStatus.ACTIVE,
        point=point,
        perimeters=(
            tests.peri_scribe.kml.kml_helpers.perimeter_with_time(
                tests.peri_scribe.kml.kml_helpers.square(3.0),
                latest_time,
            ),
        ),
    )
    ring_style_urls = ring_style_urls_for(fire)
    writer = peri_scribe.kml.geometry.KmlWriter()
    peri_scribe.kml.folders.fire_folder(
        writer,
        fire,
        style_urls,
        ring_style_urls,
    )
    bug_folder = tests.peri_scribe.kml.kml_helpers.folder_named(
        tests.peri_scribe.kml.kml_helpers.document_from_writer(writer),
        "Bug",
    )
    interior_folder = tests.peri_scribe.kml.kml_helpers.folder_named(
        bug_folder,
        "Interior",
    )
    # The fire has no dated rings, so the interior is its complete latest perimeter in
    # the hottest color.
    assert tests.peri_scribe.kml.kml_helpers.placemark_names(interior_folder) == [
        "08/15 13:00 Interior",
    ]
    assert (
        tests.peri_scribe.kml.kml_helpers.placemark_style_url(
            tests.peri_scribe.kml.kml_helpers.placemark_named(
                interior_folder,
                "08/15 13:00 Interior",
            ),
        )
        == "#ring-fill-ac1701"
    )
    assert set(
        tests.peri_scribe.kml.kml_helpers.exterior_coordinates(
            tests.peri_scribe.kml.kml_helpers.placemark_named(
                interior_folder,
                "08/15 13:00 Interior",
            ),
        ),
    ) == {
        (-1.5, -1.5),
        (1.5, -1.5),
        (1.5, 1.5),
        (-1.5, 1.5),
    }


def test_fire_folder_lists_point_tour_and_rings_in_order(
    style_urls: dict[str, str],
) -> None:
    fire = peri_scribe.kml.fire_data.FireGeometry(
        name="Bug",
        status=peri_scribe.models.FireStatus.ACTIVE,
        point=shapely.geometry.Point(1.0, 1.0),
        perimeters=(),
        progression_rings=(
            peri_scribe.perimeters.progression.Ring(
                geometry=tests.peri_scribe.kml.kml_helpers.square(1.0),
                observation_time=datetime.datetime(
                    2026,
                    8,
                    13,
                    20,
                    0,
                    tzinfo=datetime.UTC,
                ),
            ),
            peri_scribe.perimeters.progression.Ring(
                geometry=tests.peri_scribe.kml.kml_helpers.square(2.0),
                observation_time=datetime.datetime(
                    2026,
                    8,
                    14,
                    20,
                    0,
                    tzinfo=datetime.UTC,
                ),
            ),
            peri_scribe.perimeters.progression.Ring(
                geometry=tests.peri_scribe.kml.kml_helpers.square(3.0),
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
    writer = peri_scribe.kml.geometry.KmlWriter()
    peri_scribe.kml.folders.fire_folder(
        writer,
        fire,
        style_urls,
        ring_style_urls_for(fire),
    )
    bug_folder = tests.peri_scribe.kml.kml_helpers.folder_named(
        tests.peri_scribe.kml.kml_helpers.document_from_writer(writer),
        "Bug",
    )
    features = [
        child
        for child in bug_folder
        if child.tag
        in {
            tests.peri_scribe.kml.kml_helpers.kml_tag("Folder"),
            tests.peri_scribe.kml.kml_helpers.kml_tag("Placemark"),
            tests.peri_scribe.kml.kml_helpers.gx_tag("Tour"),
        }
    ]
    assert [
        (
            feature.tag,
            feature.findtext(tests.peri_scribe.kml.kml_helpers.kml_tag("name")),
        )
        for feature in features
    ] == [
        (tests.peri_scribe.kml.kml_helpers.kml_tag("Placemark"), "Bug"),
        (tests.peri_scribe.kml.kml_helpers.gx_tag("Tour"), "Progression"),
        (tests.peri_scribe.kml.kml_helpers.kml_tag("Folder"), "Interior"),
    ]
    tour = tests.peri_scribe.kml.kml_helpers.tour_named(bug_folder, "Progression")
    updates = tests.peri_scribe.kml.kml_helpers.tour_primitives(
        tour,
        tests.peri_scribe.kml.kml_helpers.gx_tag("AnimatedUpdate"),
    )
    waits = tests.peri_scribe.kml.kml_helpers.tour_primitives(
        tour,
        tests.peri_scribe.kml.kml_helpers.gx_tag("Wait"),
    )
    interior_folder = tests.peri_scribe.kml.kml_helpers.folder_named(
        bug_folder,
        "Interior",
    )
    # All three rings live in the single Interior folder, listed newest first; the
    # tour still reveals them in the same chronological order the progression rings
    # are listed.
    interior = [
        tests.peri_scribe.kml.kml_helpers.placemark_named(
            interior_folder,
            name,
        )
        for name in (
            "08/15 13:00 Interior",
            "08/14 13:00 Interior",
            "08/13 13:00 Interior",
        )
    ]
    assert len(updates) == len(interior)
    assert len(waits) == len(interior)
    oldest_id = tests.peri_scribe.kml.kml_helpers.placemark_named(
        interior_folder,
        "08/13 13:00 Interior",
    ).get("id")
    middle_id = tests.peri_scribe.kml.kml_helpers.placemark_named(
        interior_folder,
        "08/14 13:00 Interior",
    ).get("id")
    newest_id = tests.peri_scribe.kml.kml_helpers.placemark_named(
        interior_folder,
        "08/15 13:00 Interior",
    ).get("id")
    assert [
        tests.peri_scribe.kml.kml_helpers.update_visibility_by_target(update)
        for update in updates
    ] == [
        {oldest_id: 1, middle_id: 0, newest_id: 0},
        {oldest_id: 1, middle_id: 1, newest_id: 0},
        {oldest_id: 1, middle_id: 1, newest_id: 1},
    ]
    assert [
        tests.peri_scribe.kml.kml_helpers.wait_duration(wait) for wait in waits
    ] == [1.0, 1.0, 1.0]


def test_fire_folder_hides_its_tree(style_urls: dict[str, str]) -> None:
    point = shapely.geometry.Point(1.0, 1.0)
    fire = peri_scribe.kml.fire_data.FireGeometry(
        name="Bug",
        status=peri_scribe.models.FireStatus.ACTIVE,
        point=point,
        perimeters=(),
        progression_rings=(
            peri_scribe.perimeters.progression.Ring(
                geometry=tests.peri_scribe.kml.kml_helpers.square(1.0),
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
    writer = peri_scribe.kml.geometry.KmlWriter()
    peri_scribe.kml.folders.fire_folder(
        writer,
        fire,
        style_urls,
        ring_style_urls_for(fire),
        visible=False,
    )
    folder = tests.peri_scribe.kml.kml_helpers.folder_named(
        tests.peri_scribe.kml.kml_helpers.document_from_writer(writer),
        "Bug",
    )
    tests.peri_scribe.kml.kml_helpers.assert_tree_invisible(folder)


def test_fire_folder_can_load_visible(style_urls: dict[str, str]) -> None:
    point = shapely.geometry.Point(1.0, 1.0)
    fire = peri_scribe.kml.fire_data.FireGeometry(
        name="Bug",
        status=peri_scribe.models.FireStatus.ACTIVE,
        point=point,
        perimeters=(),
        progression_rings=(
            peri_scribe.perimeters.progression.Ring(
                geometry=tests.peri_scribe.kml.kml_helpers.square(1.0),
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
    writer = peri_scribe.kml.geometry.KmlWriter()
    peri_scribe.kml.folders.fire_folder(
        writer,
        fire,
        style_urls,
        ring_style_urls_for(fire),
        visible=True,
    )
    folder = tests.peri_scribe.kml.kml_helpers.folder_named(
        tests.peri_scribe.kml.kml_helpers.document_from_writer(writer),
        "Bug",
    )
    tests.peri_scribe.kml.kml_helpers.assert_tree_visible(folder)


def test_status_folder_name_for_active() -> None:
    assert (
        peri_scribe.kml.folders.status_folder_name(
            peri_scribe.models.FireStatus.ACTIVE,
        )
        == "Active Fires"
    )


def score_entry(
    name: str,
    identifier: str | None,
    score: int,
    explanation: str,
) -> peri_scribe.models.FireScoreEntry:
    """Return a saved score for a fire.

    Args:
        name: The fire's name.
        identifier: The fire's identifier, or None.
        score: The fire's score.
        explanation: Why the fire has the score.

    Returns:
        The score entry.
    """
    return peri_scribe.models.FireScoreEntry(
        name=name,
        identifier=identifier,
        score=score,
        components=peri_scribe.models.FireScoreComponents(
            size=0,
            growth=0,
            first_mapping=0,
            buildings=0,
            evacuation=0,
            importance=0,
        ),
        explanation=explanation,
    )


def test_top_fires_matches_by_identifier() -> None:
    big = peri_scribe.kml.fire_data.FireGeometry(
        name="Timber",
        status=peri_scribe.models.FireStatus.ACTIVE,
        point=None,
        perimeters=(),
        identifiers=frozenset({"id-big", "alias-big"}),
    )
    small = peri_scribe.kml.fire_data.FireGeometry(
        name="Timber",
        status=peri_scribe.models.FireStatus.INACTIVE,
        point=None,
        perimeters=(),
        identifiers=frozenset({"id-small"}),
    )
    scores = peri_scribe.models.FireScores(
        version="test",
        fires=[
            score_entry(
                "Timber",
                "id-small",
                4,
                "Over 5 structures within a mile.",
            ),
            score_entry(
                "Timber",
                "id-big",
                470,
                "Over 250 structures within a mile.",
            ),
        ],
    )
    assert peri_scribe.kml.folders.top_fires([big, small], scores) == [big, small]


def test_top_fires_matches_any_fire_identifier() -> None:
    fire = peri_scribe.kml.fire_data.FireGeometry(
        name="Timber",
        status=peri_scribe.models.FireStatus.ACTIVE,
        point=None,
        perimeters=(),
        identifiers=frozenset({"alias-big", "id-big"}),
    )
    scores = peri_scribe.models.FireScores(
        version="test",
        fires=[
            score_entry(
                "Timber",
                "id-big",
                470,
                "Over 250 structures within a mile.",
            ),
        ],
    )
    assert peri_scribe.kml.folders.top_fires([fire], scores) == [fire]


def test_top_fires_falls_back_to_name_without_identifier_match() -> None:
    fire = peri_scribe.kml.fire_data.FireGeometry(
        name="Bug",
        status=peri_scribe.models.FireStatus.ACTIVE,
        point=None,
        perimeters=(),
    )
    scores = peri_scribe.models.FireScores(
        version="test",
        fires=[score_entry("Bug", None, 12, "A Type 1 Incident.")],
    )
    assert peri_scribe.kml.folders.top_fires([fire], scores) == [fire]


def test_top_fires_excludes_scores_without_matching_fire() -> None:
    fire = peri_scribe.kml.fire_data.FireGeometry(
        name="Bug",
        status=peri_scribe.models.FireStatus.ACTIVE,
        point=None,
        perimeters=(),
        identifiers=frozenset({"id-bug"}),
    )
    scores = peri_scribe.models.FireScores(
        version="test",
        fires=[score_entry("Missing", "id-missing", 500, "A Type 1 Incident.")],
    )
    assert peri_scribe.kml.folders.top_fires([fire], scores) == []


REFERENCE_TIME = datetime.datetime(2026, 8, 20, 12, 0, tzinfo=datetime.UTC)


def active_fire(
    name: str,
    *,
    description: peri_scribe.kml.descriptions.FireDescription | None = None,
    perimeters: tuple[peri_scribe.kml.fire_data.Perimeter, ...] = (),
    identifiers: frozenset[str] = frozenset(),
) -> peri_scribe.kml.fire_data.FireGeometry:
    """Return an active fire with the given description and perimeters.

    Args:
        name: The fire's name.
        description: The fire's latest state, or None.
        perimeters: The fire's perimeters, oldest first.
        identifiers: The fire's identifiers.

    Returns:
        The active fire.
    """
    return peri_scribe.kml.fire_data.FireGeometry(
        name=name,
        status=peri_scribe.models.FireStatus.ACTIVE,
        point=None,
        perimeters=perimeters,
        description=description,
        identifiers=identifiers,
    )


def growing_fire(
    name: str,
    baseline_side: float,
    latest_side: float,
    reference_time: datetime.datetime,
) -> peri_scribe.kml.fire_data.FireGeometry:
    """Return an active fire growing from *baseline_side* to *latest_side*.

    The baseline perimeter sits at the start of the 48-hour window and the latest one
    at *reference_time*, so the fire's growth over the window is measurable.

    Args:
        name: The fire's name.
        baseline_side: The side length of the baseline square.
        latest_side: The side length of the latest square.
        reference_time: The time the snapshot is as of.

    Returns:
        The growing fire.
    """
    return active_fire(
        name,
        perimeters=(
            peri_scribe.kml.fire_data.Perimeter(
                geometry=tests.peri_scribe.kml.kml_helpers.square(baseline_side),
                observation_time=reference_time - datetime.timedelta(hours=48),
            ),
            peri_scribe.kml.fire_data.Perimeter(
                geometry=tests.peri_scribe.kml.kml_helpers.square(latest_side),
                observation_time=reference_time,
            ),
        ),
    )


def test_score_maps_partitions_entries_by_identity() -> None:
    identified = score_entry("Timber", "id-big", 470, "Large.")
    named = score_entry("Bug", None, 12, "A Type 1 Incident.")
    scores = peri_scribe.models.FireScores(
        version="test",
        fires=[identified, named],
    )

    by_identifier, by_name = peri_scribe.kml.folders.score_maps(scores)

    assert by_identifier == {"id-big": identified}
    assert by_name == {"Bug": named}


def test_score_value_for_fire_matches_by_identifier() -> None:
    identified = score_entry("Timber", "id-big", 470, "Large.")
    scores = peri_scribe.models.FireScores(version="test", fires=[identified])
    by_identifier, by_name = peri_scribe.kml.folders.score_maps(scores)
    fire = active_fire("Timber", identifiers=frozenset({"id-big", "alias-big"}))

    assert (
        peri_scribe.kml.folders.score_value_for_fire(
            fire,
            by_identifier,
            by_name,
        )
        == identified.score
    )


def test_score_value_for_fire_falls_back_to_name() -> None:
    named = score_entry("Bug", None, 12, "A Type 1 Incident.")
    scores = peri_scribe.models.FireScores(version="test", fires=[named])
    by_identifier, by_name = peri_scribe.kml.folders.score_maps(scores)
    fire = active_fire("Bug")

    assert (
        peri_scribe.kml.folders.score_value_for_fire(
            fire,
            by_identifier,
            by_name,
        )
        == named.score
    )


def test_score_value_for_fire_returns_none_without_match() -> None:
    named = score_entry("Bug", None, 12, "A Type 1 Incident.")
    scores = peri_scribe.models.FireScores(version="test", fires=[named])
    by_identifier, by_name = peri_scribe.kml.folders.score_maps(scores)
    fire = active_fire("Missing", identifiers=frozenset({"id-missing"}))

    assert (
        peri_scribe.kml.folders.score_value_for_fire(
            fire,
            by_identifier,
            by_name,
        )
        is None
    )


def test_notable_score_threshold_uses_top_fraction() -> None:
    fires = [active_fire(f"Fire {index}") for index in range(10)]
    scores = peri_scribe.models.FireScores(
        version="test",
        fires=[
            score_entry(f"Fire {index}", None, index + 1, "Notable.")
            for index in range(10)
        ],
    )
    # Ten fires keep the highest-scoring fifth, so the cutoff is the second-highest
    # score.
    expected_threshold = sorted(
        (entry.score for entry in scores.fires),
        reverse=True,
    )[1]
    assert (
        peri_scribe.kml.folders.notable_score_threshold(fires, scores)
        == expected_threshold
    )


def test_notable_score_threshold_ignores_inactive_fires() -> None:
    fire = peri_scribe.kml.fire_data.FireGeometry(
        name="Old",
        status=peri_scribe.models.FireStatus.INACTIVE,
        point=None,
        perimeters=(),
    )
    scores = peri_scribe.models.FireScores(
        version="test",
        fires=[score_entry("Old", None, 500, "A Type 1 Incident.")],
    )

    assert peri_scribe.kml.folders.notable_score_threshold([fire], scores) is None


def test_notable_score_threshold_returns_none_without_active_score() -> None:
    fire = active_fire("Unscored")
    scores = peri_scribe.models.FireScores(version="test", fires=[])

    assert peri_scribe.kml.folders.notable_score_threshold([fire], scores) is None


def test_new_notable_fires_returns_empty_without_reference_time() -> None:
    fire = active_fire(
        "New",
        description=peri_scribe.kml.descriptions.FireDescription(
            discovery_time=REFERENCE_TIME,
        ),
    )
    scores = peri_scribe.models.FireScores(
        version="test",
        fires=[score_entry("New", None, 10, "Notable.")],
    )

    assert peri_scribe.kml.folders.new_notable_fires([fire], scores, None) == []


def test_new_notable_fires_returns_empty_without_active_score() -> None:
    fire = active_fire(
        "Unscored",
        description=peri_scribe.kml.descriptions.FireDescription(
            discovery_time=REFERENCE_TIME,
        ),
    )
    scores = peri_scribe.models.FireScores(version="test", fires=[])

    assert (
        peri_scribe.kml.folders.new_notable_fires(
            [fire],
            scores,
            REFERENCE_TIME,
        )
        == []
    )


def test_new_notable_fires_includes_recent_high_score_fire() -> None:
    fires = [active_fire(f"Fire {index}") for index in range(10)]
    scores = peri_scribe.models.FireScores(
        version="test",
        fires=[
            score_entry(f"Fire {index}", None, index + 1, "Notable.")
            for index in range(10)
        ],
    )
    recent = REFERENCE_TIME - datetime.timedelta(days=1)
    candidate = active_fire(
        "New",
        description=peri_scribe.kml.descriptions.FireDescription(
            discovery_time=recent,
        ),
    )
    scores.fires.append(score_entry("New", None, 10, "Notable."))
    fires.append(candidate)

    assert peri_scribe.kml.folders.new_notable_fires(
        fires,
        scores,
        REFERENCE_TIME,
    ) == [candidate]


def test_new_notable_fires_sorts_by_score_descending() -> None:
    fires = [active_fire(f"Fire {index}") for index in range(10)]
    scores = peri_scribe.models.FireScores(
        version="test",
        fires=[
            score_entry(f"Fire {index}", None, index + 1, "Notable.")
            for index in range(10)
        ],
    )
    recent = REFERENCE_TIME - datetime.timedelta(days=1)
    lower = active_fire(
        "Lower",
        description=peri_scribe.kml.descriptions.FireDescription(
            discovery_time=recent,
        ),
    )
    higher = active_fire(
        "Higher",
        description=peri_scribe.kml.descriptions.FireDescription(
            discovery_time=recent,
        ),
    )
    scores.fires.append(score_entry("Lower", None, 10, "Notable."))
    scores.fires.append(score_entry("Higher", None, 12, "Notable."))
    fires.extend([lower, higher])

    assert peri_scribe.kml.folders.new_notable_fires(
        fires,
        scores,
        REFERENCE_TIME,
    ) == [higher, lower]


def test_new_notable_fires_excludes_stale_discovery() -> None:
    fires = [active_fire(f"Fire {index}") for index in range(10)]
    scores = peri_scribe.models.FireScores(
        version="test",
        fires=[
            score_entry(f"Fire {index}", None, index + 1, "Notable.")
            for index in range(10)
        ],
    )
    stale = REFERENCE_TIME - datetime.timedelta(days=6)
    candidate = active_fire(
        "Old",
        description=peri_scribe.kml.descriptions.FireDescription(
            discovery_time=stale,
        ),
    )
    scores.fires.append(score_entry("Old", None, 20, "Notable."))
    fires.append(candidate)

    assert (
        peri_scribe.kml.folders.new_notable_fires(
            fires,
            scores,
            REFERENCE_TIME,
        )
        == []
    )


def test_new_notable_fires_excludes_future_discovery() -> None:
    fires = [active_fire(f"Fire {index}") for index in range(10)]
    scores = peri_scribe.models.FireScores(
        version="test",
        fires=[
            score_entry(f"Fire {index}", None, index + 1, "Notable.")
            for index in range(10)
        ],
    )
    future = REFERENCE_TIME + datetime.timedelta(hours=1)
    candidate = active_fire(
        "Future",
        description=peri_scribe.kml.descriptions.FireDescription(
            discovery_time=future,
        ),
    )
    scores.fires.append(score_entry("Future", None, 20, "Notable."))
    fires.append(candidate)

    assert (
        peri_scribe.kml.folders.new_notable_fires(
            fires,
            scores,
            REFERENCE_TIME,
        )
        == []
    )


def test_new_notable_fires_excludes_missing_description() -> None:
    fires = [active_fire(f"Fire {index}") for index in range(10)]
    scores = peri_scribe.models.FireScores(
        version="test",
        fires=[
            score_entry(f"Fire {index}", None, index + 1, "Notable.")
            for index in range(10)
        ],
    )
    candidate = active_fire("NoDescription")
    scores.fires.append(score_entry("NoDescription", None, 20, "Notable."))
    fires.append(candidate)

    assert (
        peri_scribe.kml.folders.new_notable_fires(
            fires,
            scores,
            REFERENCE_TIME,
        )
        == []
    )


def test_new_notable_fires_excludes_missing_discovery_time() -> None:
    fires = [active_fire(f"Fire {index}") for index in range(10)]
    scores = peri_scribe.models.FireScores(
        version="test",
        fires=[
            score_entry(f"Fire {index}", None, index + 1, "Notable.")
            for index in range(10)
        ],
    )
    candidate = active_fire(
        "NoDiscovery",
        description=peri_scribe.kml.descriptions.FireDescription(),
    )
    scores.fires.append(score_entry("NoDiscovery", None, 20, "Notable."))
    fires.append(candidate)

    assert (
        peri_scribe.kml.folders.new_notable_fires(
            fires,
            scores,
            REFERENCE_TIME,
        )
        == []
    )


def test_new_notable_fires_excludes_below_threshold() -> None:
    fires = [active_fire(f"Fire {index}") for index in range(10)]
    scores = peri_scribe.models.FireScores(
        version="test",
        fires=[
            score_entry(f"Fire {index}", None, index + 1, "Notable.")
            for index in range(10)
        ],
    )
    recent = REFERENCE_TIME - datetime.timedelta(days=1)
    candidate = active_fire(
        "Low",
        description=peri_scribe.kml.descriptions.FireDescription(
            discovery_time=recent,
        ),
    )
    scores.fires.append(score_entry("Low", None, 5, "Notable."))
    fires.append(candidate)

    assert (
        peri_scribe.kml.folders.new_notable_fires(
            fires,
            scores,
            REFERENCE_TIME,
        )
        == []
    )


def test_new_notable_fires_excludes_unscored_fire() -> None:
    fires = [active_fire(f"Fire {index}") for index in range(10)]
    scores = peri_scribe.models.FireScores(
        version="test",
        fires=[
            score_entry(f"Fire {index}", None, index + 1, "Notable.")
            for index in range(10)
        ],
    )
    recent = REFERENCE_TIME - datetime.timedelta(days=1)
    candidate = active_fire(
        "Unscored",
        description=peri_scribe.kml.descriptions.FireDescription(
            discovery_time=recent,
        ),
    )
    fires.append(candidate)

    assert (
        peri_scribe.kml.folders.new_notable_fires(
            fires,
            scores,
            REFERENCE_TIME,
        )
        == []
    )


def test_fire_growth_compares_latest_area_with_window_start() -> None:
    fire = growing_fire("Grower", 0.02, 0.03, REFERENCE_TIME)
    baseline = peri_scribe.units.area_in_acres(
        tests.peri_scribe.kml.kml_helpers.square(0.02),
    )
    latest = peri_scribe.units.area_in_acres(
        tests.peri_scribe.kml.kml_helpers.square(0.03),
    )

    growth_in_acres, growth_in_percent = peri_scribe.kml.folders.fire_growth(
        fire,
        REFERENCE_TIME,
    )

    assert growth_in_acres == pytest.approx(latest - baseline)
    assert growth_in_percent == pytest.approx((latest - baseline) / baseline * 100.0)


def test_fire_growth_sorts_perimeters_chronologically() -> None:
    fire = active_fire(
        "Scrambled",
        perimeters=(
            peri_scribe.kml.fire_data.Perimeter(
                geometry=tests.peri_scribe.kml.kml_helpers.square(0.03),
                observation_time=REFERENCE_TIME,
            ),
            peri_scribe.kml.fire_data.Perimeter(
                geometry=tests.peri_scribe.kml.kml_helpers.square(0.02),
                observation_time=REFERENCE_TIME - datetime.timedelta(hours=48),
            ),
        ),
    )
    baseline = peri_scribe.units.area_in_acres(
        tests.peri_scribe.kml.kml_helpers.square(0.02),
    )
    latest = peri_scribe.units.area_in_acres(
        tests.peri_scribe.kml.kml_helpers.square(0.03),
    )

    growth_in_acres, _growth_in_percent = peri_scribe.kml.folders.fire_growth(
        fire,
        REFERENCE_TIME,
    )

    assert growth_in_acres == pytest.approx(latest - baseline)


def test_fire_growth_without_timed_perimeters_is_unknown() -> None:
    fire = active_fire(
        "Timeless",
        perimeters=(
            peri_scribe.kml.fire_data.Perimeter(
                geometry=tests.peri_scribe.kml.kml_helpers.square(0.02),
                observation_time=None,
            ),
        ),
    )

    assert peri_scribe.kml.folders.fire_growth(fire, REFERENCE_TIME) == (None, None)


def test_fire_growth_without_window_start_counts_whole_area() -> None:
    fire = active_fire(
        "Newborn",
        perimeters=(
            peri_scribe.kml.fire_data.Perimeter(
                geometry=tests.peri_scribe.kml.kml_helpers.square(0.03),
                observation_time=REFERENCE_TIME - datetime.timedelta(hours=24),
            ),
            peri_scribe.kml.fire_data.Perimeter(
                geometry=tests.peri_scribe.kml.kml_helpers.square(0.04),
                observation_time=REFERENCE_TIME,
            ),
        ),
    )

    growth_in_acres, growth_in_percent = peri_scribe.kml.folders.fire_growth(
        fire,
        REFERENCE_TIME,
    )

    assert growth_in_acres == pytest.approx(
        peri_scribe.units.area_in_acres(
            tests.peri_scribe.kml.kml_helpers.square(0.04),
        ),
    )
    assert growth_in_percent is None


def test_fire_growth_percent_is_unknown_without_baseline_area() -> None:
    fire = active_fire(
        "FromNothing",
        perimeters=(
            peri_scribe.kml.fire_data.Perimeter(
                geometry=shapely.geometry.Point(0.0, 0.0),
                observation_time=REFERENCE_TIME - datetime.timedelta(hours=48),
            ),
            peri_scribe.kml.fire_data.Perimeter(
                geometry=tests.peri_scribe.kml.kml_helpers.square(0.03),
                observation_time=REFERENCE_TIME,
            ),
        ),
    )

    growth_in_acres, growth_in_percent = peri_scribe.kml.folders.fire_growth(
        fire,
        REFERENCE_TIME,
    )

    assert growth_in_percent is None
    assert growth_in_acres == pytest.approx(
        peri_scribe.units.area_in_acres(
            tests.peri_scribe.kml.kml_helpers.square(0.03),
        ),
    )


def test_fast_growing_fires_by_acres_filters_and_sorts() -> None:
    fires = [
        growing_fire("Small", 0.01, 0.015, REFERENCE_TIME),
        growing_fire("Huge", 0.02, 0.04, REFERENCE_TIME),
        growing_fire("Big", 0.02, 0.03, REFERENCE_TIME),
    ]

    assert [
        fire.name
        for fire in peri_scribe.kml.folders.fast_growing_fires_by_acres(
            fires,
            REFERENCE_TIME,
        )
    ] == ["Huge", "Big"]


def test_fast_growing_fires_by_acres_returns_empty_without_reference_time() -> None:
    fires = [growing_fire("Big", 0.02, 0.03, REFERENCE_TIME)]

    assert peri_scribe.kml.folders.fast_growing_fires_by_acres(fires, None) == []


def test_fast_growing_fires_by_acres_includes_zero_baseline_growth() -> None:
    fire = active_fire(
        "Newborn",
        perimeters=(
            peri_scribe.kml.fire_data.Perimeter(
                geometry=tests.peri_scribe.kml.kml_helpers.square(0.03),
                observation_time=REFERENCE_TIME,
            ),
        ),
    )

    assert peri_scribe.kml.folders.fast_growing_fires_by_acres(
        [fire],
        REFERENCE_TIME,
    ) == [fire]


def test_fast_growing_fires_by_acres_limits_to_top_count() -> None:
    fires = [
        growing_fire(f"Grower {index}", 0.02, 0.03, REFERENCE_TIME)
        for index in range(51)
    ]

    assert (
        len(
            peri_scribe.kml.folders.fast_growing_fires_by_acres(
                fires,
                REFERENCE_TIME,
            ),
        )
        == peri_scribe.kml.folders.TOP_FIRE_COUNT
    )


def test_fast_growing_fires_by_percent_filters_and_sorts() -> None:
    fires = [
        growing_fire("Small", 0.1, 0.102, REFERENCE_TIME),
        growing_fire("Huge", 0.03, 0.04, REFERENCE_TIME),
        growing_fire("Big", 0.02, 0.03, REFERENCE_TIME),
    ]

    assert [
        fire.name
        for fire in peri_scribe.kml.folders.fast_growing_fires_by_percent(
            fires,
            REFERENCE_TIME,
        )
    ] == ["Big", "Huge"]


def test_fast_growing_fires_by_percent_returns_empty_without_reference_time() -> None:
    fires = [growing_fire("Big", 0.02, 0.03, REFERENCE_TIME)]

    assert peri_scribe.kml.folders.fast_growing_fires_by_percent(fires, None) == []


def test_fast_growing_fires_by_percent_excludes_zero_baseline_growth() -> None:
    fire = active_fire(
        "Newborn",
        perimeters=(
            peri_scribe.kml.fire_data.Perimeter(
                geometry=tests.peri_scribe.kml.kml_helpers.square(0.03),
                observation_time=REFERENCE_TIME,
            ),
        ),
    )

    assert (
        peri_scribe.kml.folders.fast_growing_fires_by_percent(
            [fire],
            REFERENCE_TIME,
        )
        == []
    )


def test_fast_growing_fires_by_percent_limits_to_top_count() -> None:
    fires = [
        growing_fire(f"Grower {index}", 0.02, 0.03, REFERENCE_TIME)
        for index in range(51)
    ]

    assert (
        len(
            peri_scribe.kml.folders.fast_growing_fires_by_percent(
                fires,
                REFERENCE_TIME,
            ),
        )
        == peri_scribe.kml.folders.TOP_FIRE_COUNT
    )


def test_most_personnel_fires_sorts_known_personnel() -> None:
    low = active_fire(
        "Low",
        description=peri_scribe.kml.descriptions.FireDescription(
            total_personnel=10.0,
            observation_time=REFERENCE_TIME,
        ),
    )
    high = active_fire(
        "High",
        description=peri_scribe.kml.descriptions.FireDescription(
            total_personnel=100.0,
            observation_time=REFERENCE_TIME,
        ),
    )

    assert [
        fire.name
        for fire in peri_scribe.kml.folders.most_personnel_fires(
            [low, high],
            REFERENCE_TIME,
        )
    ] == ["High", "Low"]


def test_most_personnel_fires_excludes_missing_personnel() -> None:
    missing_description = active_fire("NoDescription")
    missing_count = active_fire(
        "NoCount",
        description=peri_scribe.kml.descriptions.FireDescription(
            observation_time=REFERENCE_TIME,
        ),
    )
    staffed = active_fire(
        "Staffed",
        description=peri_scribe.kml.descriptions.FireDescription(
            total_personnel=5.0,
            observation_time=REFERENCE_TIME,
        ),
    )

    assert [
        fire.name
        for fire in peri_scribe.kml.folders.most_personnel_fires(
            [missing_description, missing_count, staffed],
            REFERENCE_TIME,
        )
    ] == ["Staffed"]


def test_most_personnel_fires_excludes_stale_update() -> None:
    stale = active_fire(
        "Stale",
        description=peri_scribe.kml.descriptions.FireDescription(
            total_personnel=50.0,
            observation_time=REFERENCE_TIME - datetime.timedelta(days=8),
        ),
    )

    assert peri_scribe.kml.folders.most_personnel_fires([stale], REFERENCE_TIME) == []


def test_most_personnel_fires_excludes_missing_update() -> None:
    fire = active_fire(
        "NoUpdate",
        description=peri_scribe.kml.descriptions.FireDescription(
            total_personnel=50.0,
        ),
    )

    assert peri_scribe.kml.folders.most_personnel_fires([fire], REFERENCE_TIME) == []


def test_most_personnel_fires_excludes_future_update() -> None:
    fire = active_fire(
        "Future",
        description=peri_scribe.kml.descriptions.FireDescription(
            total_personnel=50.0,
            observation_time=REFERENCE_TIME + datetime.timedelta(hours=1),
        ),
    )

    assert peri_scribe.kml.folders.most_personnel_fires([fire], REFERENCE_TIME) == []


def test_most_personnel_fires_returns_empty_without_reference_time() -> None:
    fire = active_fire(
        "Staffed",
        description=peri_scribe.kml.descriptions.FireDescription(
            total_personnel=5.0,
            observation_time=REFERENCE_TIME,
        ),
    )

    assert peri_scribe.kml.folders.most_personnel_fires([fire], None) == []


def test_most_personnel_fires_limits_to_top_count() -> None:
    fires = [
        active_fire(
            f"Staffed {index}",
            description=peri_scribe.kml.descriptions.FireDescription(
                total_personnel=float(index),
                observation_time=REFERENCE_TIME,
            ),
        )
        for index in range(51)
    ]

    assert (
        len(peri_scribe.kml.folders.most_personnel_fires(fires, REFERENCE_TIME))
        == peri_scribe.kml.folders.TOP_FIRE_COUNT
    )


def test_top_fires_folder_holds_fires_visible_by_default(
    style_urls: dict[str, str],
) -> None:
    fire = peri_scribe.kml.fire_data.FireGeometry(
        name="Zulu",
        status=peri_scribe.models.FireStatus.ACTIVE,
        point=shapely.geometry.Point(0.0, 0.0),
        perimeters=(),
    )
    writer = peri_scribe.kml.geometry.KmlWriter()
    peri_scribe.kml.folders.top_fires_folder(
        writer,
        [fire],
        "Top Fires by Name",
        style_urls,
        peri_scribe.kml.builder.ring_style_urls_for([fire]),
    )
    document = tests.peri_scribe.kml.kml_helpers.document_from_writer(writer)
    folder = tests.peri_scribe.kml.kml_helpers.folder_named(
        document,
        "Top Fires by Name",
    )
    # The folder loads checked and holds the fire folders directly, all visible, so
    # the fires all show as soon as the folder is enabled.
    assert tests.peri_scribe.kml.kml_helpers.visibility(folder) is None
    assert tests.peri_scribe.kml.kml_helpers.folder_list_item_type(folder) is None
    assert tests.peri_scribe.kml.kml_helpers.folder_names(folder) == ["Zulu"]
    tests.peri_scribe.kml.kml_helpers.assert_tree_visible(folder)


def test_top_fires_folder_hides_whole_tree_when_unchecked(
    style_urls: dict[str, str],
) -> None:
    fire = peri_scribe.kml.fire_data.FireGeometry(
        name="Zulu",
        status=peri_scribe.models.FireStatus.ACTIVE,
        point=shapely.geometry.Point(0.0, 0.0),
        perimeters=(),
    )
    writer = peri_scribe.kml.geometry.KmlWriter()
    peri_scribe.kml.folders.top_fires_folder(
        writer,
        [fire],
        "Top Fires by Score",
        style_urls,
        {},
        visible=False,
    )
    document = tests.peri_scribe.kml.kml_helpers.document_from_writer(writer)
    folder = tests.peri_scribe.kml.kml_helpers.folder_named(
        document,
        "Top Fires by Score",
    )
    # An unchecked top-fires folder hides its whole tree, so it carries no visible
    # content and its checkbox in Google Earth loads off instead of being selected.
    assert tests.peri_scribe.kml.kml_helpers.visibility(folder) == 0
    tests.peri_scribe.kml.kml_helpers.assert_tree_invisible(folder)


def test_status_folder_name_for_inactive() -> None:
    assert (
        peri_scribe.kml.folders.status_folder_name(
            peri_scribe.models.FireStatus.INACTIVE,
        )
        == "Inactive Fires"
    )


def test_status_folder_filters_by_status(style_urls: dict[str, str]) -> None:
    active = peri_scribe.kml.fire_data.FireGeometry(
        name="Active Fire",
        status=peri_scribe.models.FireStatus.ACTIVE,
        point=None,
        perimeters=(),
    )
    inactive = peri_scribe.kml.fire_data.FireGeometry(
        name="Inactive Fire",
        status=peri_scribe.models.FireStatus.INACTIVE,
        point=None,
        perimeters=(),
    )
    writer = peri_scribe.kml.geometry.KmlWriter()
    peri_scribe.kml.folders.status_folder(
        writer,
        [active, inactive],
        peri_scribe.models.FireStatus.ACTIVE,
        style_urls,
        {},
    )
    document = tests.peri_scribe.kml.kml_helpers.document_from_writer(writer)
    folder = tests.peri_scribe.kml.kml_helpers.folder_named(document, "Active Fires")
    assert tests.peri_scribe.kml.kml_helpers.folder_list_item_type(folder) is None
    assert tests.peri_scribe.kml.kml_helpers.folder_names(folder) == [
        "Active Fire",
    ]


def test_status_folder_can_load_hidden(style_urls: dict[str, str]) -> None:
    active = peri_scribe.kml.fire_data.FireGeometry(
        name="Active Fire",
        status=peri_scribe.models.FireStatus.ACTIVE,
        point=None,
        perimeters=(),
    )
    writer = peri_scribe.kml.geometry.KmlWriter()
    peri_scribe.kml.folders.status_folder(
        writer,
        [active],
        peri_scribe.models.FireStatus.ACTIVE,
        style_urls,
        {},
        visible=False,
    )
    document = tests.peri_scribe.kml.kml_helpers.document_from_writer(writer)
    folder = tests.peri_scribe.kml.kml_helpers.folder_named(document, "Active Fires")
    # The folder and its whole tree load unchecked, so the folder carries no visible
    # content and its checkbox in Google Earth loads off instead of being selected.
    assert tests.peri_scribe.kml.kml_helpers.visibility(folder) == 0
    tests.peri_scribe.kml.kml_helpers.assert_tree_invisible(folder)


def test_status_folder_holds_every_fire(
    style_urls: dict[str, str],
) -> None:
    first_time = datetime.datetime(2026, 8, 13, 20, 0, tzinfo=datetime.UTC)
    second_time = datetime.datetime(2026, 8, 14, 20, 0, tzinfo=datetime.UTC)
    with_rings = peri_scribe.kml.fire_data.FireGeometry(
        name="Rings",
        status=peri_scribe.models.FireStatus.ACTIVE,
        point=shapely.geometry.Point(1.0, 1.0),
        perimeters=(),
        progression_rings=(
            peri_scribe.perimeters.progression.Ring(
                geometry=tests.peri_scribe.kml.kml_helpers.square(1.0),
                observation_time=first_time,
            ),
            peri_scribe.perimeters.progression.Ring(
                geometry=tests.peri_scribe.kml.kml_helpers.square(2.0),
                observation_time=second_time,
            ),
        ),
    )
    point_only = peri_scribe.kml.fire_data.FireGeometry(
        name="Point",
        status=peri_scribe.models.FireStatus.ACTIVE,
        point=shapely.geometry.Point(2.0, 2.0),
        perimeters=(),
    )
    empty = peri_scribe.kml.fire_data.FireGeometry(
        name="Empty",
        status=peri_scribe.models.FireStatus.ACTIVE,
        point=None,
        perimeters=(),
    )
    writer = peri_scribe.kml.geometry.KmlWriter()
    peri_scribe.kml.folders.status_folder(
        writer,
        [with_rings, point_only, empty],
        peri_scribe.models.FireStatus.ACTIVE,
        style_urls,
        peri_scribe.kml.builder.ring_style_urls_for(
            [with_rings, point_only, empty],
        ),
    )
    document = tests.peri_scribe.kml.kml_helpers.document_from_writer(writer)
    folder = tests.peri_scribe.kml.kml_helpers.folder_named(document, "Active Fires")
    assert tests.peri_scribe.kml.kml_helpers.folder_names(folder) == [
        "Rings",
        "Point",
        "Empty",
    ]


def balloon_text(
    description: peri_scribe.kml.descriptions.FireDescription,
    image_filenames: tuple[str, ...] = (),
    leading_rows: tuple[tuple[str, str | None], ...] = (),
) -> str:
    """Return *description*'s balloon as the KML parser reads it.

    Args:
        description: The fire description to render.
        image_filenames: The plot image filenames to show below the table.
        leading_rows: The rows to lead the table with.

    Returns:
        The balloon's CDATA content, without the section markers the parser strips.
    """
    html = peri_scribe.kml.descriptions.description_html(
        description,
        image_filenames,
        leading_rows=leading_rows,
    )
    return html[len("<![CDATA[") : -len("]]>")]


def test_fire_folder_applies_fire_balloon_to_point_and_outline_placemarks(
    style_urls: dict[str, str],
) -> None:
    description = peri_scribe.kml.descriptions.FireDescription(
        identifier="2026-cabug-000001",
    )
    fire = peri_scribe.kml.fire_data.FireGeometry(
        name="Bug",
        status=peri_scribe.models.FireStatus.ACTIVE,
        point=shapely.geometry.Point(1.0, 1.0),
        perimeters=(
            tests.peri_scribe.kml.kml_helpers.perimeter_with_time(
                tests.peri_scribe.kml.kml_helpers.square(1.0),
            ),
        ),
        description=description,
        images=(
            peri_scribe.kml.plot_rendering.PlotImage(
                filename="id-bug-perimeter.png",
                content=b"png",
            ),
        ),
    )
    writer = peri_scribe.kml.geometry.KmlWriter()
    peri_scribe.kml.folders.fire_folder(
        writer,
        fire,
        style_urls,
        peri_scribe.kml.builder.ring_style_urls_for([fire]),
    )
    folder = tests.peri_scribe.kml.kml_helpers.folder_named(
        tests.peri_scribe.kml.kml_helpers.document_from_writer(writer),
        "Bug",
    )
    assert tests.peri_scribe.kml.kml_helpers.placemark_names(folder) == [
        "Bug",
        "Unknown Mapping",
    ]
    expected = balloon_text(description, ("id-bug-perimeter.png",))
    for name in ("Bug", "Unknown Mapping"):
        balloon = tests.peri_scribe.kml.kml_helpers.description_text(
            tests.peri_scribe.kml.kml_helpers.placemark_named(folder, name),
        )
        assert balloon == expected
        assert "Added area" not in balloon


def test_fire_folder_interior_ring_balloons_lead_with_added_area(
    style_urls: dict[str, str],
) -> None:
    description = peri_scribe.kml.descriptions.FireDescription(
        identifier="2026-cabug-000001",
    )
    first_time = datetime.datetime(2026, 8, 5, 20, 0, tzinfo=datetime.UTC)
    second_time = datetime.datetime(2026, 8, 7, 20, 0, tzinfo=datetime.UTC)
    first_ring = tests.peri_scribe.kml.kml_helpers.square(1.0)
    second_ring = tests.peri_scribe.kml.kml_helpers.square(2.0)
    fire = peri_scribe.kml.fire_data.FireGeometry(
        name="Bug",
        status=peri_scribe.models.FireStatus.ACTIVE,
        point=shapely.geometry.Point(1.0, 1.0),
        perimeters=(),
        progression_rings=(
            peri_scribe.perimeters.progression.Ring(
                geometry=first_ring,
                observation_time=first_time,
            ),
            peri_scribe.perimeters.progression.Ring(
                geometry=second_ring,
                observation_time=second_time,
            ),
        ),
        description=description,
    )
    writer = peri_scribe.kml.geometry.KmlWriter()
    peri_scribe.kml.folders.fire_folder(
        writer,
        fire,
        style_urls,
        peri_scribe.kml.builder.ring_style_urls_for([fire]),
    )
    folder = tests.peri_scribe.kml.kml_helpers.folder_named(
        tests.peri_scribe.kml.kml_helpers.document_from_writer(writer),
        "Bug",
    )
    point_balloon = tests.peri_scribe.kml.kml_helpers.description_text(
        tests.peri_scribe.kml.kml_helpers.placemark_named(folder, "Bug"),
    )
    assert point_balloon == balloon_text(description)
    assert "Added area" not in point_balloon
    interior_folder = tests.peri_scribe.kml.kml_helpers.folder_named(folder, "Interior")
    assert tests.peri_scribe.kml.kml_helpers.placemark_names(interior_folder) == [
        "08/07 13:00 Interior",
        "08/05 13:00 Interior",
    ]
    # The second ring redraws the whole fire, so it adds only the ground beyond the
    # first ring rather than its entire geometry.
    first_added_area_in_acres = peri_scribe.units.area_in_acres(first_ring)
    second_added_area_in_acres = (
        peri_scribe.units.area_in_acres(second_ring) - first_added_area_in_acres
    )
    expected_balloons = {
        "08/05 13:00 Interior": balloon_text(
            description,
            leading_rows=(
                (
                    peri_scribe.kml.descriptions.ADDED_AREA_LABEL,
                    peri_scribe.kml.descriptions.format_in_acres(
                        first_added_area_in_acres,
                    ),
                ),
            ),
        ),
        "08/07 13:00 Interior": balloon_text(
            description,
            leading_rows=(
                (
                    peri_scribe.kml.descriptions.ADDED_AREA_LABEL,
                    peri_scribe.kml.descriptions.format_in_acres(
                        second_added_area_in_acres,
                    ),
                ),
            ),
        ),
    }
    for name, expected in expected_balloons.items():
        balloon = tests.peri_scribe.kml.kml_helpers.description_text(
            tests.peri_scribe.kml.kml_helpers.placemark_named(
                interior_folder,
                name,
            ),
        )
        assert balloon == expected
        assert "<b>Identifier</b>" in balloon


def test_fire_folder_fallback_ring_balloon_leads_with_its_area(
    style_urls: dict[str, str],
) -> None:
    description = peri_scribe.kml.descriptions.FireDescription(
        identifier="2026-cabug-000001",
    )
    fire = peri_scribe.kml.fire_data.FireGeometry(
        name="Bug",
        status=peri_scribe.models.FireStatus.ACTIVE,
        point=shapely.geometry.Point(1.0, 1.0),
        perimeters=(
            tests.peri_scribe.kml.kml_helpers.perimeter_with_time(
                tests.peri_scribe.kml.kml_helpers.square(1.0),
            ),
        ),
        description=description,
    )
    writer = peri_scribe.kml.geometry.KmlWriter()
    peri_scribe.kml.folders.fire_folder(
        writer,
        fire,
        style_urls,
        peri_scribe.kml.builder.ring_style_urls_for([fire]),
    )
    folder = tests.peri_scribe.kml.kml_helpers.folder_named(
        tests.peri_scribe.kml.kml_helpers.document_from_writer(writer),
        "Bug",
    )
    interior_folder = tests.peri_scribe.kml.kml_helpers.folder_named(folder, "Interior")
    balloon = tests.peri_scribe.kml.kml_helpers.description_text(
        tests.peri_scribe.kml.kml_helpers.placemark_named(
            interior_folder,
            "Interior",
        ),
    )
    # The fallback ring is the fire's whole latest perimeter, so it added that entire
    # area at its observation rather than a slice.
    added_area_in_acres = peri_scribe.units.area_in_acres(
        tests.peri_scribe.kml.kml_helpers.square(1.0),
    )
    assert balloon == balloon_text(
        description,
        leading_rows=(
            (
                peri_scribe.kml.descriptions.ADDED_AREA_LABEL,
                peri_scribe.kml.descriptions.format_in_acres(added_area_in_acres),
            ),
        ),
    )
    assert balloon.index("<b>Added area</b>") < balloon.index("<b>Area</b>")
