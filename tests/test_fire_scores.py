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


def test_fire_score_total_sums_all_signals() -> None:
    score = peri_scribe.fire_scores.FireScore(
        name="Bug",
        identifier="2026-a",
        size_points=135,
        growth_points=60,
        first_mapping_points=33,
        building_points=8,
        evacuation_points=33,
        importance_points=120,
    )
    assert score.total == pytest.approx(389)


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
    record = peri_scribe.fire_scores.FireRecords(
        name="Bug",
        identifier="2026-a",
        perimeters=perimeters,
        points=points,
    )
    score = peri_scribe.fire_scores.fire_score_for(
        record,
        peri_scribe.fire_scores.PerimeterMetrics(
            area_acres=120_000.0,
            growth_acres=60_000.0,
            first_mapping_acres=120_000.0,
            geometry=None,
        ),
        building_count=5,
        evacuation_overlap=True,
    )
    assert score.size_points == pytest.approx(135)
    assert score.growth_points == pytest.approx(60)
    assert score.first_mapping_points == pytest.approx(33)
    assert score.building_points == pytest.approx(4)
    assert score.evacuation_points == pytest.approx(33)
    assert score.importance_points == pytest.approx(240)
    assert score.total == pytest.approx(505)


def test_fire_score_for_awards_no_overlap_points_without_overlaps() -> None:
    points = point_frame(
        [{"fire_name": "Point Only", "fire_identifier": None}],
        [point(0, 0)],
    )
    record = peri_scribe.fire_scores.FireRecords(
        name="Point Only",
        identifier=None,
        perimeters=perimeter_frame([], []),
        points=points,
    )
    score = peri_scribe.fire_scores.fire_score_for(
        record,
        peri_scribe.fire_scores.PerimeterMetrics(
            area_acres=None,
            growth_acres=None,
            first_mapping_acres=None,
            geometry=None,
        ),
        building_count=0,
        evacuation_overlap=False,
    )
    assert score.name == "Point Only"
    assert score.identifier is None
    assert score.building_points == 0
    assert score.evacuation_points == 0
    assert score.importance_points == 0


def test_fire_scores_path_names_output() -> None:
    assert peri_scribe.fire_scores.fire_scores_path(
        pathlib.Path("data/2026"),
    ) == pathlib.Path("data/2026/derived/fire_scores.json")


def test_fire_scores_ccdf_path_names_output() -> None:
    assert peri_scribe.fire_scores.fire_scores_ccdf_path(
        pathlib.Path("data/2026"),
    ) == pathlib.Path("data/2026/derived/fire_scores_ccdf.png")


def test_score_entry_maps_components_and_total() -> None:
    fire_score = peri_scribe.fire_scores.FireScore(
        name="Bug",
        identifier="2026-a",
        size_points=135,
        growth_points=60,
        first_mapping_points=33,
        building_points=8,
        evacuation_points=33,
        importance_points=120,
    )
    entry = peri_scribe.fire_scores.score_entry(fire_score)
    assert entry.name == "Bug"
    assert entry.identifier == "2026-a"
    assert entry.score == pytest.approx(389)
    assert entry.components.model_dump() == {
        "size": 135,
        "growth": 60,
        "first_mapping": 33,
        "buildings": 8,
        "evacuation": 33,
        "importance": 120,
    }
    assert entry.explanation == (
        "Over 100,000 acres, a single growth step over "
        "50,000 acres, already over 5,000 acres when first mapped, over "
        "50 structures within a mile, overlap with an evacuation zone, and "
        "a Type 3 Incident."
    )


def test_score_explanation_describes_each_contributing_signal() -> None:
    fire_score = peri_scribe.fire_scores.FireScore(
        name="Bug",
        identifier="2026-a",
        size_points=27,
        growth_points=15,
        first_mapping_points=11,
        building_points=0,
        evacuation_points=0,
        importance_points=0,
    )
    assert peri_scribe.fire_scores.score_explanation(fire_score) == (
        "Over 1,000 acres, a single growth step over "
        "5,000 acres, and already over 100 acres when first mapped."
    )


def test_score_explanation_mentions_evacuation_and_importance() -> None:
    fire_score = peri_scribe.fire_scores.FireScore(
        name="Bug",
        identifier="2026-a",
        size_points=0,
        growth_points=0,
        first_mapping_points=0,
        building_points=0,
        evacuation_points=33,
        importance_points=360,
    )
    assert peri_scribe.fire_scores.score_explanation(fire_score) == (
        "Overlap with an evacuation zone, and a Type 1 Incident."
    )


def test_score_explanation_says_no_signals_when_score_is_zero() -> None:
    fire_score = peri_scribe.fire_scores.FireScore(
        name="Bug",
        identifier="2026-a",
        size_points=0,
        growth_points=0,
        first_mapping_points=0,
        building_points=0,
        evacuation_points=0,
        importance_points=0,
    )
    assert peri_scribe.fire_scores.score_explanation(fire_score) == (
        "No notable size, growth, threat, or official-importance signals."
    )


def test_signal_description_returns_none_without_points() -> None:
    assert (
        peri_scribe.fire_scores.signal_description(
            0,
            peri_scribe.fire_scores.SIZE_WEIGHT,
            peri_scribe.fire_scores.SIZE_DESCRIPTIONS,
        )
        is None
    )


def test_signal_description_names_the_tier() -> None:
    assert (
        peri_scribe.fire_scores.signal_description(
            4 * peri_scribe.fire_scores.BUILDINGS_WEIGHT,
            peri_scribe.fire_scores.BUILDINGS_WEIGHT,
            peri_scribe.fire_scores.BUILDING_COUNT_DESCRIPTIONS,
        )
        == "over 1,000 structures within a mile"
    )


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
            importance=0,
        ),
        explanation="Over 1,000 acres.",
    )
    document = peri_scribe.fire_scores.fire_scores_document([entry])
    assert document.version == peri_scribe.fire_scores.FIRE_SCORES_VERSION
    assert document.fires == [entry]


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
        peri_scribe.external_sources,
        "output_path",
        lambda _year_directory, _source: pathlib.Path(
            "/sources/evacuations.gpkg",
        ),
    )
    assert (
        peri_scribe.fire_scores.latest_snapshot_layer(
            pathlib.Path("data/2026"),
            peri_scribe.external_sources.EVACUATIONS_SOURCE,
        )
        is None
    )


def test_latest_snapshot_layer_names_source_geopackage(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "evacuations.gpkg"
    path.write_bytes(b"data")
    monkeypatch.setattr(
        peri_scribe.external_sources,
        "output_path",
        lambda _year_directory, _source: path,
    )
    assert peri_scribe.fire_scores.latest_snapshot_layer(
        pathlib.Path("data/2026"),
        peri_scribe.external_sources.EVACUATIONS_SOURCE,
    ) == (path, "evacuations")


def test_read_latest_snapshot_returns_empty_without_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        peri_scribe.external_sources,
        "output_path",
        lambda _year_directory, _source: pathlib.Path(
            "/sources/evacuations.gpkg",
        ),
    )
    assert peri_scribe.fire_scores.read_latest_snapshot(
        pathlib.Path("data/2026"),
        peri_scribe.external_sources.EVACUATIONS_SOURCE,
    ).empty


def test_load_fire_scores_returns_none_when_scores_are_missing(
    tmp_path: pathlib.Path,
) -> None:
    assert peri_scribe.fire_scores.load_fire_scores(tmp_path) is None


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


def test_read_latest_snapshot_reads_source_geopackage(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame = geopandas.GeoDataFrame(
        {"name": ["zone"]},
        geometry=[square(1.0)],
        crs="EPSG:4326",
    )
    path = tmp_path / "evacuations.gpkg"
    path.write_bytes(b"data")
    monkeypatch.setattr(
        peri_scribe.external_sources,
        "output_path",
        lambda _year_directory, _source: path,
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


def test_score_fires_writes_current_scores(
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
    ccdf_writes: list[tuple[pathlib.Path, peri_scribe.models.FireScores]] = []
    monkeypatch.setattr(
        peri_scribe.output,
        "write_fire_scores_ccdf",
        lambda path, document: ccdf_writes.append((path, document)),
    )

    result = peri_scribe.fire_scores.score_fires(pathlib.Path("data/2026"))

    assert result == pathlib.Path("data/2026/derived/fire_scores.json")
    assert len(writes) == 1
    _path, document = writes[0]
    assert document.fires[0].name == "Bug"
    assert document.fires[0].score == pytest.approx(168)
    assert document.fires[0].components.size == pytest.approx(135)
    assert ccdf_writes == [
        (
            pathlib.Path("data/2026/derived/fire_scores_ccdf.png"),
            document,
        ),
    ]


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
    for name in ("evacuations",):
        snapshot = tmp_path / "sources" / name / f"{name}.gpkg"
        snapshot.parent.mkdir(parents=True)
        geopandas.GeoDataFrame(
            {"name": ["zone"]},
            geometry=[square(1.0)],
            crs="EPSG:4326",
        ).to_file(snapshot, layer=name)

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
        "read_layer_if_present",
        read_layer_if_present,
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
    monkeypatch.setattr(
        peri_scribe.output,
        "write_fire_scores_ccdf",
        lambda _path, _document: None,
    )

    result = peri_scribe.fire_scores.score_fires(tmp_path)

    assert result == tmp_path / "derived" / "fire_scores.json"
    entry = writes[0][1].fires[0]
    assert entry.name == "Bug"
    assert entry.score == pytest.approx(445)
    assert entry.components.buildings == pytest.approx(4)
    assert entry.components.evacuation == pytest.approx(33)
    assert entry.components.importance == pytest.approx(240)


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
    monkeypatch.setattr(
        peri_scribe.output,
        "write_fire_scores_ccdf",
        lambda _path, _document: None,
    )

    peri_scribe.fire_scores.score_fires(pathlib.Path("data/2026"))

    assert [entry.name for entry in writes[0][1].fires] == ["Big", "Small"]


def test_overlapping_fire_indices_reads_z_geometries(
    tmp_path: pathlib.Path,
) -> None:
    zones = geopandas.GeoDataFrame(
        {"name": ["zone"]},
        geometry=[
            shapely.geometry.Polygon(
                [(0, 0, 0), (2, 0, 0), (2, 2, 0), (0, 2, 0), (0, 0, 0)],
            ),
        ],
        crs="EPSG:4326",
    )
    path = tmp_path / "zones.gpkg"
    zones.to_file(path, layer="zones")

    indices = peri_scribe.fire_scores.overlapping_fire_indices(
        [square(1.0)],
        path,
        "zones",
    )

    assert indices == {0}


def test_buffered_fire_geometries_returns_none_for_no_geometry() -> None:
    assert peri_scribe.fire_scores.buffered_fire_geometries([]) == []
    assert peri_scribe.fire_scores.buffered_fire_geometries([None, None]) == [
        None,
        None,
    ]


def test_building_counts_within_streams_without_rtree(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    buffered = peri_scribe.fire_scores.buffered_fire_geometries(
        [square(1.0), square(0.1)],
    )
    buildings = geopandas.GeoDataFrame(
        {"name": ["a"] * 5},
        geometry=[point(0, 0)] * 3 + [point(50, 50), point(60, 60)],
        crs="EPSG:4326",
    )
    path = tmp_path / "buildings.gpkg"
    buildings.to_file(path, layer="buildings")
    monkeypatch.setattr(
        peri_scribe.fire_scores,
        "_has_rtree",
        lambda _path, _layer: False,
    )

    counts = peri_scribe.fire_scores.building_counts_within(
        buffered,
        path,
        "buildings",
        chunk_size=2,
    )

    assert counts == [3, 3]


def test_overlapping_fire_indices_returns_empty_when_no_feature_overlaps(
    tmp_path: pathlib.Path,
) -> None:
    zones = geopandas.GeoDataFrame(
        {"name": ["far"]},
        geometry=[shapely.geometry.box(100.0, 100.0, 101.0, 101.0)],
        crs="EPSG:4326",
    )
    path = tmp_path / "zones.gpkg"
    zones.to_file(path, layer="zones")

    indices = peri_scribe.fire_scores.overlapping_fire_indices(
        [square(1.0)],
        path,
        "zones",
    )

    assert indices == set()


def test_overlapping_fire_indices_streams_without_rtree(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
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
    monkeypatch.setattr(
        peri_scribe.fire_scores,
        "_has_rtree",
        lambda _path, _layer: False,
    )

    indices = peri_scribe.fire_scores.overlapping_fire_indices(
        [square(1.0), shapely.geometry.box(50.0, 50.0, 51.0, 51.0)],
        path,
        "zones",
        chunk_size=1,
    )

    assert indices == {0}


def test_score_fires_scores_point_only_fire(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    points = point_frame(
        [
            {
                "fire_name": "Smoke",
                "fire_identifier": None,
                "source_attributes": json.dumps({}),
            },
        ],
        [point(0, 0)],
    )

    def read_layer_if_present(
        _path: pathlib.Path,
        layer_name: str,
    ) -> geopandas.GeoDataFrame:
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
    monkeypatch.setattr(
        peri_scribe.output,
        "write_fire_scores_ccdf",
        lambda _path, _document: None,
    )

    peri_scribe.fire_scores.score_fires(pathlib.Path("data/2026"))

    assert [entry.name for entry in writes[0][1].fires] == ["Smoke"]
