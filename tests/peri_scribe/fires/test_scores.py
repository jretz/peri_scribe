"""Tests for peri_scribe.fires.scores."""

from __future__ import annotations

import datetime
import json
import pathlib
import tempfile
import typing

import numpy as np
import pytest

import peri_scribe.fires.identity
import peri_scribe.fires.scores
import peri_scribe.sources.buildings
import peri_scribe.sources.external_sources
import tests.factories
import tests.peri_scribe.fires.fire_helpers


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


def test_score_fires_writes_current_scores(
    score_fires_stubs: typing.Callable[
        ...,
        tests.peri_scribe.fires.fire_helpers.ScoreFiresStubs,
    ],
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
        [tests.factories.square(0.01)],
    )
    points = tests.peri_scribe.fires.fire_helpers.point_frame(
        [
            {
                "fire_name": "Bug",
                "fire_identifier": "2026-a",
                "source_attributes": json.dumps({}),
            },
        ],
        [tests.factories.point(0, 0)],
    )
    stubs = score_fires_stubs(perimeters=perimeters, points=points)

    result = peri_scribe.fires.scores.score_fires(pathlib.Path("data/2026"))

    assert result == pathlib.Path("data/2026/derived/fire_scores.json")
    assert len(stubs.writes) == 1
    _path, document = stubs.writes[0]
    assert document.fires[0].name == "Bug"
    assert document.fires[0].score == pytest.approx(168)
    assert stubs.ccdf_writes == [
        (
            pathlib.Path("data/2026/derived/fire_scores_ccdf.png"),
            document,
        ),
    ]


def test_score_fires_streams_external_signals(
    tmp_path: pathlib.Path,
    score_fires_stubs: typing.Callable[
        ...,
        tests.peri_scribe.fires.fire_helpers.ScoreFiresStubs,
    ],
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
        [tests.factories.square(0.01)],
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
        [tests.factories.point(0, 0)],
    )

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
    snapshot = tmp_path / "sources" / "evacuations" / "evacuations.gpkg"
    snapshot.parent.mkdir(parents=True)
    tests.factories.geo_frame(
        {"name": ["zone"]},
        [tests.factories.square(1.0)],
    ).to_file(snapshot, layer="evacuations")

    def output_path(
        _year_directory: pathlib.Path,
        source: peri_scribe.sources.external_sources.ExternalSource,
        **_keywords: object,
    ) -> pathlib.Path:
        suffix = ".sqlite" if source.compact_database else ".gpkg"
        return tmp_path / "sources" / source.name / f"{source.name}{suffix}"

    stubs = score_fires_stubs(
        perimeters=perimeters,
        points=points,
        output_path=output_path,
        stub_latest_snapshot_layer=False,
    )

    result = peri_scribe.fires.scores.score_fires(tmp_path)

    assert result == tmp_path / "derived" / "fire_scores.json"
    entry = stubs.writes[0][1].fires[0]
    assert entry.name == "Bug"
    assert entry.score == pytest.approx(445)


def test_score_fires_sorts_entries_by_score_descending(
    score_fires_stubs: typing.Callable[
        ...,
        tests.peri_scribe.fires.fire_helpers.ScoreFiresStubs,
    ],
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
        [tests.factories.square(0.01), tests.factories.square(0.01)],
    )
    stubs = score_fires_stubs(perimeters=perimeters)

    peri_scribe.fires.scores.score_fires(pathlib.Path("data/2026"))

    assert [entry.name for entry in stubs.writes[0][1].fires] == ["Big", "Small"]


def test_score_fires_scores_point_only_fire(
    score_fires_stubs: typing.Callable[
        ...,
        tests.peri_scribe.fires.fire_helpers.ScoreFiresStubs,
    ],
) -> None:
    points = tests.peri_scribe.fires.fire_helpers.point_frame(
        [
            {
                "fire_name": "Smoke",
                "fire_identifier": None,
                "source_attributes": json.dumps({}),
            },
        ],
        [tests.factories.point(0, 0)],
    )
    stubs = score_fires_stubs(points=points)

    peri_scribe.fires.scores.score_fires(pathlib.Path("data/2026"))

    assert [entry.name for entry in stubs.writes[0][1].fires] == ["Smoke"]


def test_fire_metrics_prefers_geometry_when_reported_understates() -> None:
    perimeters = tests.factories.geo_frame(
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
        [tests.factories.square(0.01), tests.factories.square(0.01)],
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
    perimeters = tests.factories.geo_frame(
        {
            "fire_name": ["Snow"],
            "fire_identifier": ["2026-a"],
            "area_acres": [1100.0],
            "area_acres_differential": [1100.0],
            "area_acres_from_geometry": [1110.0],
            "area_acres_from_geometry_differential": [1110.0],
            "observation_time": [datetime.datetime(2026, 9, 3, 1, 0)],
        },
        [tests.factories.square(0.01)],
    )
    perimeter_keys = peri_scribe.fires.identity.group_keys(perimeters)
    metrics, first_mapping = peri_scribe.fires.scores.fire_metrics(
        perimeters,
        perimeter_keys,
    )
    assert metrics.loc["2026-a", "max_area"] == pytest.approx(1100.0)
    assert metrics.loc["2026-a", "max_growth"] == pytest.approx(1100.0)
    assert first_mapping["2026-a"] == pytest.approx(1100.0)
