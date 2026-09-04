"""Tests for peri_scribe.fires.scores."""

from __future__ import annotations

import datetime
import json
import pathlib
import tempfile

import geopandas
import numpy as np
import pytest

import peri_scribe.fires.files
import peri_scribe.fires.identity
import peri_scribe.fires.scores
import peri_scribe.geo.reading
import peri_scribe.models
import peri_scribe.output
import peri_scribe.sources.buildings
import peri_scribe.sources.external_sources
import tests.peri_scribe.fires.fire_helpers


def test_read_layer_if_present_returns_empty_without_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pathlib.Path, "is_file", lambda _self: False)
    result = peri_scribe.fires.scores.read_layer_if_present(
        pathlib.Path("/missing.gpkg"),
        "layer",
    )
    assert result.empty


def test_read_layer_if_present_reads_existing_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame = tests.peri_scribe.fires.fire_helpers.perimeter_frame(
        [{"fire_name": "Bug"}],
        [tests.peri_scribe.fires.fire_helpers.square(1.0)],
    )
    monkeypatch.setattr(pathlib.Path, "is_file", lambda _self: True)
    monkeypatch.setattr(
        peri_scribe.geo.reading,
        "read_layer",
        lambda _path, _layer_name: frame,
    )
    result = peri_scribe.fires.scores.read_layer_if_present(
        pathlib.Path("/present.gpkg"),
        "perimeter_history",
    )
    assert result is frame


def test_latest_snapshot_layer_returns_none_without_layer_name() -> None:
    source = peri_scribe.sources.external_sources.ExternalSource(
        name="none",
        kind=peri_scribe.sources.external_sources.ExternalSourceKind.ARCGIS,
        url="https://example.test/FeatureServer/0",
    )
    assert (
        peri_scribe.fires.scores.latest_snapshot_layer(
            pathlib.Path("data/2026"),
            source,
        )
        is None
    )


def test_latest_snapshot_layer_returns_none_without_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        peri_scribe.sources.external_sources,
        "output_path",
        lambda _year_directory, _source: pathlib.Path(
            "/sources/evacuations.gpkg",
        ),
    )
    assert (
        peri_scribe.fires.scores.latest_snapshot_layer(
            pathlib.Path("data/2026"),
            peri_scribe.sources.external_sources.EVACUATIONS_SOURCE,
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
        peri_scribe.sources.external_sources,
        "output_path",
        lambda _year_directory, _source: path,
    )
    assert peri_scribe.fires.scores.latest_snapshot_layer(
        pathlib.Path("data/2026"),
        peri_scribe.sources.external_sources.EVACUATIONS_SOURCE,
    ) == (path, "evacuations")


def test_read_latest_snapshot_returns_empty_without_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        peri_scribe.sources.external_sources,
        "output_path",
        lambda _year_directory, _source: pathlib.Path(
            "/sources/evacuations.gpkg",
        ),
    )
    assert peri_scribe.fires.scores.read_latest_snapshot(
        pathlib.Path("data/2026"),
        peri_scribe.sources.external_sources.EVACUATIONS_SOURCE,
    ).empty


def test_read_latest_snapshot_returns_empty_without_layer_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = peri_scribe.sources.external_sources.ExternalSource(
        name="none",
        kind=peri_scribe.sources.external_sources.ExternalSourceKind.ARCGIS,
        url="https://example.test/FeatureServer/0",
    )
    assert peri_scribe.fires.scores.read_latest_snapshot(
        pathlib.Path("data/2026"),
        source,
    ).empty


def test_read_latest_snapshot_reads_source_geopackage(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame = geopandas.GeoDataFrame(
        {"name": ["zone"]},
        geometry=[tests.peri_scribe.fires.fire_helpers.square(1.0)],
        crs="EPSG:4326",
    )
    path = tmp_path / "evacuations.gpkg"
    path.write_bytes(b"data")
    monkeypatch.setattr(
        peri_scribe.sources.external_sources,
        "output_path",
        lambda _year_directory, _source: path,
    )
    monkeypatch.setattr(
        peri_scribe.geo.reading,
        "read_layer",
        lambda _path, _layer_name: frame,
    )
    result = peri_scribe.fires.scores.read_latest_snapshot(
        pathlib.Path("data/2026"),
        peri_scribe.sources.external_sources.EVACUATIONS_SOURCE,
    )
    assert result is frame


def test_score_fires_writes_current_scores(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    perimeters = tests.peri_scribe.fires.fire_helpers.perimeter_frame(
        [
            {
                "fire_name": "Bug",
                "fire_identifier": "2026-a",
                "area_acres": 120_000.0,
                "area_acres_differential": 0.0,
                "observation_time": datetime.datetime(2026, 8, 1),
            },
        ],
        [tests.peri_scribe.fires.fire_helpers.square(0.01)],
    )
    points = tests.peri_scribe.fires.fire_helpers.point_frame(
        [
            {
                "fire_name": "Bug",
                "fire_identifier": "2026-a",
                "source_attributes": json.dumps({}),
            },
        ],
        [tests.peri_scribe.fires.fire_helpers.point(0, 0)],
    )

    def read_layer_if_present(
        _path: pathlib.Path,
        layer_name: str,
    ) -> geopandas.GeoDataFrame:
        if layer_name == peri_scribe.fires.files.PERIMETER_LAYER_NAME:
            return perimeters
        if layer_name == peri_scribe.fires.files.POINT_LAYER_NAME:
            return points
        return tests.peri_scribe.fires.fire_helpers.empty_frame()

    monkeypatch.setattr(
        peri_scribe.fires.scores,
        "read_layer_if_present",
        read_layer_if_present,
    )
    monkeypatch.setattr(
        peri_scribe.sources.external_sources,
        "output_path",
        lambda _year_directory, _source: pathlib.Path("/missing/buildings.sqlite"),
    )
    monkeypatch.setattr(
        peri_scribe.fires.scores,
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

    result = peri_scribe.fires.scores.score_fires(pathlib.Path("data/2026"))

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
    perimeters = tests.peri_scribe.fires.fire_helpers.perimeter_frame(
        [
            {
                "fire_name": "Bug",
                "fire_identifier": "2026-a",
                "area_acres": 120_000.0,
                "area_acres_differential": 0.0,
                "observation_time": datetime.datetime(2026, 8, 1),
            },
        ],
        [tests.peri_scribe.fires.fire_helpers.square(0.01)],
    )
    points = tests.peri_scribe.fires.fire_helpers.point_frame(
        [
            {
                "fire_name": "Bug",
                "fire_identifier": "2026-a",
                "source_attributes": json.dumps(
                    {"IncidentComplexityLevel": "Type 2 Incident"},
                ),
            },
        ],
        [tests.peri_scribe.fires.fire_helpers.point(0, 0)],
    )

    def read_layer_if_present(
        _path: pathlib.Path,
        layer_name: str,
    ) -> geopandas.GeoDataFrame:
        if layer_name == peri_scribe.fires.files.PERIMETER_LAYER_NAME:
            return perimeters
        if layer_name == peri_scribe.fires.files.POINT_LAYER_NAME:
            return points
        return tests.peri_scribe.fires.fire_helpers.empty_frame()

    buildings_path = tmp_path / "sources" / "buildings" / "buildings.sqlite"
    buildings_path.parent.mkdir(parents=True)
    with tempfile.TemporaryDirectory() as temporary_directory:
        partition_directory = pathlib.Path(temporary_directory)
        with peri_scribe.sources.buildings.PartitionFiles(
            partition_directory,
        ) as partition_files:
            peri_scribe.sources.buildings.append_centroids_to_partitions(
                np.asarray([[0.0, 0.0]] * 5),
                partition_files,
            )
        peri_scribe.sources.buildings.build_tiles_database(
            partition_directory,
            buildings_path,
        )
    for name in ("evacuations",):
        snapshot = tmp_path / "sources" / name / f"{name}.gpkg"
        snapshot.parent.mkdir(parents=True)
        geopandas.GeoDataFrame(
            {"name": ["zone"]},
            geometry=[tests.peri_scribe.fires.fire_helpers.square(1.0)],
            crs="EPSG:4326",
        ).to_file(snapshot, layer=name)

    def output_path(
        _year_directory: pathlib.Path,
        source: peri_scribe.sources.external_sources.ExternalSource,
        **_keywords: object,
    ) -> pathlib.Path:
        suffix = ".sqlite" if source.compact_database else ".gpkg"
        return tmp_path / "sources" / source.name / f"{source.name}{suffix}"

    monkeypatch.setattr(
        peri_scribe.sources.external_sources,
        "output_path",
        output_path,
    )
    monkeypatch.setattr(
        peri_scribe.fires.scores,
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

    result = peri_scribe.fires.scores.score_fires(tmp_path)

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
    perimeters = tests.peri_scribe.fires.fire_helpers.perimeter_frame(
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
        [
            tests.peri_scribe.fires.fire_helpers.square(0.01),
            tests.peri_scribe.fires.fire_helpers.square(0.01),
        ],
    )

    def read_layer_if_present(
        _path: pathlib.Path,
        layer_name: str,
    ) -> geopandas.GeoDataFrame:
        if layer_name == peri_scribe.fires.files.PERIMETER_LAYER_NAME:
            return perimeters
        return tests.peri_scribe.fires.fire_helpers.empty_frame()

    monkeypatch.setattr(
        peri_scribe.fires.scores,
        "read_layer_if_present",
        read_layer_if_present,
    )
    monkeypatch.setattr(
        peri_scribe.sources.external_sources,
        "output_path",
        lambda _year_directory, _source: pathlib.Path("/missing/buildings.sqlite"),
    )
    monkeypatch.setattr(
        peri_scribe.fires.scores,
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

    peri_scribe.fires.scores.score_fires(pathlib.Path("data/2026"))

    assert [entry.name for entry in writes[0][1].fires] == ["Big", "Small"]


def test_score_fires_scores_point_only_fire(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    points = tests.peri_scribe.fires.fire_helpers.point_frame(
        [
            {
                "fire_name": "Smoke",
                "fire_identifier": None,
                "source_attributes": json.dumps({}),
            },
        ],
        [tests.peri_scribe.fires.fire_helpers.point(0, 0)],
    )

    def read_layer_if_present(
        _path: pathlib.Path,
        layer_name: str,
    ) -> geopandas.GeoDataFrame:
        if layer_name == peri_scribe.fires.files.POINT_LAYER_NAME:
            return points
        return tests.peri_scribe.fires.fire_helpers.empty_frame()

    monkeypatch.setattr(
        peri_scribe.fires.scores,
        "read_layer_if_present",
        read_layer_if_present,
    )
    monkeypatch.setattr(
        peri_scribe.sources.external_sources,
        "output_path",
        lambda _year_directory, _source: pathlib.Path("/missing/buildings.sqlite"),
    )
    monkeypatch.setattr(
        peri_scribe.fires.scores,
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

    peri_scribe.fires.scores.score_fires(pathlib.Path("data/2026"))

    assert [entry.name for entry in writes[0][1].fires] == ["Smoke"]


def test_fire_metrics_prefers_geometry_when_reported_understates() -> None:
    perimeters = geopandas.GeoDataFrame(
        {
            "fire_name": ["Snow", "Snow"],
            "fire_identifier": ["2026-a", "2026-a"],
            "area_acres": [1100.0, 1200.0],
            "area_acres_differential": [1100.0, 100.0],
            "area_acres_from_geometry": [2939.0, 3039.0],
            "area_acres_from_geometry_differential": [2939.0, 100.0],
            "observation_time": [
                datetime.datetime(2026, 9, 3, 1, 0),
                datetime.datetime(2026, 9, 4, 1, 0),
            ],
        },
        geometry=[
            tests.peri_scribe.fires.fire_helpers.square(0.01),
            tests.peri_scribe.fires.fire_helpers.square(0.01),
        ],
        crs="EPSG:4326",
    )
    perimeter_keys = peri_scribe.fires.identity.group_keys(perimeters)
    metrics, first_mapping = peri_scribe.fires.scores.fire_metrics(
        perimeters,
        perimeter_keys,
    )
    assert metrics.loc["2026-a", "max_area"] == pytest.approx(3039.0)
    assert metrics.loc["2026-a", "max_growth"] == pytest.approx(2939.0)
    assert first_mapping["2026-a"] == pytest.approx(2939.0)


def test_fire_metrics_keeps_reported_when_geometry_agrees() -> None:
    perimeters = geopandas.GeoDataFrame(
        {
            "fire_name": ["Snow"],
            "fire_identifier": ["2026-a"],
            "area_acres": [1100.0],
            "area_acres_differential": [1100.0],
            "area_acres_from_geometry": [1110.0],
            "area_acres_from_geometry_differential": [1110.0],
            "observation_time": [datetime.datetime(2026, 9, 3, 1, 0)],
        },
        geometry=[tests.peri_scribe.fires.fire_helpers.square(0.01)],
        crs="EPSG:4326",
    )
    perimeter_keys = peri_scribe.fires.identity.group_keys(perimeters)
    metrics, first_mapping = peri_scribe.fires.scores.fire_metrics(
        perimeters,
        perimeter_keys,
    )
    assert metrics.loc["2026-a", "max_area"] == pytest.approx(1100.0)
    assert metrics.loc["2026-a", "max_growth"] == pytest.approx(1100.0)
    assert first_mapping["2026-a"] == pytest.approx(1100.0)
