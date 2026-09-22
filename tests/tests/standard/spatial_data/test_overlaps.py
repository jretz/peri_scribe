"""Tests for spatial_data.overlaps."""

from __future__ import annotations

import pathlib
import typing

import geopandas
import shapely.geometry

import spatial_data.overlaps
import tests.helpers.factories.geography
import tests.helpers.factories.geometry


if typing.TYPE_CHECKING:
    import pytest


def test_overlapping_layer_indices_detects_overlap(tmp_path: pathlib.Path) -> None:
    zones = tests.helpers.factories.geography.geo_frame(
        {"name": ["zone", "far"]},
        [
            tests.helpers.factories.geometry.square(2.0),
            shapely.geometry.box(100.0, 100.0, 101.0, 101.0),
        ],
    )
    path = tmp_path / "zones.gpkg"
    zones.to_file(path, layer="zones")

    indices = spatial_data.overlaps.overlapping_layer_indices(
        [
            tests.helpers.factories.geometry.square(1.0),
            shapely.geometry.box(50.0, 50.0, 51.0, 51.0),
        ],
        path,
        "zones",
        chunk_size=1,
    )

    assert indices == {0}


def test_overlapping_layer_indices_reprojects_to_layer_crs(
    tmp_path: pathlib.Path,
) -> None:
    zones = geopandas.GeoDataFrame(
        {"name": ["zone"]},
        geometry=[tests.helpers.factories.geometry.point(0, 0)],
        crs="EPSG:3857",
    )
    path = tmp_path / "zones.gpkg"
    zones.to_file(path, layer="zones")

    indices = spatial_data.overlaps.overlapping_layer_indices(
        [tests.helpers.factories.geometry.point(0, 0)],
        path,
        "zones",
    )

    assert indices == {0}


def test_overlapping_layer_indices_returns_empty_without_geometry() -> None:
    assert (
        spatial_data.overlaps.overlapping_layer_indices(
            [None],
            pathlib.Path("/unused.gpkg"),
            "zones",
        )
        == set()
    )


def test_overlapping_layer_indices_reads_z_geometries(tmp_path: pathlib.Path) -> None:
    zones = tests.helpers.factories.geography.geo_frame(
        {"name": ["zone"]},
        [
            shapely.geometry.Polygon([
                (0, 0, 0),
                (2, 0, 0),
                (2, 2, 0),
                (0, 2, 0),
                (0, 0, 0),
            ]),
        ],
    )
    path = tmp_path / "zones.gpkg"
    zones.to_file(path, layer="zones")

    indices = spatial_data.overlaps.overlapping_layer_indices(
        [tests.helpers.factories.geometry.square(1.0)],
        path,
        "zones",
    )

    assert indices == {0}


def test_overlapping_layer_indices_returns_empty_when_no_feature_overlaps(
    tmp_path: pathlib.Path,
) -> None:
    zones = tests.helpers.factories.geography.geo_frame(
        {"name": ["far"]},
        [shapely.geometry.box(100.0, 100.0, 101.0, 101.0)],
    )
    path = tmp_path / "zones.gpkg"
    zones.to_file(path, layer="zones")

    indices = spatial_data.overlaps.overlapping_layer_indices(
        [tests.helpers.factories.geometry.square(1.0)],
        path,
        "zones",
    )

    assert indices == set()


def test_overlapping_layer_indices_streams_without_rtree(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    zones = tests.helpers.factories.geography.geo_frame(
        {"name": ["zone", "far"]},
        [
            tests.helpers.factories.geometry.square(2.0),
            shapely.geometry.box(100.0, 100.0, 101.0, 101.0),
        ],
    )
    path = tmp_path / "zones.gpkg"
    zones.to_file(path, layer="zones")
    monkeypatch.setattr(
        spatial_data.overlaps,
        "has_rtree",
        lambda _path, _layer: False,
    )

    indices = spatial_data.overlaps.overlapping_layer_indices(
        [
            tests.helpers.factories.geometry.square(1.0),
            shapely.geometry.box(50.0, 50.0, 51.0, 51.0),
        ],
        path,
        "zones",
        chunk_size=1,
    )

    assert indices == {0}
