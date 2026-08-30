"""Tests for peri_scribe.kml.builder."""

from __future__ import annotations

import datetime
import pathlib
import typing
import zipfile

import shapely.geometry

import peri_scribe.fires.files
import peri_scribe.fires.index
import peri_scribe.geo.reading
import peri_scribe.kml.builder
import peri_scribe.kml.fire_data
import peri_scribe.kml.icons
import peri_scribe.kml.template
import peri_scribe.kml.template_reader
import peri_scribe.models
import peri_scribe.perimeters.progression
import tests.peri_scribe.kml.kml_helpers


if typing.TYPE_CHECKING:
    import geopandas
    import pytest


YEAR = 2026


class FakeArchive:
    """In-memory zip archive stand-in that records its writes."""

    def __init__(self, *arguments: object, **keywords: object) -> None:
        self.arguments = arguments
        self.keywords = keywords
        self.writes: list[tuple[str, str | bytes, int | None]] = []

    def __enter__(self) -> typing.Self:
        return self

    def __exit__(
        self,
        _exc_type: object,
        _exc_value: object,
        _traceback: object,
    ) -> None:
        return None

    def writestr(
        self,
        name: str,
        data: str | bytes,
        compress_type: int | None = None,
    ) -> None:
        self.writes.append((name, data, compress_type))


def test_year_from_reads_directory_name() -> None:
    assert peri_scribe.kml.builder.year_from(pathlib.Path(f"data/{YEAR}")) == YEAR


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
        ("id-bug", "Bug", tests.peri_scribe.kml.kml_helpers.square(1.0)),
    ])
    points = tests.peri_scribe.kml.kml_helpers.geometry_frame([
        ("id-bug", "Bug", shapely.geometry.Point(1.0, 1.0)),
    ])
    template = peri_scribe.kml.template_reader.template_from(
        peri_scribe.kml.template.template_kml(),
    )
    fires = peri_scribe.kml.fire_data.fire_geometries(
        index,
        perimeters,
        points,
        perimeters,
    )
    document = tests.peri_scribe.kml.kml_helpers.document_from(
        peri_scribe.kml.builder.fire_kml(fires, template, name="PeriScribe Fires 2026"),
    )

    assert (
        document.findtext(tests.peri_scribe.kml.kml_helpers.kml_tag("name"))
        == "PeriScribe Fires 2026"
    )
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
    components = peri_scribe.models.FireScoreComponents(
        size=0,
        growth=0,
        first_mapping=0,
        buildings=0,
        evacuation=0,
        importance=0,
    )
    scores = peri_scribe.models.FireScores(
        version="test",
        fires=[
            peri_scribe.models.FireScoreEntry(
                name="Zulu",
                score=3,
                components=components,
                explanation="No notable size, growth, threat, or "
                "official-importance signals.",
            ),
            peri_scribe.models.FireScoreEntry(
                name="Alpha",
                score=2,
                components=components,
                explanation="No notable size, growth, threat, or "
                "official-importance signals.",
            ),
        ],
    )
    template = peri_scribe.kml.template_reader.template_from(
        peri_scribe.kml.template.template_kml(),
    )
    document = tests.peri_scribe.kml.kml_helpers.document_from(
        peri_scribe.kml.builder.fire_kml(fires, template, "test", scores),
    )

    top_level = tests.peri_scribe.kml.kml_helpers.folder_named(document, "test")
    assert tests.peri_scribe.kml.kml_helpers.folder_names(top_level) == [
        "Top Fires by Name",
        "Top Fires by Score",
        "Active Fires",
        "Inactive Fires",
    ]
    top_by_name = tests.peri_scribe.kml.kml_helpers.folder_named(
        top_level,
        "Top Fires by Name",
    )
    top_by_score = tests.peri_scribe.kml.kml_helpers.folder_named(
        top_level,
        "Top Fires by Score",
    )
    assert tests.peri_scribe.kml.kml_helpers.folder_names(
        tests.peri_scribe.kml.kml_helpers.folder_named(
            top_by_name,
            peri_scribe.kml.template.LATEST_PERIMETERS_FOLDER_NAME,
        ),
    ) == ["Alpha", "Zulu"]
    assert tests.peri_scribe.kml.kml_helpers.folder_names(
        tests.peri_scribe.kml.kml_helpers.folder_named(
            top_by_score,
            peri_scribe.kml.template.LATEST_PERIMETERS_FOLDER_NAME,
        ),
    ) == ["Zulu", "Alpha"]


def test_fire_kml_shows_top_fires_by_name_progression_maps() -> None:
    fires = [
        peri_scribe.kml.fire_data.FireGeometry(
            name=name,
            status=peri_scribe.models.FireStatus.ACTIVE,
            point=shapely.geometry.Point(0.0, 0.0),
            perimeters=(),
        )
        for name in ("Zulu", "Alpha")
    ]
    components = peri_scribe.models.FireScoreComponents(
        size=0,
        growth=0,
        first_mapping=0,
        buildings=0,
        evacuation=0,
        importance=0,
    )
    scores = peri_scribe.models.FireScores(
        version="test",
        fires=[
            peri_scribe.models.FireScoreEntry(
                name="Zulu",
                score=3,
                components=components,
                explanation="No notable size, growth, threat, or "
                "official-importance signals.",
            ),
            peri_scribe.models.FireScoreEntry(
                name="Alpha",
                score=2,
                components=components,
                explanation="No notable size, growth, threat, or "
                "official-importance signals.",
            ),
        ],
    )
    template = peri_scribe.kml.template_reader.template_from(
        peri_scribe.kml.template.template_kml(),
    )
    document = tests.peri_scribe.kml.kml_helpers.document_from(
        peri_scribe.kml.builder.fire_kml(fires, template, "test", scores),
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
    active = tests.peri_scribe.kml.kml_helpers.folder_named(
        top_level,
        "Active Fires",
    )
    inactive = tests.peri_scribe.kml.kml_helpers.folder_named(
        top_level,
        "Inactive Fires",
    )
    # The top-level radios load with only "Top Fires by Name" checked, and inside it
    # the progression-maps view is the checked radio, so the progression maps are the
    # default view on load.
    assert tests.peri_scribe.kml.kml_helpers.visibility(by_name) is None
    assert tests.peri_scribe.kml.kml_helpers.visibility(by_score) == 0
    assert tests.peri_scribe.kml.kml_helpers.visibility(active) == 0
    assert tests.peri_scribe.kml.kml_helpers.visibility(inactive) == 0
    assert (
        tests.peri_scribe.kml.kml_helpers.visibility(
            tests.peri_scribe.kml.kml_helpers.folder_named(
                by_name,
                peri_scribe.kml.template.LATEST_PERIMETERS_FOLDER_NAME,
            ),
        )
        == 0
    )
    assert (
        tests.peri_scribe.kml.kml_helpers.visibility(
            tests.peri_scribe.kml.kml_helpers.folder_named(
                by_name,
                peri_scribe.perimeters.progression.PROGRESSION_MAPS_FOLDER_NAME,
            ),
        )
        is None
    )
    # The checked "Top Fires by Name" radio keeps its unchecked latest-perimeters view
    # usable, so checking its radio button in Google Earth shows the fire folders
    # immediately. The unchecked top-level radios hide their whole trees, so they carry
    # no visible content and their radio buttons load off instead of being selected.
    by_name_latest = tests.peri_scribe.kml.kml_helpers.folder_named(
        by_name,
        peri_scribe.kml.template.LATEST_PERIMETERS_FOLDER_NAME,
    )
    for fire_name in by_name_latest.findall(
        tests.peri_scribe.kml.kml_helpers.kml_tag("Folder"),
    ):
        assert tests.peri_scribe.kml.kml_helpers.visibility(fire_name) is None
    tests.peri_scribe.kml.kml_helpers.assert_tree_invisible(active)
    tests.peri_scribe.kml.kml_helpers.assert_tree_invisible(by_score)
    tests.peri_scribe.kml.kml_helpers.assert_tree_visible(
        tests.peri_scribe.kml.kml_helpers.folder_named(
            by_name,
            peri_scribe.perimeters.progression.PROGRESSION_MAPS_FOLDER_NAME,
        ),
    )
    tests.peri_scribe.kml.kml_helpers.assert_tree_invisible(
        tests.peri_scribe.kml.kml_helpers.folder_named(
            by_score,
            peri_scribe.perimeters.progression.PROGRESSION_MAPS_FOLDER_NAME,
        ),
    )


def test_fire_kml_includes_progression_maps_folder() -> None:
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
            ("id-bug", "Bug", tests.peri_scribe.kml.kml_helpers.square(1.0)),
            ("id-alta", "ALTA", tests.peri_scribe.kml.kml_helpers.square(2.0)),
        ],
        observation_times=[observation_time, observation_time],
    )
    points = tests.peri_scribe.kml.kml_helpers.geometry_frame([
        ("id-bug", "Bug", shapely.geometry.Point(1.0, 1.0)),
        ("id-alta", "ALTA", shapely.geometry.Point(2.0, 2.0)),
    ])
    template = peri_scribe.kml.template_reader.template_from(
        peri_scribe.kml.template.template_kml(),
    )
    fires = peri_scribe.kml.fire_data.fire_geometries(
        index,
        perimeters,
        points,
        perimeters,
    )
    document = tests.peri_scribe.kml.kml_helpers.document_from(
        peri_scribe.kml.builder.fire_kml(fires, template, name="PeriScribe Fires 2026"),
    )

    active = tests.peri_scribe.kml.kml_helpers.folder_named(
        tests.peri_scribe.kml.kml_helpers.top_level_folder(document),
        "Active Fires",
    )
    active_progression = tests.peri_scribe.kml.kml_helpers.folder_named(
        active,
        peri_scribe.perimeters.progression.PROGRESSION_MAPS_FOLDER_NAME,
    )
    assert (
        tests.peri_scribe.kml.kml_helpers.folder_list_item_type(active_progression)
        is None
    )
    assert tests.peri_scribe.kml.kml_helpers.folder_names(active_progression) == ["Bug"]
    bug_folder = tests.peri_scribe.kml.kml_helpers.folder_named(
        active_progression,
        "Bug",
    )
    assert tests.peri_scribe.kml.kml_helpers.folder_list_item_type(bug_folder) is None
    assert tests.peri_scribe.kml.kml_helpers.placemark_names(bug_folder) == ["Bug"]
    assert tests.peri_scribe.kml.kml_helpers.folder_names(bug_folder) == ["08/15"]

    inactive = tests.peri_scribe.kml.kml_helpers.folder_named(
        tests.peri_scribe.kml.kml_helpers.top_level_folder(document),
        "Inactive Fires",
    )
    inactive_progression = tests.peri_scribe.kml.kml_helpers.folder_named(
        inactive,
        peri_scribe.perimeters.progression.PROGRESSION_MAPS_FOLDER_NAME,
    )
    assert tests.peri_scribe.kml.kml_helpers.folder_names(inactive_progression) == [
        "ALTA",
    ]
    alta_folder = tests.peri_scribe.kml.kml_helpers.folder_named(
        inactive_progression,
        "ALTA",
    )
    assert tests.peri_scribe.kml.kml_helpers.placemark_names(alta_folder) == ["ALTA"]
    assert tests.peri_scribe.kml.kml_helpers.folder_names(alta_folder) == ["08/15"]


def test_fire_kml_builds_active_and_inactive_folders(
    in_process_plot_image_bundles: None,
) -> None:
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
            ("id-bug", "Bug", tests.peri_scribe.kml.kml_helpers.square(1.0)),
            ("id-bug", "Bug", tests.peri_scribe.kml.kml_helpers.square(2.0)),
            ("id-bug", "Bug", tests.peri_scribe.kml.kml_helpers.square(3.0)),
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
    template = peri_scribe.kml.template_reader.template_from(
        peri_scribe.kml.template.template_kml(),
    )
    document = tests.peri_scribe.kml.kml_helpers.document_from(
        peri_scribe.kml.builder.fire_kml(fires, template, name="PeriScribe Fires 2026"),
    )

    top_level = tests.peri_scribe.kml.kml_helpers.top_level_folder(document)
    assert tests.peri_scribe.kml.kml_helpers.folder_names(top_level) == [
        "Active Fires",
        "Inactive Fires",
    ]
    active = tests.peri_scribe.kml.kml_helpers.folder_named(top_level, "Active Fires")
    assert (
        tests.peri_scribe.kml.kml_helpers.folder_list_item_type(active) == "radioFolder"
    )
    active_perimeters = tests.peri_scribe.kml.kml_helpers.folder_named(
        active,
        peri_scribe.kml.template.LATEST_PERIMETERS_FOLDER_NAME,
    )
    assert (
        tests.peri_scribe.kml.kml_helpers.folder_list_item_type(active_perimeters)
        is None
    )
    bug_folder = tests.peri_scribe.kml.kml_helpers.folder_named(
        active_perimeters,
        "Bug",
    )
    assert tests.peri_scribe.kml.kml_helpers.placemark_names(bug_folder) == ["Bug"]
    assert tests.peri_scribe.kml.kml_helpers.placemark_names(
        tests.peri_scribe.kml.kml_helpers.folder_named(bug_folder, "Perimeters"),
    ) == [
        "08/05 13:30 Perimeter",
        "08/04 09:15 Perimeter",
        "08/03 16:00 Perimeter",
    ]
    assert tests.peri_scribe.kml.kml_helpers.placemark_names(
        tests.peri_scribe.kml.kml_helpers.folder_named(bug_folder, "Interior"),
    ) == [
        "08/05 13:30 Interior",
    ]
    inactive = tests.peri_scribe.kml.kml_helpers.folder_named(
        top_level,
        "Inactive Fires",
    )
    assert (
        tests.peri_scribe.kml.kml_helpers.folder_list_item_type(inactive)
        == "radioFolder"
    )
    inactive_perimeters = tests.peri_scribe.kml.kml_helpers.folder_named(
        inactive,
        peri_scribe.kml.template.LATEST_PERIMETERS_FOLDER_NAME,
    )
    assert (
        tests.peri_scribe.kml.kml_helpers.folder_list_item_type(inactive_perimeters)
        is None
    )
    alta_folder = tests.peri_scribe.kml.kml_helpers.folder_named(
        inactive_perimeters,
        "ALTA",
    )
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


def test_fire_kml_hides_inactive_fires_tree(
    in_process_plot_image_bundles: None,
) -> None:
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
            ("id-bug", "Bug", tests.peri_scribe.kml.kml_helpers.square(1.0)),
            ("id-alta", "ALTA", tests.peri_scribe.kml.kml_helpers.square(2.0)),
        ],
        observation_times=[observation_time, observation_time],
    )
    points = tests.peri_scribe.kml.kml_helpers.geometry_frame([
        ("id-bug", "Bug", shapely.geometry.Point(1.0, 1.0)),
        ("id-alta", "ALTA", shapely.geometry.Point(2.0, 2.0)),
    ])
    template = peri_scribe.kml.template_reader.template_from(
        peri_scribe.kml.template.template_kml(),
    )
    fires = peri_scribe.kml.fire_data.fire_geometries(
        index,
        perimeters,
        points,
        perimeters,
    )
    document = tests.peri_scribe.kml.kml_helpers.document_from(
        peri_scribe.kml.builder.fire_kml(fires, template, name="PeriScribe Fires 2026"),
    )

    top_level = tests.peri_scribe.kml.kml_helpers.top_level_folder(document)
    inactive = tests.peri_scribe.kml.kml_helpers.folder_named(
        top_level,
        "Inactive Fires",
    )
    tests.peri_scribe.kml.kml_helpers.assert_tree_invisible(inactive)

    active = tests.peri_scribe.kml.kml_helpers.folder_named(top_level, "Active Fires")
    active_perimeters = tests.peri_scribe.kml.kml_helpers.folder_named(
        active,
        peri_scribe.kml.template.LATEST_PERIMETERS_FOLDER_NAME,
    )
    bug_folder = tests.peri_scribe.kml.kml_helpers.folder_named(
        active_perimeters,
        "Bug",
    )
    assert tests.peri_scribe.kml.kml_helpers.visibility(active) is None
    assert tests.peri_scribe.kml.kml_helpers.visibility(active_perimeters) is None
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


def test_fire_kml_hides_active_progression_maps(
    in_process_plot_image_bundles: None,
) -> None:
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
            ("id-bug", "Bug", tests.peri_scribe.kml.kml_helpers.square(1.0)),
            ("id-alta", "ALTA", tests.peri_scribe.kml.kml_helpers.square(2.0)),
        ],
        observation_times=[observation_time, observation_time],
    )
    points = tests.peri_scribe.kml.kml_helpers.geometry_frame([
        ("id-bug", "Bug", shapely.geometry.Point(1.0, 1.0)),
        ("id-alta", "ALTA", shapely.geometry.Point(2.0, 2.0)),
    ])
    template = peri_scribe.kml.template_reader.template_from(
        peri_scribe.kml.template.template_kml(),
    )
    fires = peri_scribe.kml.fire_data.fire_geometries(
        index,
        perimeters,
        points,
        perimeters,
    )
    document = tests.peri_scribe.kml.kml_helpers.document_from(
        peri_scribe.kml.builder.fire_kml(fires, template, name="PeriScribe Fires 2026"),
    )

    active = tests.peri_scribe.kml.kml_helpers.folder_named(
        tests.peri_scribe.kml.kml_helpers.top_level_folder(document),
        "Active Fires",
    )
    progression = tests.peri_scribe.kml.kml_helpers.folder_named(
        active,
        peri_scribe.perimeters.progression.PROGRESSION_MAPS_FOLDER_NAME,
    )
    tests.peri_scribe.kml.kml_helpers.assert_tree_invisible(progression)


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
            ("id-alta", "ALTA", tests.peri_scribe.kml.kml_helpers.square(2.0)),
        ]),
        tests.peri_scribe.kml.kml_helpers.geometry_frame([]),
        tests.peri_scribe.kml.kml_helpers.geometry_frame([]),
    )
    template = peri_scribe.kml.template_reader.template_from(
        peri_scribe.kml.template.template_kml(),
    )
    document = tests.peri_scribe.kml.kml_helpers.document_from(
        peri_scribe.kml.builder.fire_kml(fires, template, name="PeriScribe Fires 2026"),
    )
    inactive = tests.peri_scribe.kml.kml_helpers.folder_named(
        tests.peri_scribe.kml.kml_helpers.top_level_folder(document),
        "Inactive Fires",
    )
    perimeters_folder = tests.peri_scribe.kml.kml_helpers.folder_named(
        inactive,
        peri_scribe.kml.template.LATEST_PERIMETERS_FOLDER_NAME,
    )
    alta_folder = tests.peri_scribe.kml.kml_helpers.folder_named(
        perimeters_folder,
        "ALTA",
    )
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


def test_write_kmz_writes_compressed_document(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = pathlib.Path("/maps/PeriScribe Fires 2026.kmz")
    made_directories: list[pathlib.Path] = []
    archives: list[FakeArchive] = []

    def fake_zipfile(
        *arguments: object,
        **keywords: object,
    ) -> FakeArchive:
        archive = FakeArchive(*arguments, **keywords)
        archives.append(archive)
        return archive

    monkeypatch.setattr(
        pathlib.Path,
        "mkdir",
        lambda _self, **_keywords: made_directories.append(_self),
    )
    monkeypatch.setattr(zipfile, "ZipFile", fake_zipfile)

    peri_scribe.kml.builder.write_kmz(path, "<kml/>")

    assert made_directories == [pathlib.Path("/maps")]
    assert len(archives) == 1
    archive = archives[0]
    assert archive.arguments == (path, "w")
    assert archive.keywords["compression"] == zipfile.ZIP_DEFLATED
    assert (
        archive.keywords["compresslevel"]
        == peri_scribe.kml.builder.KMZ_COMPRESSION_LEVEL
    )
    assert archive.writes == [("doc.kml", "<kml/>", None)]


def test_write_kmz_writes_images(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = pathlib.Path("/maps/PeriScribe Fires 2026.kmz")
    archives: list[FakeArchive] = []

    def fake_zipfile(
        *arguments: object,
        **keywords: object,
    ) -> FakeArchive:
        archive = FakeArchive(*arguments, **keywords)
        archives.append(archive)
        return archive

    monkeypatch.setattr(
        pathlib.Path,
        "mkdir",
        lambda _self, **_keywords: None,
    )
    monkeypatch.setattr(zipfile, "ZipFile", fake_zipfile)

    image_content = b"\x89PNG\r\n\x1a\n"
    peri_scribe.kml.builder.write_kmz(
        path,
        "<kml/>",
        {"id-bug-area.png": image_content},
    )

    (archive,) = archives
    assert archive.writes == [
        ("doc.kml", "<kml/>", None),
        ("id-bug-area.png", image_content, zipfile.ZIP_STORED),
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
        peri_scribe.fires.files,
        "history_geopackage_path",
        lambda _directory: pathlib.Path("/derived/full.gpkg"),
    )
    perimeters = tests.peri_scribe.kml.kml_helpers.geometry_frame(
        [("id-bug", "Bug", tests.peri_scribe.kml.kml_helpers.square(1.0))],
        area_acres=[100.0],
    )
    points = tests.peri_scribe.kml.kml_helpers.geometry_frame([
        ("id-bug", "Bug", shapely.geometry.Point(1.0, 1.0)),
    ])

    def read_layer(
        _path: pathlib.Path,
        layer_name: str,
    ) -> geopandas.GeoDataFrame:
        return perimeters if layer_name == "perimeter_history" else points

    monkeypatch.setattr(peri_scribe.geo.reading, "read_layer", read_layer)
    template = peri_scribe.kml.template_reader.template_from(
        peri_scribe.kml.template.template_kml(),
    )
    monkeypatch.setattr(
        peri_scribe.kml.template_reader,
        "read_template",
        lambda _path: template,
    )
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
        peri_scribe.kml.icons.interior_icon_filename(),
        peri_scribe.kml.icons.perimeters_icon_filename(),
        *(
            peri_scribe.kml.icons.progression_icon_filename(index)
            for index in range(
                len(peri_scribe.perimeters.progression.PROGRESSION_BANDS),
            )
        ),
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
        peri_scribe.fires.files,
        "history_geopackage_path",
        lambda _directory: pathlib.Path("/derived/full.gpkg"),
    )
    perimeters = tests.peri_scribe.kml.kml_helpers.geometry_frame(
        [
            ("id-bug", "Bug", tests.peri_scribe.kml.kml_helpers.square(1.0)),
            ("id-tiny", "Tiny", tests.peri_scribe.kml.kml_helpers.square(1.0)),
        ],
        area_acres=[100.0, 10.0],
    )
    points = tests.peri_scribe.kml.kml_helpers.geometry_frame([])

    def read_layer(
        _path: pathlib.Path,
        layer_name: str,
    ) -> geopandas.GeoDataFrame:
        return perimeters if layer_name == "perimeter_history" else points

    monkeypatch.setattr(peri_scribe.geo.reading, "read_layer", read_layer)
    template = peri_scribe.kml.template_reader.template_from(
        peri_scribe.kml.template.template_kml(),
    )
    monkeypatch.setattr(
        peri_scribe.kml.template_reader,
        "read_template",
        lambda _path: template,
    )
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
