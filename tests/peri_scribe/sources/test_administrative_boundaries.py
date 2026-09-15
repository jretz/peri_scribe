"""Tests for peri_scribe.sources.administrative_boundaries."""

from __future__ import annotations

import datetime
import pathlib
import typing

import arcgis.features
import geopandas
import pyproj
import pytest
import shapely.geometry
import structlog
import time_machine

import peri_scribe.exceptions
import peri_scribe.models
import peri_scribe.sources.administrative_boundaries
import peri_scribe.sources.borders
import tests.peri_scribe.sources.boundary_helpers


if typing.TYPE_CHECKING:
    from tests.factories import GeoPackageStore


def test_output_geopackage_path() -> None:
    path = peri_scribe.sources.administrative_boundaries.output_geopackage_path(
        tests.peri_scribe.sources.boundary_helpers.BASE_DIRECTORY,
    )
    assert (
        path
        == tests.peri_scribe.sources.boundary_helpers.BASE_DIRECTORY
        / "sources"
        / "CA_border_with_AZ_NV_and_OR.gpkg"
    )


def test_line_parts_returns_lines_from_collection() -> None:
    collection = shapely.geometry.GeometryCollection([
        shapely.geometry.LineString([(0, 0), (1, 1)]),
        shapely.geometry.Point(2, 2),
    ])
    parts = peri_scribe.sources.borders.line_parts(collection)
    assert len(parts) == 1
    assert parts[0].equals(shapely.geometry.LineString([(0, 0), (1, 1)]))


def test_line_parts_returns_empty_for_point() -> None:
    assert peri_scribe.sources.borders.line_parts(shapely.geometry.Point(0, 0)) == []


def test_shared_border_returns_shared_edge() -> None:
    border = peri_scribe.sources.borders.shared_border(
        tests.peri_scribe.sources.boundary_helpers.CALIFORNIA,
        tests.peri_scribe.sources.boundary_helpers.ARIZONA,
    )
    assert border.geom_type == "LineString"
    assert border.length == pytest.approx(10.0, abs=1e-3)
    assert {border.coords[0][1], border.coords[-1][1]} == {0.0, 10.0}


def test_shared_border_accepts_slightly_misaligned_neighbor() -> None:
    neighbor = shapely.geometry.Polygon([
        (10.000005, 0),
        (10.000005, 10),
        (20, 10),
        (20, 0),
    ])
    border = peri_scribe.sources.borders.shared_border(
        tests.peri_scribe.sources.boundary_helpers.CALIFORNIA,
        neighbor,
    )
    assert not border.is_empty
    assert peri_scribe.sources.borders.total_line_length(border).m_as(
        "degree",
    ) == pytest.approx(10.0, abs=1e-3)


def test_shared_border_returns_multi_line_string_for_multiple_segments() -> None:
    neighbor = shapely.geometry.MultiPolygon([
        tests.peri_scribe.sources.boundary_helpers.ARIZONA,
        tests.peri_scribe.sources.boundary_helpers.OREGON,
    ])
    border = peri_scribe.sources.borders.shared_border(
        tests.peri_scribe.sources.boundary_helpers.CALIFORNIA,
        neighbor,
    )
    assert border.geom_type == "MultiLineString"
    assert len(border.geoms) > 1
    assert peri_scribe.sources.borders.total_line_length(border).m_as(
        "degree",
    ) == pytest.approx(20.0, abs=1e-2)


def test_shared_border_raises_when_geometries_share_no_border() -> None:
    distant = shapely.geometry.Polygon([(50, 50), (50, 60), (60, 60), (60, 50)])
    with pytest.raises(
        peri_scribe.exceptions.AdministrativeBoundariesError,
        match="share no border",
    ):
        peri_scribe.sources.borders.shared_border(
            tests.peri_scribe.sources.boundary_helpers.CALIFORNIA,
            distant,
        )


def test_border_length() -> None:
    line = shapely.geometry.LineString([(0, 0), (1, 0)])
    length = peri_scribe.sources.borders.border_length(line)
    assert length.m_as("kilometers") == pytest.approx(111.319, rel=1e-4)


def test_border_length_sums_line_parts() -> None:
    multi_line = shapely.geometry.MultiLineString([
        shapely.geometry.LineString([(0, 0), (1, 0)]),
        shapely.geometry.LineString([(1, 0), (2, 0)]),
    ])
    length = peri_scribe.sources.borders.border_length(multi_line)
    assert length.m_as("kilometers") == pytest.approx(222.638, rel=1e-4)


def test_border_dataframe_builds_neighbor_rows() -> None:
    neighbor_states = peri_scribe.sources.borders.NEIGHBOR_STATES
    neighbor_state_names = [state.name for state in neighbor_states]
    neighbor_state_abbreviations = [state.abbr for state in neighbor_states]
    neighbors = geopandas.GeoDataFrame(
        {
            "STATE_NAME": neighbor_state_names,
            "STATE_ABBR": neighbor_state_abbreviations,
        },
        geometry=[
            tests.peri_scribe.sources.boundary_helpers.ARIZONA,
            tests.peri_scribe.sources.boundary_helpers.NEVADA,
            tests.peri_scribe.sources.boundary_helpers.OREGON,
        ],
        crs=pyproj.CRS.from_epsg(4326),
    )
    border = peri_scribe.sources.borders.border_dataframe(
        tests.peri_scribe.sources.boundary_helpers.CALIFORNIA,
        neighbors,
    )
    assert list(border["NEIGHBOR"]) == neighbor_state_names
    assert list(border["NEIGHBOR_ABBR"]) == neighbor_state_abbreviations
    assert border.geometry.name == "geom"
    assert border.crs.to_epsg() == peri_scribe.models.WGS84_SPATIAL_REFERENCE_ID
    assert all(border["LENGTH_KM"] > 0)


def test_layer_dataframe_queries_features_in_wgs84() -> None:
    feature_set = tests.peri_scribe.sources.boundary_helpers.polygon_feature_set(
        [tests.peri_scribe.sources.boundary_helpers.ARIZONA],
        ["Arizona"],
        ["AZ"],
    )
    layer = tests.peri_scribe.sources.boundary_helpers.FeatureLayerStub(feature_set)
    dataframe = peri_scribe.sources.borders.layer_dataframe(
        tests.peri_scribe.sources.boundary_helpers.as_feature_layer(layer),
        "Neighboring states",
        where="STATE_ABBR IN ('AZ','NV','OR')",
    )
    assert len(dataframe) == 1
    assert dataframe.crs.to_epsg() == peri_scribe.models.WGS84_SPATIAL_REFERENCE_ID
    assert dataframe.geometry.name == "geom"
    assert layer.queries == [
        {
            "where": "STATE_ABBR IN ('AZ','NV','OR')",
            "out_sr": 4326,
            "order_by_fields": "OBJECTID",
        },
    ]


def test_layer_dataframe_raises_when_layer_has_no_features() -> None:
    layer = tests.peri_scribe.sources.boundary_helpers.FeatureLayerStub(
        arcgis.features.FeatureSet([]),
    )
    with pytest.raises(
        peri_scribe.exceptions.AdministrativeBoundariesError,
        match="returned no features",
    ):
        peri_scribe.sources.borders.layer_dataframe(
            tests.peri_scribe.sources.boundary_helpers.as_feature_layer(layer),
            "California",
            where="STATE_ABBR='CA'",
        )


def test_layer_dataframe_logs_warning_when_geometry_missing() -> None:
    layer = tests.peri_scribe.sources.boundary_helpers.FeatureLayerStub(
        tests.peri_scribe.sources.boundary_helpers.GeometrylessFeatureSetStub(1),
    )
    with structlog.testing.capture_logs() as captured:
        dataframe = peri_scribe.sources.borders.layer_dataframe(
            tests.peri_scribe.sources.boundary_helpers.as_feature_layer(layer),
            "California",
            where="STATE_ABBR='CA'",
        )
    assert len(dataframe) == 1
    assert dataframe.geometry.iloc[0] is None
    assert captured[0]["event"] == (
        "  warning: all features lack geometry; writing the layer with NULL geometry"
    )


def test_boundary_geometries_queries_california_and_neighbors_once() -> None:
    layer = tests.peri_scribe.sources.boundary_helpers.FeatureLayerStub(
        tests.peri_scribe.sources.boundary_helpers.polygon_feature_set(
            [
                tests.peri_scribe.sources.boundary_helpers.CALIFORNIA,
                tests.peri_scribe.sources.boundary_helpers.ARIZONA,
                tests.peri_scribe.sources.boundary_helpers.NEVADA,
                tests.peri_scribe.sources.boundary_helpers.OREGON,
            ],
            ["California", "Arizona", "Nevada", "Oregon"],
            ["CA", "AZ", "NV", "OR"],
        ),
    )
    states = peri_scribe.sources.borders.boundary_geometries(
        tests.peri_scribe.sources.boundary_helpers.as_feature_layer(layer),
    )
    assert list(states["STATE_ABBR"]) == ["CA", "AZ", "NV", "OR"]
    assert layer.queries == [
        {
            "where": "STATE_ABBR IN ('CA','AZ','NV','OR')",
            "out_sr": 4326,
            "order_by_fields": "OBJECTID",
        },
    ]


def test_boundary_geometries_raises_when_state_missing() -> None:
    layer = tests.peri_scribe.sources.boundary_helpers.FeatureLayerStub(
        tests.peri_scribe.sources.boundary_helpers.polygon_feature_set(
            [
                tests.peri_scribe.sources.boundary_helpers.CALIFORNIA,
                tests.peri_scribe.sources.boundary_helpers.ARIZONA,
                tests.peri_scribe.sources.boundary_helpers.NEVADA,
            ],
            ["California", "Arizona", "Nevada"],
            ["CA", "AZ", "NV"],
        ),
    )
    with pytest.raises(
        peri_scribe.exceptions.AdministrativeBoundariesError,
        match="Expected California and 3 neighboring states, got 3",
    ):
        peri_scribe.sources.borders.boundary_geometries(
            tests.peri_scribe.sources.boundary_helpers.as_feature_layer(layer),
        )


def test_boundary_geometries_raises_when_geometry_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    states = geopandas.GeoDataFrame(
        {"STATE_ABBR": ["CA", "AZ", "NV", "OR"]},
        geometry=[
            tests.peri_scribe.sources.boundary_helpers.CALIFORNIA,
            tests.peri_scribe.sources.boundary_helpers.ARIZONA,
            tests.peri_scribe.sources.boundary_helpers.NEVADA,
            None,
        ],
        crs=pyproj.CRS.from_epsg(4326),
    )
    monkeypatch.setattr(
        peri_scribe.sources.borders,
        "layer_dataframe",
        lambda *_args, **_kwargs: states,
    )
    with pytest.raises(
        peri_scribe.exceptions.AdministrativeBoundariesError,
        match="border state feature has no geometry",
    ):
        peri_scribe.sources.borders.boundary_geometries(
            tests.peri_scribe.sources.boundary_helpers.as_feature_layer(object()),
        )


def test_california_geometry_from_states_raises_when_missing() -> None:
    states = geopandas.GeoDataFrame(
        {"STATE_ABBR": ["AZ", "NV", "OR"]},
        geometry=[
            tests.peri_scribe.sources.boundary_helpers.ARIZONA,
            tests.peri_scribe.sources.boundary_helpers.NEVADA,
            tests.peri_scribe.sources.boundary_helpers.OREGON,
        ],
        crs=pyproj.CRS.from_epsg(4326),
    )
    with pytest.raises(
        peri_scribe.exceptions.AdministrativeBoundariesError,
        match="Expected one California feature, got 0",
    ):
        peri_scribe.sources.borders.california_geometry_from_states(states)


def test_is_usable_false_when_file_missing() -> None:
    assert not peri_scribe.sources.administrative_boundaries.is_usable(
        pathlib.Path("/no/such/file.gpkg"),
    )


def test_is_usable_false_when_file_unreadable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pathlib.Path, "is_file", lambda _self: True)

    fail_to_list = tests.peri_scribe.sources.boundary_helpers.fail_layer_listing

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
    tests.peri_scribe.sources.boundary_helpers.stub_geopackage_reads(
        monkeypatch,
        ["Some_Other_Layer"],
        tests.peri_scribe.sources.boundary_helpers.good_border_dataframe(),
    )
    assert not peri_scribe.sources.administrative_boundaries.is_usable(
        pathlib.Path("/data/file.gpkg"),
    )


def test_is_usable_false_when_feature_count_wrong(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tests.peri_scribe.sources.boundary_helpers.stub_geopackage_reads(
        monkeypatch,
        [tests.peri_scribe.sources.boundary_helpers.OUTPUT_LAYER_NAME],
        tests.peri_scribe.sources.boundary_helpers.good_border_dataframe().head(2),
    )
    assert not peri_scribe.sources.administrative_boundaries.is_usable(
        pathlib.Path("/data/file.gpkg"),
    )


def test_is_usable_false_when_columns_wrong(monkeypatch: pytest.MonkeyPatch) -> None:
    tests.peri_scribe.sources.boundary_helpers.stub_geopackage_reads(
        monkeypatch,
        [tests.peri_scribe.sources.boundary_helpers.OUTPUT_LAYER_NAME],
        typing.cast(
            "geopandas.GeoDataFrame",
            tests.peri_scribe.sources.boundary_helpers.good_border_dataframe().drop(
                columns=["LENGTH_KM"],
            ),
        ),
    )
    assert not peri_scribe.sources.administrative_boundaries.is_usable(
        pathlib.Path("/data/file.gpkg"),
    )


def test_is_usable_false_when_geometry_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    tests.peri_scribe.sources.boundary_helpers.stub_geopackage_reads(
        monkeypatch,
        [tests.peri_scribe.sources.boundary_helpers.OUTPUT_LAYER_NAME],
        tests.peri_scribe.sources.boundary_helpers.is_usable_dataframe(
            geometry=[None, None, None],
        ),
    )
    assert not peri_scribe.sources.administrative_boundaries.is_usable(
        pathlib.Path("/data/file.gpkg"),
    )


def test_is_usable_false_when_geometry_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    tests.peri_scribe.sources.boundary_helpers.stub_geopackage_reads(
        monkeypatch,
        [tests.peri_scribe.sources.boundary_helpers.OUTPUT_LAYER_NAME],
        tests.peri_scribe.sources.boundary_helpers.is_usable_dataframe(
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
    tests.peri_scribe.sources.boundary_helpers.stub_geopackage_reads(
        monkeypatch,
        [tests.peri_scribe.sources.boundary_helpers.OUTPUT_LAYER_NAME],
        tests.peri_scribe.sources.boundary_helpers.good_border_dataframe().to_crs(3857),
    )
    assert not peri_scribe.sources.administrative_boundaries.is_usable(
        pathlib.Path("/data/file.gpkg"),
    )


def test_is_usable_false_when_no_spatial_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tests.peri_scribe.sources.boundary_helpers.stub_geopackage_reads(
        monkeypatch,
        [tests.peri_scribe.sources.boundary_helpers.OUTPUT_LAYER_NAME],
        tests.peri_scribe.sources.boundary_helpers.is_usable_dataframe(
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
    tests.peri_scribe.sources.boundary_helpers.stub_geopackage_reads(
        monkeypatch,
        [tests.peri_scribe.sources.boundary_helpers.OUTPUT_LAYER_NAME],
        tests.peri_scribe.sources.boundary_helpers.good_border_dataframe(),
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
            tests.peri_scribe.sources.boundary_helpers.BASE_DIRECTORY,
        )
    assert result == (
        peri_scribe.sources.administrative_boundaries.output_geopackage_path(
            tests.peri_scribe.sources.boundary_helpers.BASE_DIRECTORY,
        )
    )
    assert constructed == []
    assert [event["event"] for event in captured] == [
        "Administrative boundaries already present",
    ]


def test_ensure_administrative_boundaries_builds_when_file_unusable(
    monkeypatch: pytest.MonkeyPatch,
    geo_package_store: GeoPackageStore,
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
    state_set = tests.peri_scribe.sources.boundary_helpers.polygon_feature_set(
        [
            tests.peri_scribe.sources.boundary_helpers.CALIFORNIA,
            tests.peri_scribe.sources.boundary_helpers.ARIZONA,
            tests.peri_scribe.sources.boundary_helpers.NEVADA,
            tests.peri_scribe.sources.boundary_helpers.OREGON,
        ],
        ["California", "Arizona", "Nevada", "Oregon"],
        ["CA", "AZ", "NV", "OR"],
    )

    layer_factory = tests.peri_scribe.sources.boundary_helpers.make_layer_factory(
        state_set=state_set,
    )

    monkeypatch.setattr(
        peri_scribe.sources.administrative_boundaries.arcgis.features,
        "FeatureLayer",
        layer_factory,
    )
    output_path = peri_scribe.sources.administrative_boundaries.output_geopackage_path(
        tests.peri_scribe.sources.boundary_helpers.BASE_DIRECTORY,
    )
    result = (
        peri_scribe.sources.administrative_boundaries.ensure_administrative_boundaries(
            tests.peri_scribe.sources.boundary_helpers.BASE_DIRECTORY,
        )
    )
    assert result == output_path
    assert geo_package_store.has(output_path)
    written = geo_package_store.layer(
        output_path,
        tests.peri_scribe.sources.boundary_helpers.OUTPUT_LAYER_NAME,
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
            tests.peri_scribe.sources.boundary_helpers.FailingFeatureLayerStub()
        ),
    )
    with pytest.raises(
        peri_scribe.exceptions.AdministrativeBoundariesError,
        match="Failed to build administrative boundaries: boom",
    ):
        peri_scribe.sources.administrative_boundaries.ensure_administrative_boundaries(
            tests.peri_scribe.sources.boundary_helpers.BASE_DIRECTORY,
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
        staticmethod(lambda: tests.peri_scribe.sources.boundary_helpers.BASE_DIRECTORY),
    )
    with time_machine.travel(datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)):
        result = ensure_administrative_boundaries()
    assert (
        result
        == peri_scribe.sources.administrative_boundaries.output_geopackage_path(
            tests.peri_scribe.sources.boundary_helpers.BASE_DIRECTORY / "data" / "2026",
        )
    )


def test_load_border_geometry_returns_stored_lines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tests.peri_scribe.sources.boundary_helpers.stub_border_file(
        monkeypatch,
        tests.peri_scribe.sources.boundary_helpers.good_border_dataframe(),
    )
    result = peri_scribe.sources.administrative_boundaries.load_border_geometry(
        tests.peri_scribe.sources.boundary_helpers.BASE_DIRECTORY,
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
    tests.peri_scribe.sources.boundary_helpers.stub_border_file(monkeypatch, single)
    result = peri_scribe.sources.administrative_boundaries.load_border_geometry(
        tests.peri_scribe.sources.boundary_helpers.BASE_DIRECTORY,
    )
    assert isinstance(result, shapely.geometry.LineString)


def test_ordered_border_coordinates_orders_single_path() -> None:
    parts = [shapely.geometry.LineString([(0.0, 10.0), (5.0, 10.0), (10.0, 5.0)])]
    assert peri_scribe.sources.borders.ordered_border_coordinates(parts) == [
        (0.0, 10.0),
        (5.0, 10.0),
        (10.0, 5.0),
    ]


def test_ordered_border_coordinates_orders_multiple_parts() -> None:
    parts = [
        shapely.geometry.LineString([(0.0, 10.0), (5.0, 10.0)]),
        shapely.geometry.LineString([(5.0, 10.0), (10.0, 5.0)]),
    ]
    assert peri_scribe.sources.borders.ordered_border_coordinates(parts) == [
        (0.0, 10.0),
        (5.0, 10.0),
        (10.0, 5.0),
    ]


def test_ordered_border_coordinates_bridges_small_gaps() -> None:
    parts = [
        shapely.geometry.LineString([(0.0, 10.0), (5.0, 10.0)]),
        shapely.geometry.LineString([(5.00001, 10.0), (10.0, 5.0)]),
    ]
    assert peri_scribe.sources.borders.ordered_border_coordinates(parts) == [
        (0.0, 10.0),
        (5.0, 10.0),
        (10.0, 5.0),
    ]


def test_ordered_border_coordinates_raises_when_no_segments() -> None:
    with pytest.raises(
        peri_scribe.exceptions.AdministrativeBoundariesError,
        match="no line segments",
    ):
        peri_scribe.sources.borders.ordered_border_coordinates([])


def test_ordered_border_coordinates_raises_when_not_a_single_path() -> None:
    parts = [
        shapely.geometry.LineString([(0.0, 0.0), (1.0, 0.0)]),
        shapely.geometry.LineString([(10.0, 0.0), (11.0, 0.0)]),
    ]
    with pytest.raises(
        peri_scribe.exceptions.AdministrativeBoundariesError,
        match="not a single continuous path",
    ):
        peri_scribe.sources.borders.ordered_border_coordinates(parts)


def test_california_box_polygon_contains_california() -> None:
    box = peri_scribe.sources.borders.california_box_polygon(
        tests.peri_scribe.sources.boundary_helpers.california_like_border(),
    )
    assert box.is_valid
    assert box.contains(shapely.geometry.Point(-120.0, 40.0))
    assert box.contains(shapely.geometry.Point(-123.0, 34.0))


def test_california_box_polygon_excludes_neighboring_states() -> None:
    box = peri_scribe.sources.borders.california_box_polygon(
        tests.peri_scribe.sources.boundary_helpers.california_like_border(),
    )
    assert not box.contains(shapely.geometry.Point(-117.0, 40.0))
    assert not box.contains(shapely.geometry.Point(-120.0, 43.0))


def test_california_box_polygon_absorbs_maritime_and_mexico() -> None:
    box = peri_scribe.sources.borders.california_box_polygon(
        tests.peri_scribe.sources.boundary_helpers.california_like_border(),
    )
    assert box.contains(shapely.geometry.Point(-116.0, 32.3))
    assert not box.contains(shapely.geometry.Point(-116.0, 30.0))
    assert not box.contains(shapely.geometry.Point(-127.0, 38.0))
