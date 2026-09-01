"""Tests for peri_scribe.fires.overlaps."""

from __future__ import annotations

import pathlib
import typing

import geopandas
import shapely.geometry

import peri_scribe.fires.overlaps
import tests.peri_scribe.fires.fire_helpers


if typing.TYPE_CHECKING:
    import pytest


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
