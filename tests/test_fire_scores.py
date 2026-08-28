"""Tests for peri_scribe.fire_scores."""

from __future__ import annotations

import datetime
import json
import pathlib

import geopandas
import pytest
import shapely.geometry

import peri_scribe.external_sources
import peri_scribe.fire_history
import peri_scribe.fire_scores
import peri_scribe.geo_package
import peri_scribe.models
import peri_scribe.output
import peri_scribe.snapshots


def point(x: float, y: float) -> shapely.geometry.Point:
    """Return a WGS84 point at the given coordinates.

    Args:
        x: The longitude.
        y: The latitude.

    Returns:
        The point.
    """
    return shapely.geometry.Point(x, y)


def square(side: float) -> shapely.geometry.Polygon:
    """Return a square of the given side, centered at the origin.

    Args:
        side: The length of each side.

    Returns:
        The square.
    """
    half = side / 2
    return shapely.geometry.box(-half, -half, half, half)


def empty_frame(crs: str = "EPSG:4326") -> geopandas.GeoDataFrame:
    """Return an empty GeoDataFrame in the given spatial reference.

    Args:
        crs: The spatial reference.

    Returns:
        The empty GeoDataFrame.
    """
    return geopandas.GeoDataFrame(geometry=[], crs=crs)


def perimeter_frame(
    records: list[dict[str, object]],
    geometries: list[shapely.geometry.base.BaseGeometry],
) -> geopandas.GeoDataFrame:
    """Build a perimeter-history GeoDataFrame from attribute overrides.

    Args:
        records: One attribute override per row.
        geometries: The rows' geometries.

    Returns:
        The rows as a GeoDataFrame with the perimeter columns scoring reads.
    """
    columns = [
        "fire_name",
        "fire_identifier",
        "area_acres",
        "area_acres_differential",
        "observation_time",
    ]
    rows = [{column: record.get(column) for column in columns} for record in records]
    return geopandas.GeoDataFrame(rows, geometry=geometries, crs="EPSG:4326")


def point_frame(
    records: list[dict[str, object]],
    geometries: list[shapely.geometry.base.BaseGeometry],
) -> geopandas.GeoDataFrame:
    """Build a point-history GeoDataFrame from attribute overrides.

    Args:
        records: One attribute override per row.
        geometries: The rows' geometries.

    Returns:
        The rows as a GeoDataFrame with the point columns scoring reads.
    """
    columns = ["fire_name", "fire_identifier", "source_attributes"]
    rows = [{column: record.get(column) for column in columns} for record in records]
    return geopandas.GeoDataFrame(rows, geometry=geometries, crs="EPSG:4326")


def test_tiered_points_returns_zero_for_missing() -> None:
    assert peri_scribe.fire_scores.tiered_points(None, ((10.0, 1),)) == 0


def test_tiered_points_returns_zero_when_no_tier_is_met() -> None:
    assert peri_scribe.fire_scores.tiered_points(3.0, ((100.0, 5), (10.0, 1))) == 0


def test_tiered_points_returns_first_met_tier() -> None:
    assert peri_scribe.fire_scores.tiered_points(50.0, ((100.0, 5), (10.0, 1))) == 1


def test_tiered_points_meets_exact_threshold() -> None:
    assert peri_scribe.fire_scores.tiered_points(
        100.0,
        ((100.0, 5), (10.0, 1)),
    ) == pytest.approx(5)


def test_importance_points_returns_points_for_known_level() -> None:
    assert peri_scribe.fire_scores.importance_points(
        "Type 2 Incident",
    ) == pytest.approx(2)


def test_importance_points_returns_zero_for_unknown_level() -> None:
    assert peri_scribe.fire_scores.importance_points("Type 4 Incident") == 0


def test_importance_points_returns_zero_for_missing() -> None:
    assert peri_scribe.fire_scores.importance_points(None) == 0


def test_complexity_level_reads_level_from_json() -> None:
    assert (
        peri_scribe.fire_scores.complexity_level(
            json.dumps({"IncidentComplexityLevel": "Type 1 Incident"}),
        )
        == "Type 1 Incident"
    )


def test_complexity_level_returns_none_without_level() -> None:
    assert peri_scribe.fire_scores.complexity_level(json.dumps({"Other": 1})) is None


def test_complexity_level_returns_none_for_invalid_json() -> None:
    assert peri_scribe.fire_scores.complexity_level("{not json") is None


def test_complexity_level_returns_none_for_non_object_json() -> None:
    assert peri_scribe.fire_scores.complexity_level(json.dumps([1, 2])) is None


def test_complexity_level_returns_none_for_missing() -> None:
    assert peri_scribe.fire_scores.complexity_level(None) is None


def test_maximum_value_returns_largest_numeric_value() -> None:
    assert peri_scribe.fire_scores.maximum_value(
        [None, 3, "x", 5.0],
    ) == pytest.approx(5.0)


def test_maximum_value_returns_none_when_all_missing() -> None:
    assert peri_scribe.fire_scores.maximum_value(["x", None]) is None


def test_maximum_value_returns_none_for_empty() -> None:
    assert peri_scribe.fire_scores.maximum_value([]) is None


def test_first_mapping_acres_uses_earliest_observation() -> None:
    frame = perimeter_frame(
        [
            {
                "area_acres": 50.0,
                "observation_time": datetime.datetime(2026, 8, 2),
            },
            {
                "area_acres": 500.0,
                "observation_time": datetime.datetime(2026, 8, 1),
            },
        ],
        [square(1.0), square(2.0)],
    )
    assert peri_scribe.fire_scores.first_mapping_acres(frame) == pytest.approx(500.0)


def test_first_mapping_acres_falls_back_to_first_row_without_times() -> None:
    frame = perimeter_frame(
        [{"area_acres": 50.0}, {"area_acres": 500.0}],
        [square(1.0), square(2.0)],
    )
    assert peri_scribe.fire_scores.first_mapping_acres(frame) == pytest.approx(50.0)


def test_union_geometry_returns_single_geometry_unchanged() -> None:
    geometry = square(1.0)
    result = peri_scribe.fire_scores.union_geometry(
        geopandas.GeoSeries([geometry], crs="EPSG:4326"),
    )
    assert result is not None
    assert result.equals(geometry)


def test_union_geometry_unions_multiple_geometries() -> None:
    result = peri_scribe.fire_scores.union_geometry(
        geopandas.GeoSeries(
            [square(1.0), shapely.geometry.box(2.0, 2.0, 3.0, 3.0)],
            crs="EPSG:4326",
        ),
    )
    assert result is not None
    assert result.geom_type == "MultiPolygon"


def test_union_geometry_returns_none_for_all_empty() -> None:
    result = peri_scribe.fire_scores.union_geometry(
        geopandas.GeoSeries(
            [shapely.geometry.Polygon(), None],
            crs="EPSG:4326",
        ),
    )
    assert result is None


def test_perimeter_metrics_returns_none_for_empty() -> None:
    metrics = peri_scribe.fire_scores.perimeter_metrics(
        perimeter_frame([], []),
    )
    assert metrics.area_acres is None
    assert metrics.growth_acres is None
    assert metrics.first_mapping_acres is None
    assert metrics.geometry is None


def test_perimeter_metrics_measures_size_growth_and_first_mapping() -> None:
    frame = perimeter_frame(
        [
            {
                "area_acres": 50.0,
                "area_acres_differential": 50.0,
                "observation_time": datetime.datetime(2026, 8, 1),
            },
            {
                "area_acres": 200.0,
                "area_acres_differential": 150.0,
                "observation_time": datetime.datetime(2026, 8, 2),
            },
        ],
        [square(1.0), square(2.0)],
    )
    metrics = peri_scribe.fire_scores.perimeter_metrics(frame)
    assert metrics.area_acres == pytest.approx(200.0)
    assert metrics.growth_acres == pytest.approx(150.0)
    assert metrics.first_mapping_acres == pytest.approx(50.0)
    assert metrics.geometry is not None


def test_fire_importance_points_returns_zero_for_empty() -> None:
    assert peri_scribe.fire_scores.fire_importance_points(empty_frame()) == 0


def test_fire_importance_points_takes_highest_level() -> None:
    frame = point_frame(
        [
            {
                "source_attributes": json.dumps(
                    {"IncidentComplexityLevel": "Type 3 Incident"},
                ),
            },
            {
                "source_attributes": json.dumps(
                    {"IncidentComplexityLevel": "Type 1 Incident"},
                ),
            },
        ],
        [point(0, 0), point(1, 1)],
    )
    assert peri_scribe.fire_scores.fire_importance_points(
        frame,
    ) == pytest.approx(3)


def test_fire_geometry_from_prefers_perimeter_geometry() -> None:
    geometry = square(1.0)
    assert (
        peri_scribe.fire_scores.fire_geometry_from(
            geometry,
            point_frame([], []),
        )
        is geometry
    )


def test_fire_geometry_from_unions_points_without_perimeters() -> None:
    points = point_frame([], [point(0, 0), point(1, 1)])
    geometry = peri_scribe.fire_scores.fire_geometry_from(None, points)
    assert geometry is not None
    assert geometry.geom_type == "MultiPoint"


def test_fire_geometry_from_returns_none_without_geometry() -> None:
    assert (
        peri_scribe.fire_scores.fire_geometry_from(
            None,
            point_frame([], []),
        )
        is None
    )


def test_buffered_fire_geometries_buffers_each_geometry() -> None:
    buffered = peri_scribe.fire_scores.buffered_fire_geometries(
        [point(0, 0), None],
    )
    assert buffered[0] is not None
    assert buffered[0].geom_type == "Polygon"
    assert buffered[0].contains(point(0, 0))
    assert buffered[1] is None


def test_building_counts_within_counts_points_across_chunks(
    tmp_path: pathlib.Path,
) -> None:
    buffered = peri_scribe.fire_scores.buffered_fire_geometries(
        [square(1.0), square(0.1)],
    )
    buildings = geopandas.GeoDataFrame(
        {"name": ["a"] * 6},
        geometry=[point(0, 0)] * 3 + [point(50, 50), point(60, 60), point(70, 70)],
        crs="EPSG:4326",
    )
    path = tmp_path / "buildings.gpkg"
    buildings.to_file(path, layer="buildings")

    counts = peri_scribe.fire_scores.building_counts_within(
        buffered,
        path,
        "buildings",
        chunk_size=2,
    )

    assert counts == [3, 3]


def test_building_counts_within_returns_zero_without_geometry() -> None:
    counts = peri_scribe.fire_scores.building_counts_within(
        [None, shapely.geometry.Polygon()],
        pathlib.Path("/unused.gpkg"),
        "buildings",
    )
    assert counts == [0, 0]


def test_reproject_geometry_returns_geometry_unchanged_for_same_crs() -> None:
    geometry = point(1.0, 2.0)
    result = peri_scribe.fire_scores.reproject_geometry(
        geometry,
        peri_scribe.fire_scores.WGS84_SPATIAL_REFERENCE,
        peri_scribe.fire_scores.WGS84_SPATIAL_REFERENCE,
    )
    assert result.equals(geometry)


def test_reproject_geometry_transforms_between_crs() -> None:
    result = peri_scribe.fire_scores.reproject_geometry(
        point(1.0, 0.0),
        peri_scribe.fire_scores.WGS84_SPATIAL_REFERENCE,
        peri_scribe.fire_scores.WEB_MERCATOR_SPATIAL_REFERENCE,
    )
    assert result.x == pytest.approx(111319.49079327357)


def test_buffered_wgs84_geometry_contains_original_point() -> None:
    buffered = peri_scribe.fire_scores.buffered_wgs84_geometry(point(0, 0), 1609.34)
    assert buffered.geom_type == "Polygon"
    assert buffered.contains(point(0, 0))


def test_overlapping_fire_indices_detects_overlap(
    tmp_path: pathlib.Path,
) -> None:
    zones = geopandas.GeoDataFrame(
        {"name": ["zone", "far"]},
        geometry=[
            square(2.0),
            shapely.geometry.box(100.0, 100.0, 101.0, 101.0),
        ],
        crs="EPSG:4326",
    )
    path = tmp_path / "zones.gpkg"
    zones.to_file(path, layer="zones")

    indices = peri_scribe.fire_scores.overlapping_fire_indices(
        [square(1.0), shapely.geometry.box(50.0, 50.0, 51.0, 51.0)],
        path,
        "zones",
        chunk_size=1,
    )

    assert indices == {0}


def test_overlapping_fire_indices_reprojects_to_layer_crs(
    tmp_path: pathlib.Path,
) -> None:
    zones = geopandas.GeoDataFrame(
        {"name": ["zone"]},
        geometry=[point(0, 0)],
        crs="EPSG:3857",
    )
    path = tmp_path / "zones.gpkg"
    zones.to_file(path, layer="zones")

    indices = peri_scribe.fire_scores.overlapping_fire_indices(
        [point(0, 0)],
        path,
        "zones",
    )

    assert indices == {0}


def test_overlapping_fire_indices_returns_empty_without_geometry() -> None:
    assert (
        peri_scribe.fire_scores.overlapping_fire_indices(
            [None],
            pathlib.Path("/unused.gpkg"),
            "zones",
        )
        == set()
    )


def test_identity_key_prefers_identifier() -> None:
    assert peri_scribe.fire_scores.identity_key("Bug", "2026-x") == "2026-x"


def test_identity_key_falls_back_to_name() -> None:
    assert peri_scribe.fire_scores.identity_key("Bug", None) == "name:Bug"


def test_row_identity_reads_name_and_identifier() -> None:
    frame = perimeter_frame(
        [{"fire_name": "Bug", "fire_identifier": "2026-x"}],
        [square(1.0)],
    )
    assert peri_scribe.fire_scores.row_identity(frame.iloc[0]) == ("Bug", "2026-x")


def test_row_identity_treats_missing_identifier_as_none() -> None:
    frame = perimeter_frame(
        [{"fire_name": "Bug", "fire_identifier": float("nan")}],
        [square(1.0)],
    )
    assert peri_scribe.fire_scores.row_identity(frame.iloc[0]) == ("Bug", None)


def test_group_keys_aligns_with_rows() -> None:
    frame = perimeter_frame(
        [
            {"fire_name": "Bug", "fire_identifier": "2026-a"},
            {"fire_name": "Bug", "fire_identifier": "2026-a"},
            {"fire_name": "Other", "fire_identifier": None},
        ],
        [square(1.0), square(2.0), square(3.0)],
    )
    assert peri_scribe.fire_scores.group_keys(frame).tolist() == [
        "2026-a",
        "2026-a",
        "name:Other",
    ]


def test_fire_name_and_identifier_uses_perimeters_when_present() -> None:
    perimeters = perimeter_frame(
        [{"fire_name": "Bug", "fire_identifier": "2026-a"}],
        [square(1.0)],
    )
    points = point_frame(
        [{"fire_name": "Other", "fire_identifier": "2026-b"}],
        [point(0, 0)],
    )
    assert peri_scribe.fire_scores.fire_name_and_identifier(perimeters, points) == (
        "Bug",
        "2026-a",
    )


def test_fire_name_and_identifier_uses_points_when_perimeters_empty() -> None:
    points = point_frame(
        [{"fire_name": "Other", "fire_identifier": "2026-b"}],
        [point(0, 0)],
    )
    assert peri_scribe.fire_scores.fire_name_and_identifier(
        perimeter_frame([], []),
        points,
    ) == ("Other", "2026-b")


def test_fire_records_groups_perimeters_and_points() -> None:
    perimeters = perimeter_frame(
        [
            {"fire_name": "Bug", "fire_identifier": "2026-a"},
            {"fire_name": "Bug", "fire_identifier": "2026-a"},
            {"fire_name": "Lone", "fire_identifier": "2026-c"},
        ],
        [square(1.0), square(2.0), square(3.0)],
    )
    points = point_frame(
        [
            {"fire_name": "Bug", "fire_identifier": "2026-a"},
            {"fire_name": "Point Only", "fire_identifier": None},
        ],
        [point(0, 0), point(1, 1)],
    )
    records = peri_scribe.fire_scores.fire_records(perimeters, points)
    assert [record.name for record in records] == ["Bug", "Lone", "Point Only"]
    assert (len(records[0].perimeters), len(records[0].points)) == (2, 1)
    assert records[1].points.empty
    assert records[2].perimeters.empty


def test_fire_score_total_sums_all_signals() -> None:
    score = peri_scribe.fire_scores.FireScore(
        name="Bug",
        identifier="2026-a",
        size_points=5,
        growth_points=4,
        first_mapping_points=3,
        building_points=2,
        evacuation_points=3,
        red_flag_warning_points=2,
        wui_points=2,
        importance_points=1,
    )
    assert score.total == pytest.approx(22)


def test_fire_score_for_combines_all_signals() -> None:
    perimeters = perimeter_frame(
        [
            {
                "fire_name": "Bug",
                "fire_identifier": "2026-a",
                "area_acres": 120_000.0,
                "area_acres_differential": 60_000.0,
                "observation_time": datetime.datetime(2026, 8, 1),
            },
        ],
        [square(0.01)],
    )
    points = point_frame(
        [
            {
                "fire_name": "Bug",
                "fire_identifier": "2026-a",
                "source_attributes": json.dumps(
                    {"IncidentComplexityLevel": "Type 2 Incident"},
                ),
            },
        ],
        [point(0, 0)],
    )
    record = peri_scribe.fire_scores.fire_records(perimeters, points)[0]
    score = peri_scribe.fire_scores.fire_score_for(
        record,
        peri_scribe.fire_scores.perimeter_metrics(record.perimeters),
        building_count=5,
        evacuation_overlap=True,
        red_flag_warning_overlap=True,
        wui_overlap=True,
    )
    assert score.size_points == pytest.approx(5)
    assert score.growth_points == pytest.approx(4)
    assert score.first_mapping_points == pytest.approx(3)
    assert score.building_points == 1
    assert score.evacuation_points == pytest.approx(3)
    assert score.red_flag_warning_points == pytest.approx(2)
    assert score.wui_points == pytest.approx(2)
    assert score.importance_points == pytest.approx(2)
    assert score.total == pytest.approx(22)


def test_fire_score_for_awards_no_overlap_points_without_overlaps() -> None:
    points = point_frame(
        [{"fire_name": "Point Only", "fire_identifier": None}],
        [point(0, 0)],
    )
    record = peri_scribe.fire_scores.fire_records(
        perimeter_frame([], []),
        points,
    )[0]
    score = peri_scribe.fire_scores.fire_score_for(
        record,
        peri_scribe.fire_scores.perimeter_metrics(record.perimeters),
        building_count=0,
        evacuation_overlap=False,
        red_flag_warning_overlap=False,
        wui_overlap=False,
    )
    assert score.name == "Point Only"
    assert score.identifier is None
    assert score.building_points == 0
    assert score.evacuation_points == 0
    assert score.red_flag_warning_points == 0
    assert score.wui_points == 0


def test_fire_scores_path_names_output() -> None:
    assert peri_scribe.fire_scores.fire_scores_path(
        pathlib.Path("data/2026"),
    ) == pathlib.Path("data/2026/derived/fire_scores.json")


def test_best_score_uses_current_when_no_previous() -> None:
    assert peri_scribe.fire_scores.best_score(None, 7) == pytest.approx(7)


def test_best_score_keeps_the_highest_score() -> None:
    assert peri_scribe.fire_scores.best_score(10, 7) == pytest.approx(10)
    assert peri_scribe.fire_scores.best_score(7, 10) == pytest.approx(10)


def test_score_entry_maps_components_and_best_score() -> None:
    fire_score = peri_scribe.fire_scores.FireScore(
        name="Bug",
        identifier="2026-a",
        size_points=5,
        growth_points=4,
        first_mapping_points=3,
        building_points=2,
        evacuation_points=3,
        red_flag_warning_points=2,
        wui_points=2,
        importance_points=1,
    )
    entry = peri_scribe.fire_scores.score_entry(fire_score, previous_score=30)
    assert entry.name == "Bug"
    assert entry.identifier == "2026-a"
    assert entry.score == pytest.approx(30)
    assert entry.components.model_dump() == {
        "size": 5,
        "growth": 4,
        "first_mapping": 3,
        "buildings": 2,
        "evacuation": 3,
        "red_flag_warning": 2,
        "wui": 2,
        "importance": 1,
    }


def test_fire_scores_document_wraps_entries_with_version() -> None:
    entry = peri_scribe.models.FireScoreEntry(
        name="Bug",
        identifier=None,
        score=5,
        components=peri_scribe.models.FireScoreComponents(
            size=5,
            growth=0,
            first_mapping=0,
            buildings=0,
            evacuation=0,
            red_flag_warning=0,
            wui=0,
            importance=0,
        ),
    )
    document = peri_scribe.fire_scores.fire_scores_document([entry])
    assert document.version == peri_scribe.fire_scores.FIRE_SCORES_VERSION
    assert document.fires == [entry]


def test_previous_scores_returns_empty_without_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pathlib.Path, "is_file", lambda _self: False)
    assert peri_scribe.fire_scores.previous_scores(pathlib.Path("data/2026")) == {}


def test_previous_scores_reads_existing_scores(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = {
        "version": peri_scribe.fire_scores.FIRE_SCORES_VERSION,
        "fires": [
            {
                "name": "Bug",
                "identifier": "2026-a",
                "score": 12,
                "components": {
                    "size": 5,
                    "growth": 4,
                    "first_mapping": 0,
                    "buildings": 0,
                    "evacuation": 3,
                    "red_flag_warning": 0,
                    "wui": 0,
                    "importance": 0,
                },
            },
        ],
    }
    monkeypatch.setattr(pathlib.Path, "is_file", lambda _self: True)
    monkeypatch.setattr(
        pathlib.Path,
        "read_text",
        lambda _self, *_arguments, **_keywords: json.dumps(document),
    )
    assert peri_scribe.fire_scores.previous_scores(pathlib.Path("data/2026")) == {
        "2026-a": 12,
    }


def test_read_layer_if_present_returns_empty_without_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pathlib.Path, "is_file", lambda _self: False)
    result = peri_scribe.fire_scores.read_layer_if_present(
        pathlib.Path("/missing.gpkg"),
        "layer",
    )
    assert result.empty


def test_read_layer_if_present_reads_existing_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame = perimeter_frame(
        [{"fire_name": "Bug"}],
        [square(1.0)],
    )
    monkeypatch.setattr(pathlib.Path, "is_file", lambda _self: True)
    monkeypatch.setattr(
        peri_scribe.geo_package,
        "read_layer",
        lambda _path, _layer_name: frame,
    )
    result = peri_scribe.fire_scores.read_layer_if_present(
        pathlib.Path("/present.gpkg"),
        "perimeter_history",
    )
    assert result is frame


def test_latest_snapshot_path_returns_none_without_snapshots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        peri_scribe.snapshots,
        "existing_source_files",
        lambda _directory: [],
    )
    assert (
        peri_scribe.fire_scores.latest_snapshot_path(
            pathlib.Path("/sources/evacuations"),
        )
        is None
    )


def test_latest_snapshot_path_returns_newest_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = pathlib.Path("/sources/evacuations")
    monkeypatch.setattr(
        peri_scribe.snapshots,
        "existing_source_files",
        lambda _directory: [
            peri_scribe.snapshots.SourceFile(
                serial_number=0,
                last_edit_timestamp=1,
            ),
            peri_scribe.snapshots.SourceFile(
                serial_number=1,
                last_edit_timestamp=2,
            ),
        ],
    )
    assert peri_scribe.fire_scores.latest_snapshot_path(directory) == (
        directory / "000___" / "000001,lastEdit=2.gpkg"
    )


def test_download_source_layer_returns_none_without_layer_name() -> None:
    source = peri_scribe.external_sources.ExternalSource(
        name="none",
        kind=peri_scribe.external_sources.ExternalSourceKind.DOWNLOAD,
        url="https://example.test/file.zip",
    )
    assert (
        peri_scribe.fire_scores.download_source_layer(
            pathlib.Path("data/2026"),
            source,
        )
        is None
    )


def test_download_source_layer_names_source_geopackage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        peri_scribe.external_sources,
        "output_path",
        lambda _year_directory, _source: pathlib.Path("/sources/buildings.gpkg"),
    )
    assert peri_scribe.fire_scores.download_source_layer(
        pathlib.Path("data/2026"),
        peri_scribe.external_sources.BUILDINGS_SOURCE,
    ) == (pathlib.Path("/sources/buildings.gpkg"), "buildings")


def test_latest_snapshot_layer_returns_none_without_layer_name() -> None:
    source = peri_scribe.external_sources.ExternalSource(
        name="none",
        kind=peri_scribe.external_sources.ExternalSourceKind.ARCGIS,
        url="https://example.test/FeatureServer/0",
    )
    assert (
        peri_scribe.fire_scores.latest_snapshot_layer(
            pathlib.Path("data/2026"),
            source,
        )
        is None
    )


def test_latest_snapshot_layer_returns_none_without_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        peri_scribe.fire_scores,
        "latest_snapshot_path",
        lambda _directory: None,
    )
    assert (
        peri_scribe.fire_scores.latest_snapshot_layer(
            pathlib.Path("data/2026"),
            peri_scribe.external_sources.EVACUATIONS_SOURCE,
        )
        is None
    )


def test_latest_snapshot_layer_names_newest_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        peri_scribe.fire_scores,
        "latest_snapshot_path",
        lambda _directory: pathlib.Path("/sources/evacuations/0.gpkg"),
    )
    assert peri_scribe.fire_scores.latest_snapshot_layer(
        pathlib.Path("data/2026"),
        peri_scribe.external_sources.EVACUATIONS_SOURCE,
    ) == (pathlib.Path("/sources/evacuations/0.gpkg"), "evacuations")


def test_read_download_source_returns_empty_without_layer_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = peri_scribe.external_sources.ExternalSource(
        name="none",
        kind=peri_scribe.external_sources.ExternalSourceKind.DOWNLOAD,
        url="https://example.test/file.zip",
    )
    assert peri_scribe.fire_scores.read_download_source(
        pathlib.Path("data/2026"),
        source,
    ).empty


def test_read_download_source_reads_source_geopackage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame = geopandas.GeoDataFrame(
        {"name": ["a"]},
        geometry=[point(0, 0)],
        crs="EPSG:4326",
    )
    monkeypatch.setattr(
        peri_scribe.external_sources,
        "output_path",
        lambda _year_directory, _source: pathlib.Path("/sources/buildings.gpkg"),
    )
    monkeypatch.setattr(pathlib.Path, "is_file", lambda _self: True)
    monkeypatch.setattr(
        peri_scribe.geo_package,
        "read_layer",
        lambda _path, _layer_name: frame,
    )
    result = peri_scribe.fire_scores.read_download_source(
        pathlib.Path("data/2026"),
        peri_scribe.external_sources.BUILDINGS_SOURCE,
    )
    assert result is frame


def test_read_latest_snapshot_returns_empty_without_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        peri_scribe.fire_scores,
        "latest_snapshot_path",
        lambda _directory: None,
    )
    assert peri_scribe.fire_scores.read_latest_snapshot(
        pathlib.Path("data/2026"),
        peri_scribe.external_sources.EVACUATIONS_SOURCE,
    ).empty


def test_read_latest_snapshot_returns_empty_without_layer_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = peri_scribe.external_sources.ExternalSource(
        name="none",
        kind=peri_scribe.external_sources.ExternalSourceKind.ARCGIS,
        url="https://example.test/FeatureServer/0",
    )
    assert peri_scribe.fire_scores.read_latest_snapshot(
        pathlib.Path("data/2026"),
        source,
    ).empty


def test_read_latest_snapshot_reads_newest_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame = geopandas.GeoDataFrame(
        {"name": ["zone"]},
        geometry=[square(1.0)],
        crs="EPSG:4326",
    )
    monkeypatch.setattr(
        peri_scribe.fire_scores,
        "latest_snapshot_path",
        lambda _directory: pathlib.Path("/sources/evacuations/0.gpkg"),
    )
    monkeypatch.setattr(
        peri_scribe.geo_package,
        "read_layer",
        lambda _path, _layer_name: frame,
    )
    result = peri_scribe.fire_scores.read_latest_snapshot(
        pathlib.Path("data/2026"),
        peri_scribe.external_sources.EVACUATIONS_SOURCE,
    )
    assert result is frame


def test_score_fires_writes_best_scores(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    perimeters = perimeter_frame(
        [
            {
                "fire_name": "Bug",
                "fire_identifier": "2026-a",
                "area_acres": 120_000.0,
                "area_acres_differential": 0.0,
                "observation_time": datetime.datetime(2026, 8, 1),
            },
        ],
        [square(0.01)],
    )
    points = point_frame(
        [
            {
                "fire_name": "Bug",
                "fire_identifier": "2026-a",
                "source_attributes": json.dumps({}),
            },
        ],
        [point(0, 0)],
    )

    def read_layer_if_present(
        _path: pathlib.Path,
        layer_name: str,
    ) -> geopandas.GeoDataFrame:
        if layer_name == peri_scribe.fire_history.PERIMETER_LAYER_NAME:
            return perimeters
        if layer_name == peri_scribe.fire_history.POINT_LAYER_NAME:
            return points
        return empty_frame()

    monkeypatch.setattr(
        peri_scribe.fire_scores,
        "read_layer_if_present",
        read_layer_if_present,
    )
    monkeypatch.setattr(
        peri_scribe.fire_scores,
        "download_source_layer",
        lambda _year_directory, _source: None,
    )
    monkeypatch.setattr(
        peri_scribe.fire_scores,
        "latest_snapshot_layer",
        lambda _year_directory, _source: None,
    )
    monkeypatch.setattr(
        peri_scribe.fire_scores,
        "previous_scores",
        lambda _year_directory: {"2026-a": 9},
    )
    monkeypatch.setattr(
        pathlib.Path,
        "mkdir",
        lambda *_arguments, **_keywords: None,
    )
    writes: list[tuple[pathlib.Path, peri_scribe.models.FireScores]] = []
    monkeypatch.setattr(
        peri_scribe.output,
        "write_fire_scores",
        lambda path, document: writes.append((path, document)),
    )

    result = peri_scribe.fire_scores.score_fires(pathlib.Path("data/2026"))

    assert result == pathlib.Path("data/2026/derived/fire_scores.json")
    assert len(writes) == 1
    _path, document = writes[0]
    assert document.fires[0].name == "Bug"
    assert document.fires[0].score == pytest.approx(9)
    assert document.fires[0].components.size == pytest.approx(5)


def test_score_fires_streams_external_signals(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    perimeters = perimeter_frame(
        [
            {
                "fire_name": "Bug",
                "fire_identifier": "2026-a",
                "area_acres": 120_000.0,
                "area_acres_differential": 0.0,
                "observation_time": datetime.datetime(2026, 8, 1),
            },
        ],
        [square(0.01)],
    )
    points = point_frame(
        [
            {
                "fire_name": "Bug",
                "fire_identifier": "2026-a",
                "source_attributes": json.dumps(
                    {"IncidentComplexityLevel": "Type 2 Incident"},
                ),
            },
        ],
        [point(0, 0)],
    )

    def read_layer_if_present(
        _path: pathlib.Path,
        layer_name: str,
    ) -> geopandas.GeoDataFrame:
        if layer_name == peri_scribe.fire_history.PERIMETER_LAYER_NAME:
            return perimeters
        if layer_name == peri_scribe.fire_history.POINT_LAYER_NAME:
            return points
        return empty_frame()

    buildings = geopandas.GeoDataFrame(
        {"name": ["a"] * 5},
        geometry=[point(0, 0)] * 5,
        crs="EPSG:4326",
    )
    buildings_path = tmp_path / "sources" / "buildings" / "buildings.gpkg"
    buildings_path.parent.mkdir(parents=True)
    buildings.to_file(buildings_path, layer="buildings")
    for name in ("evacuations", "red_flag_warnings"):
        snapshot = tmp_path / "sources" / name / "snapshot.gpkg"
        snapshot.parent.mkdir(parents=True)
        geopandas.GeoDataFrame(
            {"name": ["zone"]},
            geometry=[square(1.0)],
            crs="EPSG:4326",
        ).to_file(snapshot, layer=name)
    wui_path = tmp_path / "sources" / "wui" / "wui.gpkg"
    wui_path.parent.mkdir(parents=True)
    geopandas.GeoDataFrame(
        {"name": ["zone"]},
        geometry=[square(1.0)],
        crs="EPSG:4326",
    ).to_file(wui_path, layer="wui")

    def output_path(
        _year_directory: pathlib.Path,
        source: peri_scribe.external_sources.ExternalSource,
        **_keywords: object,
    ) -> pathlib.Path:
        return tmp_path / "sources" / source.name / f"{source.name}.gpkg"

    monkeypatch.setattr(
        peri_scribe.external_sources,
        "output_path",
        output_path,
    )
    monkeypatch.setattr(
        peri_scribe.fire_scores,
        "latest_snapshot_path",
        lambda directory: directory / "snapshot.gpkg",
    )
    monkeypatch.setattr(
        peri_scribe.fire_scores,
        "read_layer_if_present",
        read_layer_if_present,
    )
    monkeypatch.setattr(
        peri_scribe.fire_scores,
        "previous_scores",
        lambda _year_directory: {},
    )
    monkeypatch.setattr(
        pathlib.Path,
        "mkdir",
        lambda *_arguments, **_keywords: None,
    )
    writes: list[tuple[pathlib.Path, peri_scribe.models.FireScores]] = []
    monkeypatch.setattr(
        peri_scribe.output,
        "write_fire_scores",
        lambda path, document: writes.append((path, document)),
    )

    result = peri_scribe.fire_scores.score_fires(tmp_path)

    assert result == tmp_path / "derived" / "fire_scores.json"
    entry = writes[0][1].fires[0]
    assert entry.name == "Bug"
    assert entry.score == pytest.approx(18)
    assert entry.components.buildings == pytest.approx(1)
    assert entry.components.evacuation == pytest.approx(3)
    assert entry.components.red_flag_warning == pytest.approx(2)
    assert entry.components.wui == pytest.approx(2)
    assert entry.components.importance == pytest.approx(2)


def test_score_fires_sorts_entries_by_score_descending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    perimeters = perimeter_frame(
        [
            {
                "fire_name": "Big",
                "fire_identifier": "2026-a",
                "area_acres": 120_000.0,
                "area_acres_differential": 0.0,
                "observation_time": datetime.datetime(2026, 8, 1),
            },
            {
                "fire_name": "Small",
                "fire_identifier": "2026-b",
                "area_acres": 100.0,
                "area_acres_differential": 0.0,
                "observation_time": datetime.datetime(2026, 8, 1),
            },
        ],
        [square(0.01), square(0.01)],
    )

    def read_layer_if_present(
        _path: pathlib.Path,
        layer_name: str,
    ) -> geopandas.GeoDataFrame:
        if layer_name == peri_scribe.fire_history.PERIMETER_LAYER_NAME:
            return perimeters
        return empty_frame()

    monkeypatch.setattr(
        peri_scribe.fire_scores,
        "read_layer_if_present",
        read_layer_if_present,
    )
    monkeypatch.setattr(
        peri_scribe.fire_scores,
        "download_source_layer",
        lambda _year_directory, _source: None,
    )
    monkeypatch.setattr(
        peri_scribe.fire_scores,
        "latest_snapshot_layer",
        lambda _year_directory, _source: None,
    )
    monkeypatch.setattr(
        peri_scribe.fire_scores,
        "previous_scores",
        lambda _year_directory: {},
    )
    monkeypatch.setattr(
        pathlib.Path,
        "mkdir",
        lambda *_arguments, **_keywords: None,
    )
    writes: list[tuple[pathlib.Path, peri_scribe.models.FireScores]] = []
    monkeypatch.setattr(
        peri_scribe.output,
        "write_fire_scores",
        lambda path, document: writes.append((path, document)),
    )

    peri_scribe.fire_scores.score_fires(pathlib.Path("data/2026"))

    assert [entry.name for entry in writes[0][1].fires] == ["Big", "Small"]
