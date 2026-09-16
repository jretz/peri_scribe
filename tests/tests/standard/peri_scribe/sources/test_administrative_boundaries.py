"""Tests for peri_scribe.sources.administrative_boundaries."""

from __future__ import annotations

import datetime
import pathlib
import typing

import geopandas
import pyproj
import pytest
import shapely.geometry
import structlog
import time_machine

import peri_scribe.exceptions
import peri_scribe.models
import peri_scribe.sources.administrative_boundaries
import tests.helpers.doubles.peri_scribe.snapshot_storage
import tests.helpers.doubles.peri_scribe.sources.administrative_boundaries
import tests.helpers.factories.peri_scribe.sources.administrative_boundaries


def test_output_geopackage_path() -> None:
    path = peri_scribe.sources.administrative_boundaries.output_geopackage_path(
        tests.helpers.factories.peri_scribe.sources.administrative_boundaries.BASE_DIRECTORY,
    )
    assert (
        path
        == (
            tests.helpers.factories.peri_scribe.sources.administrative_boundaries
        ).BASE_DIRECTORY
        / "sources"
        / "CA_border_with_AZ_NV_and_OR.gpkg"
    )


def test_is_usable_false_when_file_missing() -> None:
    assert not peri_scribe.sources.administrative_boundaries.is_usable(
        pathlib.Path("/no/such/file.gpkg"),
    )


def test_is_usable_false_when_file_unreadable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pathlib.Path, "is_file", lambda _self: True)

    fail_to_list = (
        tests.helpers.doubles.peri_scribe.sources.administrative_boundaries
    ).fail_layer_listing

    monkeypatch.setattr(
        peri_scribe.sources.administrative_boundaries.geopandas,
        "list_layers",
        fail_to_list,
    )
    with structlog.testing.capture_logs() as captured:
        usable = peri_scribe.sources.administrative_boundaries.is_usable(
            pathlib.Path("/data/file.gpkg"),
        )
    assert not usable
    assert captured[0]["event"] == "Administrative boundaries file is not usable"


def test_is_usable_false_when_layer_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    tests.helpers.doubles.peri_scribe.sources.administrative_boundaries.stub_geopackage_reads(
        monkeypatch,
        ["Some_Other_Layer"],
        tests.helpers.factories.peri_scribe.sources.administrative_boundaries.good_border_dataframe(),
    )
    assert not peri_scribe.sources.administrative_boundaries.is_usable(
        pathlib.Path("/data/file.gpkg"),
    )


def test_is_usable_false_when_feature_count_wrong(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tests.helpers.doubles.peri_scribe.sources.administrative_boundaries.stub_geopackage_reads(
        monkeypatch,
        [
            tests.helpers.factories.peri_scribe.sources.administrative_boundaries.OUTPUT_LAYER_NAME,
        ],
        tests.helpers.factories.peri_scribe.sources.administrative_boundaries.good_border_dataframe().head(
            2,
        ),
    )
    assert not peri_scribe.sources.administrative_boundaries.is_usable(
        pathlib.Path("/data/file.gpkg"),
    )


def test_is_usable_false_when_columns_wrong(monkeypatch: pytest.MonkeyPatch) -> None:
    tests.helpers.doubles.peri_scribe.sources.administrative_boundaries.stub_geopackage_reads(
        monkeypatch,
        [
            tests.helpers.factories.peri_scribe.sources.administrative_boundaries.OUTPUT_LAYER_NAME,
        ],
        typing.cast(
            "geopandas.GeoDataFrame",
            tests.helpers.factories.peri_scribe.sources.administrative_boundaries.good_border_dataframe().drop(
                columns=["LENGTH_KM"],
            ),
        ),
    )
    assert not peri_scribe.sources.administrative_boundaries.is_usable(
        pathlib.Path("/data/file.gpkg"),
    )


def test_is_usable_false_when_geometry_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    tests.helpers.doubles.peri_scribe.sources.administrative_boundaries.stub_geopackage_reads(
        monkeypatch,
        [
            tests.helpers.factories.peri_scribe.sources.administrative_boundaries.OUTPUT_LAYER_NAME,
        ],
        tests.helpers.factories.peri_scribe.sources.administrative_boundaries.is_usable_dataframe(
            geometry=[None, None, None],
        ),
    )
    assert not peri_scribe.sources.administrative_boundaries.is_usable(
        pathlib.Path("/data/file.gpkg"),
    )


def test_is_usable_false_when_geometry_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    tests.helpers.doubles.peri_scribe.sources.administrative_boundaries.stub_geopackage_reads(
        monkeypatch,
        [
            tests.helpers.factories.peri_scribe.sources.administrative_boundaries.OUTPUT_LAYER_NAME,
        ],
        tests.helpers.factories.peri_scribe.sources.administrative_boundaries.is_usable_dataframe(
            geometry=[
                shapely.geometry.LineString(),
                shapely.geometry.LineString(),
                shapely.geometry.LineString(),
            ],
        ),
    )
    assert not peri_scribe.sources.administrative_boundaries.is_usable(
        pathlib.Path("/data/file.gpkg"),
    )


def test_is_usable_false_when_spatial_reference_wrong(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tests.helpers.doubles.peri_scribe.sources.administrative_boundaries.stub_geopackage_reads(
        monkeypatch,
        [
            tests.helpers.factories.peri_scribe.sources.administrative_boundaries.OUTPUT_LAYER_NAME,
        ],
        tests.helpers.factories.peri_scribe.sources.administrative_boundaries.good_border_dataframe().to_crs(
            3857,
        ),
    )
    assert not peri_scribe.sources.administrative_boundaries.is_usable(
        pathlib.Path("/data/file.gpkg"),
    )


def test_is_usable_false_when_no_spatial_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tests.helpers.doubles.peri_scribe.sources.administrative_boundaries.stub_geopackage_reads(
        monkeypatch,
        [
            tests.helpers.factories.peri_scribe.sources.administrative_boundaries.OUTPUT_LAYER_NAME,
        ],
        tests.helpers.factories.peri_scribe.sources.administrative_boundaries.is_usable_dataframe(
            geometry=[
                shapely.geometry.LineString([(0, 0), (1, 1)]),
                shapely.geometry.LineString([(2, 2), (3, 3)]),
                shapely.geometry.LineString([(4, 4), (5, 5)]),
            ],
            crs=None,
        ),
    )
    assert not peri_scribe.sources.administrative_boundaries.is_usable(
        pathlib.Path("/data/file.gpkg"),
    )


def test_is_usable_true_when_file_good(monkeypatch: pytest.MonkeyPatch) -> None:
    tests.helpers.doubles.peri_scribe.sources.administrative_boundaries.stub_geopackage_reads(
        monkeypatch,
        [
            tests.helpers.factories.peri_scribe.sources.administrative_boundaries.OUTPUT_LAYER_NAME,
        ],
        tests.helpers.factories.peri_scribe.sources.administrative_boundaries.good_border_dataframe(),
    )
    assert peri_scribe.sources.administrative_boundaries.is_usable(
        pathlib.Path("/data/file.gpkg"),
    )


def test_ensure_administrative_boundaries_skips_when_file_usable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_administrative_boundaries = (
        peri_scribe.sources.administrative_boundaries.ensure_administrative_boundaries
    )
    monkeypatch.setattr(
        peri_scribe.sources.administrative_boundaries,
        "is_usable",
        lambda _path: True,
    )
    constructed: list[str] = []
    monkeypatch.setattr(
        peri_scribe.sources.administrative_boundaries.arcgis.features,
        "FeatureLayer",
        lambda url, _gis: constructed.append(url) or object(),
    )
    with structlog.testing.capture_logs() as captured:
        result = ensure_administrative_boundaries(
            tests.helpers.factories.peri_scribe.sources.administrative_boundaries.BASE_DIRECTORY,
        )
    assert result == (
        peri_scribe.sources.administrative_boundaries.output_geopackage_path(
            tests.helpers.factories.peri_scribe.sources.administrative_boundaries.BASE_DIRECTORY,
        )
    )
    assert constructed == []
    assert [event["event"] for event in captured] == [
        "Administrative boundaries already present",
    ]


def test_ensure_administrative_boundaries_builds_when_file_unusable(
    monkeypatch: pytest.MonkeyPatch,
    geo_package_store: (
        tests.helpers.doubles.peri_scribe.snapshot_storage.GeoPackageStore
    ),
) -> None:
    monkeypatch.setattr(
        peri_scribe.sources.administrative_boundaries,
        "is_usable",
        lambda _path: False,
    )
    monkeypatch.setattr(
        peri_scribe.sources.administrative_boundaries.arcgis.gis,
        "GIS",
        object,
    )
    state_set = (
        tests.helpers.factories.peri_scribe.sources.administrative_boundaries
    ).polygon_feature_set(
        [
            tests.helpers.factories.peri_scribe.sources.administrative_boundaries.CALIFORNIA,
            tests.helpers.factories.peri_scribe.sources.administrative_boundaries.ARIZONA,
            tests.helpers.factories.peri_scribe.sources.administrative_boundaries.NEVADA,
            tests.helpers.factories.peri_scribe.sources.administrative_boundaries.OREGON,
        ],
        ["California", "Arizona", "Nevada", "Oregon"],
        ["CA", "AZ", "NV", "OR"],
    )

    layer_factory = (
        tests.helpers.doubles.peri_scribe.sources.administrative_boundaries
    ).make_layer_factory(
        state_set=state_set,
    )

    monkeypatch.setattr(
        peri_scribe.sources.administrative_boundaries.arcgis.features,
        "FeatureLayer",
        layer_factory,
    )
    output_path = peri_scribe.sources.administrative_boundaries.output_geopackage_path(
        tests.helpers.factories.peri_scribe.sources.administrative_boundaries.BASE_DIRECTORY,
    )
    result = (
        peri_scribe.sources.administrative_boundaries
    ).ensure_administrative_boundaries(
        tests.helpers.factories.peri_scribe.sources.administrative_boundaries.BASE_DIRECTORY,
    )
    assert result == output_path
    assert geo_package_store.has(output_path)
    written = geo_package_store.layer(
        output_path,
        tests.helpers.factories.peri_scribe.sources.administrative_boundaries.OUTPUT_LAYER_NAME,
    )
    assert list(written["NEIGHBOR"]) == ["Arizona", "Nevada", "Oregon"]
    assert list(written["NEIGHBOR_ABBR"]) == ["AZ", "NV", "OR"]
    assert list(written.columns) == ["NEIGHBOR", "NEIGHBOR_ABBR", "LENGTH_KM", "geom"]
    assert written.crs.to_epsg() == peri_scribe.models.WGS84_SPATIAL_REFERENCE_ID


def test_ensure_administrative_boundaries_raises_when_fetch_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        peri_scribe.sources.administrative_boundaries,
        "is_usable",
        lambda _path: False,
    )
    monkeypatch.setattr(
        peri_scribe.sources.administrative_boundaries.arcgis.gis,
        "GIS",
        object,
    )
    monkeypatch.setattr(
        peri_scribe.sources.administrative_boundaries.arcgis.features,
        "FeatureLayer",
        lambda _url, _gis: (
            tests.helpers.doubles.peri_scribe.sources.administrative_boundaries.FailingFeatureLayerStub()
        ),
    )
    with pytest.raises(
        peri_scribe.exceptions.AdministrativeBoundariesError,
        match="Failed to build administrative boundaries: boom",
    ):
        peri_scribe.sources.administrative_boundaries.ensure_administrative_boundaries(
            tests.helpers.factories.peri_scribe.sources.administrative_boundaries.BASE_DIRECTORY,
        )


def test_ensure_administrative_boundaries_defaults_to_current_year_directory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_administrative_boundaries = (
        peri_scribe.sources.administrative_boundaries.ensure_administrative_boundaries
    )
    monkeypatch.setattr(
        peri_scribe.sources.administrative_boundaries,
        "is_usable",
        lambda _path: True,
    )
    monkeypatch.setattr(
        pathlib.Path,
        "cwd",
        staticmethod(
            lambda: (
                tests.helpers.factories.peri_scribe.sources.administrative_boundaries.BASE_DIRECTORY
            ),
        ),
    )
    with time_machine.travel(datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)):
        result = ensure_administrative_boundaries()
    assert (
        result
        == peri_scribe.sources.administrative_boundaries.output_geopackage_path(
            tests.helpers.factories.peri_scribe.sources.administrative_boundaries.BASE_DIRECTORY
            / "data"
            / "2026",
        )
    )


def test_load_border_geometry_returns_stored_lines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tests.helpers.doubles.peri_scribe.sources.administrative_boundaries.stub_border_file(
        monkeypatch,
        tests.helpers.factories.peri_scribe.sources.administrative_boundaries.good_border_dataframe(),
    )
    result = peri_scribe.sources.administrative_boundaries.load_border_geometry(
        tests.helpers.factories.peri_scribe.sources.administrative_boundaries.BASE_DIRECTORY,
    )
    assert isinstance(result, shapely.geometry.MultiLineString)


def test_load_border_geometry_returns_single_line_when_one_part(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    single = geopandas.GeoDataFrame(
        {"NEIGHBOR": ["Oregon"], "NEIGHBOR_ABBR": ["OR"], "LENGTH_KM": [10.0]},
        geometry=[shapely.geometry.LineString([(0.0, 0.0), (10.0, 0.0)])],
        crs=pyproj.CRS.from_epsg(4326),
    )
    tests.helpers.doubles.peri_scribe.sources.administrative_boundaries.stub_border_file(
        monkeypatch,
        single,
    )
    result = peri_scribe.sources.administrative_boundaries.load_border_geometry(
        tests.helpers.factories.peri_scribe.sources.administrative_boundaries.BASE_DIRECTORY,
    )
    assert isinstance(result, shapely.geometry.LineString)
