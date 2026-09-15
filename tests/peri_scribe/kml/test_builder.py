"""Tests for peri_scribe.kml.builder."""

from __future__ import annotations

import datetime
import pathlib
import zipfile

import pytest
import shapely.geometry
import time_machine

import peri_scribe.fires.files
import peri_scribe.fires.index
import peri_scribe.fires.score_files
import peri_scribe.geo.reading
import peri_scribe.kml.builder
import peri_scribe.kml.fire_data
import peri_scribe.kml.icons
import peri_scribe.models
import peri_scribe.publication
import tests.factories
import tests.peri_scribe.kml.builder_helpers
import tests.peri_scribe.kml.kml_helpers


def test_kmz_filename_names_year() -> None:
    assert peri_scribe.kml.builder.kmz_filename(2026) == "PeriScribe Fires 2026.kmz"


def test_kmz_path_places_file_in_maps_directory() -> None:
    assert peri_scribe.kml.builder.kmz_path(pathlib.Path("data/2026")) == (
        pathlib.Path("data/2026/maps/PeriScribe Fires 2026.kmz")
    )


def test_fire_kml_names_the_document() -> None:
    index = tests.peri_scribe.kml.kml_helpers.fire_index([
        tests.peri_scribe.kml.kml_helpers.fire_index_entry(
            "Bug",
            "active",
            identifier="id-bug",
        ),
    ])
    perimeters = tests.peri_scribe.kml.kml_helpers.geometry_frame([
        ("id-bug", "Bug", tests.factories.square(1.0)),
    ])
    points = tests.peri_scribe.kml.kml_helpers.geometry_frame([
        ("id-bug", "Bug", shapely.geometry.Point(1.0, 1.0)),
    ])
    fires = peri_scribe.kml.fire_data.fire_geometries(
        index,
        perimeters,
        points,
        perimeters,
    )
    document = tests.peri_scribe.kml.kml_helpers.document_from(
        peri_scribe.kml.builder.fire_kml(fires, name="PeriScribe Fires 2026"),
    )

    assert (
        document.findtext(tests.peri_scribe.kml.kml_helpers.kml_tag("name"))
        == "PeriScribe Fires 2026"
    )
    attribution = document.findtext(
        tests.peri_scribe.kml.kml_helpers.kml_tag("description"),
    )
    assert attribution is not None
    assert "CAL FIRE/NIFC FIRIS" in attribution
    assert "Open Data Commons Open Database License (ODbL)" in attribution
    top_level = tests.peri_scribe.kml.kml_helpers.top_level_folder(document)
    assert (
        tests.peri_scribe.kml.kml_helpers.folder_list_item_type(top_level)
        == "radioFolder"
    )


def test_fire_kml_puts_top_fires_before_status_folders() -> None:
    fires = [
        peri_scribe.kml.fire_data.FireGeometry(
            name=name,
            status=peri_scribe.models.FireStatus.ACTIVE,
            point=shapely.geometry.Point(0.0, 0.0),
            perimeters=(),
        )
        for name in ("Zulu", "Alpha")
    ]
    scores = peri_scribe.models.FireScores(
        version="test",
        fires=[
            peri_scribe.models.FireScoreEntry(
                name="Zulu",
                score=3,
                explanation="No notable size, growth, threat, or "
                "official-importance signals.",
            ),
            peri_scribe.models.FireScoreEntry(
                name="Alpha",
                score=2,
                explanation="No notable size, growth, threat, or "
                "official-importance signals.",
            ),
        ],
    )
    document = tests.peri_scribe.kml.kml_helpers.document_from(
        peri_scribe.kml.builder.fire_kml(fires, "test", scores),
    )

    top_level = tests.peri_scribe.kml.kml_helpers.folder_named(document, "test")
    assert tests.peri_scribe.kml.kml_helpers.folder_names(top_level) == [
        "Top Fires by Name",
        "Top Fires by Score",
        "Active Fires",
    ]
    top_by_name = tests.peri_scribe.kml.kml_helpers.folder_named(
        top_level,
        "Top Fires by Name",
    )
    top_by_score = tests.peri_scribe.kml.kml_helpers.folder_named(
        top_level,
        "Top Fires by Score",
    )
    assert tests.peri_scribe.kml.kml_helpers.folder_names(top_by_name) == [
        "Alpha",
        "Zulu",
    ]
    assert tests.peri_scribe.kml.kml_helpers.folder_names(top_by_score) == [
        "Zulu",
        "Alpha",
    ]


def test_fire_kml_puts_new_folders_before_top_fires() -> None:
    fires, scores = tests.peri_scribe.kml.builder_helpers.new_folder_scenario()
    with time_machine.travel(tests.peri_scribe.kml.builder_helpers.SCENARIO_TIME):
        document = tests.peri_scribe.kml.kml_helpers.document_from(
            peri_scribe.kml.builder.fire_kml(fires, "test", scores),
        )

    top_level = tests.peri_scribe.kml.kml_helpers.folder_named(document, "test")
    assert tests.peri_scribe.kml.kml_helpers.folder_names(top_level) == [
        "New, Notable Fires",
        "Type 1 Fires",
        "Fast Growing Fires (acres)",
        "Fast Growing Fires (%)",
        "Fires with Most Personnel",
        "Top Fires by Name",
        "Top Fires by Score",
        "Active Fires",
    ]


def test_fire_kml_loads_new_folders_unchecked() -> None:
    fires, scores = tests.peri_scribe.kml.builder_helpers.new_folder_scenario()
    with time_machine.travel(tests.peri_scribe.kml.builder_helpers.SCENARIO_TIME):
        document = tests.peri_scribe.kml.kml_helpers.document_from(
            peri_scribe.kml.builder.fire_kml(fires, "test", scores),
        )

    top_level = tests.peri_scribe.kml.kml_helpers.folder_named(document, "test")
    by_name = tests.peri_scribe.kml.kml_helpers.folder_named(
        top_level,
        "Top Fires by Name",
    )
    active = tests.peri_scribe.kml.kml_helpers.folder_named(top_level, "Active Fires")
    # The new folders hold their fires directly and load unchecked, so "Top Fires by
    # Name" stays the last radio option with visible content and loads checked; the
    # status folders stay unchecked beneath it.
    for name in tests.peri_scribe.kml.builder_helpers.NEW_FOLDER_NAMES:
        folder = tests.peri_scribe.kml.kml_helpers.folder_named(top_level, name)
        assert tests.peri_scribe.kml.kml_helpers.visibility(folder) == 0
        tests.peri_scribe.kml.kml_helpers.assert_tree_invisible(folder)
        assert tests.peri_scribe.kml.kml_helpers.folder_names(folder) == ["Alpha"]
    assert tests.peri_scribe.kml.kml_helpers.visibility(by_name) is None
    tests.peri_scribe.kml.kml_helpers.assert_tree_visible(by_name)
    assert tests.peri_scribe.kml.kml_helpers.visibility(active) == 0
    tests.peri_scribe.kml.kml_helpers.assert_tree_invisible(active)


def test_fire_kml_lists_type_one_fires_by_name() -> None:
    fires = [
        peri_scribe.kml.fire_data.FireGeometry(
            name=name,
            status=peri_scribe.models.FireStatus.ACTIVE,
            point=None,
            perimeters=(),
            type_one=True,
        )
        for name in ("Zulu", "Alpha")
    ]
    empty_scores = peri_scribe.models.FireScores(version="test", fires=[])
    document = tests.peri_scribe.kml.kml_helpers.document_from(
        peri_scribe.kml.builder.fire_kml(fires, "test", empty_scores),
    )

    top_level = tests.peri_scribe.kml.kml_helpers.folder_named(document, "test")
    type_one = tests.peri_scribe.kml.kml_helpers.folder_named(top_level, "Type 1 Fires")
    assert tests.peri_scribe.kml.kml_helpers.folder_names(type_one) == ["Alpha", "Zulu"]
    tests.peri_scribe.kml.kml_helpers.assert_tree_invisible(type_one)


def test_fire_kml_loads_top_fires_by_name_checked() -> None:
    fires = [
        peri_scribe.kml.fire_data.FireGeometry(
            name=name,
            status=peri_scribe.models.FireStatus.ACTIVE,
            point=shapely.geometry.Point(0.0, 0.0),
            perimeters=(),
        )
        for name in ("Zulu", "Alpha")
    ]
    scores = peri_scribe.models.FireScores(
        version="test",
        fires=[
            peri_scribe.models.FireScoreEntry(
                name="Zulu",
                score=3,
                explanation="No notable size, growth, threat, or "
                "official-importance signals.",
            ),
            peri_scribe.models.FireScoreEntry(
                name="Alpha",
                score=2,
                explanation="No notable size, growth, threat, or "
                "official-importance signals.",
            ),
        ],
    )
    document = tests.peri_scribe.kml.kml_helpers.document_from(
        peri_scribe.kml.builder.fire_kml(fires, "test", scores),
    )

    top_level = tests.peri_scribe.kml.kml_helpers.folder_named(document, "test")
    by_name = tests.peri_scribe.kml.kml_helpers.folder_named(
        top_level,
        "Top Fires by Name",
    )
    by_score = tests.peri_scribe.kml.kml_helpers.folder_named(
        top_level,
        "Top Fires by Score",
    )
    active = tests.peri_scribe.kml.kml_helpers.folder_named(top_level, "Active Fires")
    # The top-level radios load with only "Top Fires by Name" checked, so its fires are
    # the default view on load. The unchecked top-level radios hide their whole trees,
    # so they carry no visible content and their radio buttons load off instead of being
    # selected. A status folder with no fires is omitted.
    assert tests.peri_scribe.kml.kml_helpers.folder_names(top_level) == [
        "Top Fires by Name",
        "Top Fires by Score",
        "Active Fires",
    ]
    assert tests.peri_scribe.kml.kml_helpers.visibility(by_name) is None
    assert tests.peri_scribe.kml.kml_helpers.visibility(by_score) == 0
    assert tests.peri_scribe.kml.kml_helpers.visibility(active) == 0
    tests.peri_scribe.kml.kml_helpers.assert_tree_visible(by_name)
    tests.peri_scribe.kml.kml_helpers.assert_tree_invisible(active)
    tests.peri_scribe.kml.kml_helpers.assert_tree_invisible(by_score)


def test_fire_kml_checks_active_fires_without_top_fires() -> None:
    fires, _scores = tests.peri_scribe.kml.builder_helpers.new_folder_scenario()
    empty_scores = peri_scribe.models.FireScores(version="test", fires=[])
    with time_machine.travel(tests.peri_scribe.kml.builder_helpers.SCENARIO_TIME):
        document = tests.peri_scribe.kml.kml_helpers.document_from(
            peri_scribe.kml.builder.fire_kml(fires, "test", empty_scores),
        )

    top_level = tests.peri_scribe.kml.kml_helpers.folder_named(document, "test")
    assert tests.peri_scribe.kml.kml_helpers.folder_names(top_level) == [
        "Type 1 Fires",
        "Fast Growing Fires (acres)",
        "Fast Growing Fires (%)",
        "Fires with Most Personnel",
        "Active Fires",
    ]
    active = tests.peri_scribe.kml.kml_helpers.folder_named(top_level, "Active Fires")
    # Without any top fires the active fires folder is the last radio option with
    # visible content, so it loads checked.
    assert tests.peri_scribe.kml.kml_helpers.visibility(active) is None
    tests.peri_scribe.kml.kml_helpers.assert_tree_visible(active)


def test_fire_kml_checks_inactive_fires_without_top_or_active_fires() -> None:
    fire = peri_scribe.kml.fire_data.FireGeometry(
        name="Done",
        status=peri_scribe.models.FireStatus.INACTIVE,
        point=None,
        perimeters=(),
    )
    empty_scores = peri_scribe.models.FireScores(version="test", fires=[])
    document = tests.peri_scribe.kml.kml_helpers.document_from(
        peri_scribe.kml.builder.fire_kml([fire], "test", empty_scores),
    )

    top_level = tests.peri_scribe.kml.kml_helpers.folder_named(document, "test")
    assert tests.peri_scribe.kml.kml_helpers.folder_names(top_level) == [
        "Inactive Fires",
    ]
    inactive = tests.peri_scribe.kml.kml_helpers.folder_named(
        top_level,
        "Inactive Fires",
    )
    assert tests.peri_scribe.kml.kml_helpers.visibility(inactive) is None
    tests.peri_scribe.kml.kml_helpers.assert_tree_visible(inactive)


def test_fire_kml_without_fires_has_no_top_level_folders() -> None:
    empty_scores = peri_scribe.models.FireScores(version="test", fires=[])
    documents = [
        tests.peri_scribe.kml.kml_helpers.document_from(
            peri_scribe.kml.builder.fire_kml([], "test"),
        ),
        tests.peri_scribe.kml.kml_helpers.document_from(
            peri_scribe.kml.builder.fire_kml([], "test", empty_scores),
        ),
    ]

    for document in documents:
        top_level = tests.peri_scribe.kml.kml_helpers.folder_named(document, "test")
        assert tests.peri_scribe.kml.kml_helpers.folder_names(top_level) == []


def test_fire_kml_holds_fires_directly_under_status_folders() -> None:
    index = tests.peri_scribe.kml.kml_helpers.fire_index([
        tests.peri_scribe.kml.kml_helpers.fire_index_entry(
            "Bug",
            "active",
            identifier="id-bug",
        ),
        tests.peri_scribe.kml.kml_helpers.fire_index_entry(
            "ALTA",
            "inactive",
            identifier="id-alta",
        ),
    ])
    observation_time = datetime.datetime(2026, 8, 15, 20, 0, tzinfo=datetime.UTC)
    perimeters = tests.peri_scribe.kml.kml_helpers.geometry_frame(
        [
            ("id-bug", "Bug", tests.factories.square(1.0)),
            ("id-alta", "ALTA", tests.factories.square(2.0)),
        ],
        observation_times=[observation_time, observation_time],
    )
    points = tests.peri_scribe.kml.kml_helpers.geometry_frame([
        ("id-bug", "Bug", shapely.geometry.Point(1.0, 1.0)),
        ("id-alta", "ALTA", shapely.geometry.Point(2.0, 2.0)),
    ])
    fires = peri_scribe.kml.fire_data.fire_geometries(
        index,
        perimeters,
        points,
        perimeters,
    )
    document = tests.peri_scribe.kml.kml_helpers.document_from(
        peri_scribe.kml.builder.fire_kml(fires, name="PeriScribe Fires 2026"),
    )

    active = tests.peri_scribe.kml.kml_helpers.folder_named(
        tests.peri_scribe.kml.kml_helpers.top_level_folder(document),
        "Active Fires",
    )
    assert tests.peri_scribe.kml.kml_helpers.folder_list_item_type(active) is None
    assert tests.peri_scribe.kml.kml_helpers.folder_names(active) == ["Bug"]
    bug_folder = tests.peri_scribe.kml.kml_helpers.folder_named(active, "Bug")
    assert tests.peri_scribe.kml.kml_helpers.folder_list_item_type(bug_folder) is None
    assert tests.peri_scribe.kml.kml_helpers.placemark_names(bug_folder) == [
        "Bug",
        "08/15 13:00 Perimeter",
    ]
    assert tests.peri_scribe.kml.kml_helpers.folder_names(bug_folder) == ["Interior"]

    inactive = tests.peri_scribe.kml.kml_helpers.folder_named(
        tests.peri_scribe.kml.kml_helpers.top_level_folder(document),
        "Inactive Fires",
    )
    assert tests.peri_scribe.kml.kml_helpers.folder_names(inactive) == ["ALTA"]
    alta_folder = tests.peri_scribe.kml.kml_helpers.folder_named(inactive, "ALTA")
    assert tests.peri_scribe.kml.kml_helpers.placemark_names(alta_folder) == [
        "ALTA",
        "08/15 13:00 Perimeter",
    ]
    assert tests.peri_scribe.kml.kml_helpers.folder_names(alta_folder) == ["Interior"]


def test_fire_kml_builds_active_and_inactive_folders() -> None:
    index = tests.peri_scribe.kml.kml_helpers.fire_index([
        tests.peri_scribe.kml.kml_helpers.fire_index_entry(
            "Bug",
            "active",
            identifier="id-bug",
        ),
        tests.peri_scribe.kml.kml_helpers.fire_index_entry(
            "ALTA",
            "inactive",
            identifier="id-alta",
        ),
    ])
    perimeters = tests.peri_scribe.kml.kml_helpers.geometry_frame(
        [
            ("id-bug", "Bug", tests.factories.square(1.0)),
            ("id-bug", "Bug", tests.factories.square(2.0)),
            ("id-bug", "Bug", tests.factories.square(3.0)),
        ],
        observation_times=[
            datetime.datetime(2026, 8, 3, 23, 0, tzinfo=datetime.UTC),
            datetime.datetime(2026, 8, 4, 16, 15, tzinfo=datetime.UTC),
            datetime.datetime(2026, 8, 5, 20, 30, tzinfo=datetime.UTC),
        ],
    )
    points = tests.peri_scribe.kml.kml_helpers.geometry_frame([
        ("id-bug", "Bug", shapely.geometry.Point(1.0, 1.0)),
        ("id-alta", "ALTA", shapely.geometry.Point(2.0, 2.0)),
    ])
    fires = peri_scribe.kml.fire_data.fire_geometries(
        index,
        perimeters,
        points,
        tests.peri_scribe.kml.kml_helpers.geometry_frame([]),
    )
    document = tests.peri_scribe.kml.kml_helpers.document_from(
        peri_scribe.kml.builder.fire_kml(fires, name="PeriScribe Fires 2026"),
    )

    top_level = tests.peri_scribe.kml.kml_helpers.top_level_folder(document)
    assert tests.peri_scribe.kml.kml_helpers.folder_names(top_level) == [
        "Active Fires",
        "Inactive Fires",
    ]
    active = tests.peri_scribe.kml.kml_helpers.folder_named(top_level, "Active Fires")
    assert tests.peri_scribe.kml.kml_helpers.folder_list_item_type(active) is None
    bug_folder = tests.peri_scribe.kml.kml_helpers.folder_named(active, "Bug")
    assert tests.peri_scribe.kml.kml_helpers.placemark_names(bug_folder) == ["Bug"]
    assert tests.peri_scribe.kml.kml_helpers.placemark_names(
        tests.peri_scribe.kml.kml_helpers.folder_named(bug_folder, "Perimeters"),
    ) == ["08/05 13:30 Perimeter", "08/04 09:15 Perimeter", "08/03 16:00 Perimeter"]
    assert tests.peri_scribe.kml.kml_helpers.placemark_names(
        tests.peri_scribe.kml.kml_helpers.folder_named(bug_folder, "Interior"),
    ) == ["08/05 13:30 Interior"]
    inactive = tests.peri_scribe.kml.kml_helpers.folder_named(
        top_level,
        "Inactive Fires",
    )
    assert tests.peri_scribe.kml.kml_helpers.folder_list_item_type(inactive) is None
    alta_folder = tests.peri_scribe.kml.kml_helpers.folder_named(inactive, "ALTA")
    assert tests.peri_scribe.kml.kml_helpers.placemark_names(alta_folder) == ["ALTA"]
    assert (
        tests.peri_scribe.kml.kml_helpers.draw_order(
            tests.peri_scribe.kml.kml_helpers.placemark_named(alta_folder, "ALTA"),
        )
        == 1
    )

    style_ids = {
        child.get("id")
        for child in document
        if child.tag == tests.peri_scribe.kml.kml_helpers.kml_tag("Style")
    }
    assert "point-icon" in style_ids
    assert "perimeter-fill" in style_ids
    assert "perimeter-outline-1" in style_ids


def test_fire_kml_hides_inactive_fires_tree() -> None:
    index = tests.peri_scribe.kml.kml_helpers.fire_index([
        tests.peri_scribe.kml.kml_helpers.fire_index_entry(
            "Bug",
            "active",
            identifier="id-bug",
        ),
        tests.peri_scribe.kml.kml_helpers.fire_index_entry(
            "ALTA",
            "inactive",
            identifier="id-alta",
        ),
    ])
    observation_time = datetime.datetime(2026, 8, 15, 20, 0, tzinfo=datetime.UTC)
    perimeters = tests.peri_scribe.kml.kml_helpers.geometry_frame(
        [
            ("id-bug", "Bug", tests.factories.square(1.0)),
            ("id-alta", "ALTA", tests.factories.square(2.0)),
        ],
        observation_times=[observation_time, observation_time],
    )
    points = tests.peri_scribe.kml.kml_helpers.geometry_frame([
        ("id-bug", "Bug", shapely.geometry.Point(1.0, 1.0)),
        ("id-alta", "ALTA", shapely.geometry.Point(2.0, 2.0)),
    ])
    fires = peri_scribe.kml.fire_data.fire_geometries(
        index,
        perimeters,
        points,
        perimeters,
    )
    document = tests.peri_scribe.kml.kml_helpers.document_from(
        peri_scribe.kml.builder.fire_kml(fires, name="PeriScribe Fires 2026"),
    )

    top_level = tests.peri_scribe.kml.kml_helpers.top_level_folder(document)
    inactive = tests.peri_scribe.kml.kml_helpers.folder_named(
        top_level,
        "Inactive Fires",
    )
    tests.peri_scribe.kml.kml_helpers.assert_tree_invisible(inactive)

    active = tests.peri_scribe.kml.kml_helpers.folder_named(top_level, "Active Fires")
    bug_folder = tests.peri_scribe.kml.kml_helpers.folder_named(active, "Bug")
    assert tests.peri_scribe.kml.kml_helpers.visibility(active) is None
    assert tests.peri_scribe.kml.kml_helpers.visibility(bug_folder) is None
    for placemark in bug_folder.findall(
        tests.peri_scribe.kml.kml_helpers.kml_tag("Placemark"),
    ):
        assert tests.peri_scribe.kml.kml_helpers.visibility(placemark) is None
    assert (
        tests.peri_scribe.kml.kml_helpers.visibility(
            tests.peri_scribe.kml.kml_helpers.tour_named(bug_folder, "Progression"),
        )
        is None
    )


def test_fire_kml_shows_derived_point_for_inactive_fire_without_location() -> None:
    index = tests.peri_scribe.kml.kml_helpers.fire_index([
        tests.peri_scribe.kml.kml_helpers.fire_index_entry(
            "ALTA",
            "inactive",
            identifier="id-alta",
        ),
    ])
    fires = peri_scribe.kml.fire_data.fire_geometries(
        index,
        tests.peri_scribe.kml.kml_helpers.geometry_frame([
            ("id-alta", "ALTA", tests.factories.square(2.0)),
        ]),
        tests.peri_scribe.kml.kml_helpers.geometry_frame([]),
        tests.peri_scribe.kml.kml_helpers.geometry_frame([]),
    )
    document = tests.peri_scribe.kml.kml_helpers.document_from(
        peri_scribe.kml.builder.fire_kml(fires, name="PeriScribe Fires 2026"),
    )
    inactive = tests.peri_scribe.kml.kml_helpers.folder_named(
        tests.peri_scribe.kml.kml_helpers.top_level_folder(document),
        "Inactive Fires",
    )
    alta_folder = tests.peri_scribe.kml.kml_helpers.folder_named(inactive, "ALTA")
    assert tests.peri_scribe.kml.kml_helpers.placemark_names(alta_folder) == [
        "ALTA",
        "Unknown Mapping",
    ]
    assert tests.peri_scribe.kml.kml_helpers.placemark_names(
        tests.peri_scribe.kml.kml_helpers.folder_named(alta_folder, "Interior"),
    ) == ["Interior"]
    assert (
        tests.peri_scribe.kml.kml_helpers.placemark_style_url(
            tests.peri_scribe.kml.kml_helpers.placemark_named(alta_folder, "ALTA"),
        )
        == "#point-icon"
    )


def test_write_archive_writes_compressed_document(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = pathlib.Path("/maps/PeriScribe Fires 2026.kmz")
    archives: list[tests.peri_scribe.kml.builder_helpers.FakeArchive] = []

    monkeypatch.setattr(
        zipfile,
        "ZipFile",
        tests.peri_scribe.kml.builder_helpers.recording_archive_factory(archives),
    )

    peri_scribe.kml.builder.write_archive(path, "<kml/>", None)

    assert len(archives) == 1
    archive = archives[0]
    assert archive.arguments == (path, "w")
    assert archive.keywords["compression"] == zipfile.ZIP_DEFLATED
    assert (
        archive.keywords["compresslevel"]
        == peri_scribe.kml.builder.KMZ_COMPRESSION_LEVEL
    )
    assert archive.writes == [("doc.kml", "<kml/>", None)]


def test_write_archive_writes_images(monkeypatch: pytest.MonkeyPatch) -> None:
    path = pathlib.Path("/maps/PeriScribe Fires 2026.kmz")
    archives: list[tests.peri_scribe.kml.builder_helpers.FakeArchive] = []

    monkeypatch.setattr(
        zipfile,
        "ZipFile",
        tests.peri_scribe.kml.builder_helpers.recording_archive_factory(archives),
    )

    image_content = b"\x89PNG\r\n\x1a\n"
    svg_content = b"<svg/>"
    peri_scribe.kml.builder.write_archive(
        path,
        "<kml/>",
        {"id-bug-area.png": image_content, "id-bug-area.svg": svg_content},
    )

    (archive,) = archives
    assert archive.writes == [
        ("doc.kml", "<kml/>", None),
        # A raster that is already compressed is stored; a text plot is deflated.
        ("id-bug-area.png", image_content, zipfile.ZIP_STORED),
        ("id-bug-area.svg", svg_content, zipfile.ZIP_DEFLATED),
    ]


def test_create_kmz_reads_history_and_writes_kmz(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    year_directory = pathlib.Path("data/2026")
    index = tests.peri_scribe.kml.kml_helpers.fire_index([
        tests.peri_scribe.kml.kml_helpers.fire_index_entry(
            "Bug",
            "active",
            identifier="id-bug",
        ),
    ])
    monkeypatch.setattr(
        peri_scribe.fires.index,
        "load_fire_index",
        lambda _directory: index,
    )
    monkeypatch.setattr(
        peri_scribe.fires.score_files,
        "load_fire_scores",
        lambda _directory: None,
    )
    monkeypatch.setattr(
        peri_scribe.fires.files,
        "history_geopackage_path",
        lambda _directory: pathlib.Path("/derived/full.gpkg"),
    )
    perimeters = tests.peri_scribe.kml.kml_helpers.geometry_frame(
        [("id-bug", "Bug", tests.factories.square(1.0))],
        area_acres=[100.0],
    )
    points = tests.peri_scribe.kml.kml_helpers.geometry_frame([
        ("id-bug", "Bug", shapely.geometry.Point(1.0, 1.0)),
    ])

    read_layer = tests.peri_scribe.kml.builder_helpers.make_history_layer_reader(
        perimeters=perimeters,
        points=points,
    )

    monkeypatch.setattr(peri_scribe.geo.reading, "read_layer", read_layer)
    writes: list[tuple[pathlib.Path, str, dict[str, bytes]]] = []
    monkeypatch.setattr(
        peri_scribe.kml.builder,
        "write_kmz",
        lambda path, kml_text, images: writes.append((path, kml_text, images)),
    )

    result = peri_scribe.kml.builder.create_kmz(year_directory)

    assert result == peri_scribe.kml.builder.kmz_path(year_directory)
    assert len(writes) == 1
    path, kml_text, images = writes[0]
    assert path == result
    assert "Active Fires" in kml_text
    assert "PeriScribe Fires 2026" in kml_text
    assert set(images) == {
        peri_scribe.kml.icons.interior_progression_icon_filename(),
        peri_scribe.kml.icons.perimeters_icon_filename(),
    }
    assert all(content.startswith(b"\x89PNG\r\n\x1a\n") for content in images.values())


def test_create_kmz_excludes_fires_without_qualifying_area(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    year_directory = pathlib.Path("data/2026")
    index = tests.peri_scribe.kml.kml_helpers.fire_index([
        tests.peri_scribe.kml.kml_helpers.fire_index_entry(
            "Bug",
            "active",
            identifier="id-bug",
        ),
        tests.peri_scribe.kml.kml_helpers.fire_index_entry(
            "Tiny",
            "active",
            identifier="id-tiny",
        ),
    ])
    monkeypatch.setattr(
        peri_scribe.fires.index,
        "load_fire_index",
        lambda _directory: index,
    )
    monkeypatch.setattr(
        peri_scribe.fires.score_files,
        "load_fire_scores",
        lambda _directory: None,
    )
    monkeypatch.setattr(
        peri_scribe.fires.files,
        "history_geopackage_path",
        lambda _directory: pathlib.Path("/derived/full.gpkg"),
    )
    perimeters = tests.peri_scribe.kml.kml_helpers.geometry_frame(
        [
            ("id-bug", "Bug", tests.factories.square(0.01)),
            ("id-tiny", "Tiny", tests.factories.square(0.001)),
        ],
        area_acres=[100.0, 10.0],
    )
    points = tests.peri_scribe.kml.kml_helpers.geometry_frame([])

    read_layer = tests.peri_scribe.kml.builder_helpers.make_history_layer_reader(
        perimeters=perimeters,
        points=points,
    )

    monkeypatch.setattr(peri_scribe.geo.reading, "read_layer", read_layer)
    writes: list[tuple[pathlib.Path, str, dict[str, bytes]]] = []
    monkeypatch.setattr(
        peri_scribe.kml.builder,
        "write_kmz",
        lambda path, kml_text, images: writes.append((path, kml_text, images)),
    )

    peri_scribe.kml.builder.create_kmz(year_directory)

    _path, kml_text, images = writes[0]
    assert "Bug" in kml_text
    assert "Tiny" not in kml_text
    assert not any(filename.startswith("id-tiny") for filename in images)


def test_area_qualified_index_includes_independent_incident_history() -> None:
    index = tests.peri_scribe.kml.kml_helpers.fire_index([
        tests.peri_scribe.kml.kml_helpers.fire_index_entry(
            "Example",
            "active",
            identifier="example",
        ),
    ])
    empty = tests.peri_scribe.kml.kml_helpers.geometry_frame([])
    incidents = tests.factories.geo_frame(
        {
            "fire_identifier": ["example"],
            "fire_name": ["Example"],
            "observation_time": [tests.factories.utc(2026, 9, 1, 0)],
            "incident_size": [100],
            "report_confirmed": [False],
        },
        [None],
    )
    assert (
        peri_scribe.kml.builder.area_qualified_index(index, empty, empty, incidents)
        == index
    )


def test_kmz_atomic_replacement_and_failed_write_preserve_complete_file(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "maps/output.kmz"
    peri_scribe.kml.builder.write_kmz(output, "<kml>old</kml>")
    previous = output.read_bytes()

    fail_after_partial_write = (
        tests.peri_scribe.kml.builder_helpers.make_interrupted_archive_writer(
            output=output,
            previous=previous,
        )
    )

    with monkeypatch.context() as patch:
        patch.setattr(
            peri_scribe.kml.builder,
            "write_archive",
            fail_after_partial_write,
        )
        with pytest.raises(OSError, match="disk failure"):
            peri_scribe.kml.builder.write_kmz(output, "<kml>new</kml>")
    assert output.read_bytes() == previous
    assert list(output.parent.iterdir()) == [output]
    peri_scribe.kml.builder.write_kmz(output, "<kml>new</kml>")
    with zipfile.ZipFile(output) as archive:
        assert archive.read("doc.kml") == b"<kml>new</kml>"


@pytest.mark.parametrize("fail", [False, True])
def test_create_kmz_advances_checkpoint_only_after_file_completion(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    fail: bool,
) -> None:
    year = tmp_path / "2026"
    inputs = peri_scribe.publication.Collection()
    empty = tests.peri_scribe.kml.kml_helpers.geometry_frame([])
    index = tests.peri_scribe.kml.kml_helpers.fire_index([])
    monkeypatch.setattr(peri_scribe.fires.index, "load_fire_index", lambda _year: index)
    monkeypatch.setattr(
        peri_scribe.fires.score_files,
        "load_fire_scores",
        lambda _year: None,
    )
    monkeypatch.setattr(peri_scribe.geo.reading, "read_layer", lambda *_args: empty)
    checkpoint = peri_scribe.publication.publication_path(year)
    checkpoint.parent.mkdir()
    checkpoint.write_bytes(b"previous checkpoint")
    if fail:
        monkeypatch.setattr(
            peri_scribe.kml.builder,
            "write_kmz",
            tests.factories.raising_stub(OSError("disk failure")),
        )
        with pytest.raises(OSError, match="disk failure"):
            peri_scribe.kml.builder.create_kmz(year, publication_inputs=inputs)
        assert checkpoint.read_bytes() == b"previous checkpoint"
    else:
        output = peri_scribe.kml.builder.create_kmz(year, publication_inputs=inputs)
        published = peri_scribe.publication.read_publication(year, output)
        assert published is not None
        assert published.files == {}
        assert published.fires == {}
        with zipfile.ZipFile(output) as archive:
            assert b"PeriScribe Fires 2026" in archive.read("doc.kml")
