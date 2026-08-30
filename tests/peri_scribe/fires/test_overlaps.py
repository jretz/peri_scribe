"""Tests for peri_scribe.fires.scores."""

from __future__ import annotations

import pathlib
import typing

import geopandas
import shapely.geometry

import peri_scribe.fires.buffering
import peri_scribe.fires.overlaps
import tests.peri_scribe.fires.fire_helpers


if typing.TYPE_CHECKING:
    import pytest


def test_building_counts_within_counts_points_across_chunks(
    tmp_path: pathlib.Path,
) -> None:
    buffered = peri_scribe.fires.buffering.buffered_fire_geometries(
        [
            tests.peri_scribe.fires.fire_helpers.square(1.0),
            tests.peri_scribe.fires.fire_helpers.square(0.1),
        ],
    )
    buildings = geopandas.GeoDataFrame(
        {"name": ["a"] * 6},
        geometry=[tests.peri_scribe.fires.fire_helpers.point(0, 0)] * 3
        + [
            tests.peri_scribe.fires.fire_helpers.point(50, 50),
            tests.peri_scribe.fires.fire_helpers.point(60, 60),
            tests.peri_scribe.fires.fire_helpers.point(70, 70),
        ],
        crs="EPSG:4326",
    )
    path = tmp_path / "buildings.gpkg"
    buildings.to_file(path, layer="buildings")

    counts = peri_scribe.fires.overlaps.building_counts_within(
        buffered,
        path,
        "buildings",
        chunk_size=2,
    )

    assert counts == [3, 3]


def test_building_counts_within_returns_zero_without_geometry() -> None:
    counts = peri_scribe.fires.overlaps.building_counts_within(
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
            tests.peri_scribe.fires.fire_helpers.square(2.0),
            shapely.geometry.box(100.0, 100.0, 101.0, 101.0),
        ],
        crs="EPSG:4326",
    )
    path = tmp_path / "zones.gpkg"
    zones.to_file(path, layer="zones")

    indices = peri_scribe.fires.overlaps.overlapping_fire_indices(
        [
            tests.peri_scribe.fires.fire_helpers.square(1.0),
            shapely.geometry.box(50.0, 50.0, 51.0, 51.0),
        ],
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
        geometry=[tests.peri_scribe.fires.fire_helpers.point(0, 0)],
        crs="EPSG:3857",
    )
    path = tmp_path / "zones.gpkg"
    zones.to_file(path, layer="zones")

    indices = peri_scribe.fires.overlaps.overlapping_fire_indices(
        [tests.peri_scribe.fires.fire_helpers.point(0, 0)],
        path,
        "zones",
    )

    assert indices == {0}


def test_overlapping_fire_indices_returns_empty_without_geometry() -> None:
    assert (
        peri_scribe.fires.overlaps.overlapping_fire_indices(
            [None],
            pathlib.Path("/unused.gpkg"),
            "zones",
        )
        == set()
    )


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

    indices = peri_scribe.fires.overlaps.overlapping_fire_indices(
        [tests.peri_scribe.fires.fire_helpers.square(1.0)],
        path,
        "zones",
    )

    assert indices == {0}


def test_building_counts_within_streams_without_rtree(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    buffered = peri_scribe.fires.buffering.buffered_fire_geometries(
        [
            tests.peri_scribe.fires.fire_helpers.square(1.0),
            tests.peri_scribe.fires.fire_helpers.square(0.1),
        ],
    )
    buildings = geopandas.GeoDataFrame(
        {"name": ["a"] * 5},
        geometry=[tests.peri_scribe.fires.fire_helpers.point(0, 0)] * 3
        + [
            tests.peri_scribe.fires.fire_helpers.point(50, 50),
            tests.peri_scribe.fires.fire_helpers.point(60, 60),
        ],
        crs="EPSG:4326",
    )
    path = tmp_path / "buildings.gpkg"
    buildings.to_file(path, layer="buildings")
    monkeypatch.setattr(
        peri_scribe.fires.overlaps,
        "has_rtree",
        lambda _path, _layer: False,
    )

    counts = peri_scribe.fires.overlaps.building_counts_within(
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

    indices = peri_scribe.fires.overlaps.overlapping_fire_indices(
        [tests.peri_scribe.fires.fire_helpers.square(1.0)],
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
            tests.peri_scribe.fires.fire_helpers.square(2.0),
            shapely.geometry.box(100.0, 100.0, 101.0, 101.0),
        ],
        crs="EPSG:4326",
    )
    path = tmp_path / "zones.gpkg"
    zones.to_file(path, layer="zones")
    monkeypatch.setattr(
        peri_scribe.fires.overlaps,
        "has_rtree",
        lambda _path, _layer: False,
    )

    indices = peri_scribe.fires.overlaps.overlapping_fire_indices(
        [
            tests.peri_scribe.fires.fire_helpers.square(1.0),
            shapely.geometry.box(50.0, 50.0, 51.0, 51.0),
        ],
        path,
        "zones",
        chunk_size=1,
    )

    assert indices == {0}
