"""Tests for peri_scribe.administrative_boundaries."""

from __future__ import annotations

import pathlib
import typing

import arcgis.features
import geopandas
import pandas as pd
import pyproj
import pytest
import shapely.geometry
import structlog

import peri_scribe.administrative_boundaries
import peri_scribe.exceptions
import peri_scribe.models


if typing.TYPE_CHECKING:
    from tests.conftest import GeoPackageStore


CALIFORNIA = shapely.geometry.Polygon([(0, 0), (0, 10), (10, 10), (10, 0)])
ARIZONA = shapely.geometry.Polygon([(10, 0), (10, 10), (20, 10), (20, 0)])
NEVADA = shapely.geometry.Polygon([(0, 10), (0, 20), (10, 20), (10, 10)])
OREGON = shapely.geometry.Polygon([(-10, 0), (-10, 10), (0, 10), (0, 0)])

BASE_DIRECTORY = pathlib.Path("/boundaries")

OUTPUT_LAYER_NAME = peri_scribe.administrative_boundaries.OUTPUT_LAYER_NAME


class FeatureLayerStub:
    """Minimal stand-in for an ArcGIS FeatureLayer with a fixed query result."""

    def __init__(self, feature_set: object) -> None:
        self.feature_set = feature_set
        self.queries: list[dict[str, object]] = []

    def query(self, **parameters: object) -> object:
        self.queries.append(parameters)
        return self.feature_set


class FailingFeatureLayerStub:
    """FeatureLayer stand-in whose query always raises."""

    @staticmethod
    def query(**_parameters: object) -> object:
        message = "boom"
        raise RuntimeError(message)


class GeometrylessFeatureSetStub:
    """FeatureSet stand-in whose dataframe carries no geometry column."""

    def __init__(self, count: int) -> None:
        self.features = [object()] * count
        self.sdf = pd.DataFrame(
            {"STATE_NAME": [f"State {index}" for index in range(count)]},
        )


def as_feature_layer(stub: object) -> arcgis.features.FeatureLayer:
    """Type *stub* as an ArcGIS FeatureLayer for the functions under test.

    Returns:
        The stub, statically typed as a FeatureLayer.
    """
    return typing.cast("arcgis.features.FeatureLayer", stub)


def polygon_feature_set(
    polygons: list[shapely.Polygon],
    names: list[str],
    abbreviations: list[str],
) -> arcgis.features.FeatureSet:
    """Build an ArcGIS FeatureSet from polygon geometries in WGS84.

    Returns:
        A FeatureSet whose features carry the named polygons in WGS84.
    """
    features = []
    for polygon, name, abbreviation in zip(
        polygons,
        names,
        abbreviations,
        strict=True,
    ):
        rings = [[list(coordinate) for coordinate in polygon.exterior.coords]]
        features.append(
            arcgis.features.Feature(
                geometry={
                    "rings": rings,
                    "spatialReference": {"wkid": 4326},
                },
                attributes={"STATE_NAME": name, "STATE_ABBR": abbreviation},
            ),
        )
    return arcgis.features.FeatureSet(features)


def good_border_dataframe() -> geopandas.GeoDataFrame:
    """Return the border GeoDataFrame for the sample neighboring states.

    Returns:
        The three shared borders in WGS84 with the expected columns.
    """
    neighbors = geopandas.GeoDataFrame(
        {
            "STATE_NAME": ["Arizona", "Nevada", "Oregon"],
            "STATE_ABBR": ["AZ", "NV", "OR"],
        },
        geometry=[ARIZONA, NEVADA, OREGON],
        crs=pyproj.CRS.from_epsg(4326),
    )
    return peri_scribe.administrative_boundaries.border_dataframe(
        CALIFORNIA,
        neighbors,
    )


def stub_geopackage_reads(
    monkeypatch: pytest.MonkeyPatch,
    layer_names: list[str],
    dataframe: geopandas.GeoDataFrame,
) -> None:
    """Point the module's GeoPackage reads at in-memory stand-ins."""
    monkeypatch.setattr(pathlib.Path, "is_file", lambda _self: True)
    monkeypatch.setattr(
        peri_scribe.administrative_boundaries.geopandas,
        "list_layers",
        lambda _path: pd.DataFrame({"name": layer_names}),
    )
    monkeypatch.setattr(
        peri_scribe.administrative_boundaries.geopandas,
        "read_file",
        lambda _path, **_keywords: dataframe,
    )


def is_usable_dataframe(
    *,
    geometry: list[shapely.Geometry | None],
    crs: object | None = pyproj.CRS.from_epsg(4326),
) -> geopandas.GeoDataFrame:
    """Build a candidate border dataframe for the is_usable checks.

    Args:
        geometry: The border line geometries.
        crs: The dataframe's CRS, or None to omit it.

    Returns:
        The GeoDataFrame with the expected border columns.
    """
    return geopandas.GeoDataFrame(
        {
            "NEIGHBOR": ["Arizona", "Nevada", "Oregon"],
            "NEIGHBOR_ABBR": ["AZ", "NV", "OR"],
            "LENGTH_KM": [1.0, 2.0, 3.0],
        },
        geometry=geometry,
        crs=crs,
    )


def stub_border_file(
    monkeypatch: pytest.MonkeyPatch,
    dataframe: geopandas.GeoDataFrame,
) -> None:
    """Point load_border_geometry's file reads at *dataframe*.

    Args:
        monkeypatch: The monkeypatch fixture.
        dataframe: The stored border dataframe.
    """
    monkeypatch.setattr(
        peri_scribe.administrative_boundaries,
        "output_geopackage_path",
        lambda _base_dir: pathlib.Path("/data/border.gpkg"),
    )
    monkeypatch.setattr(
        peri_scribe.administrative_boundaries.geopandas,
        "read_file",
        lambda _path, **_keywords: dataframe,
    )


def test_output_geopackage_path() -> None:
    path = peri_scribe.administrative_boundaries.output_geopackage_path(
        BASE_DIRECTORY,
    )
    assert path == (
        BASE_DIRECTORY
        / "data"
        / "administrative_boundaries"
        / "CA_border_with_AZ_NV_and_OR.gpkg"
    )


def test_line_parts_returns_lines_from_collection() -> None:
    collection = shapely.geometry.GeometryCollection([
        shapely.geometry.LineString([(0, 0), (1, 1)]),
        shapely.geometry.Point(2, 2),
    ])
    parts = peri_scribe.administrative_boundaries.line_parts(collection)
    assert len(parts) == 1
    assert parts[0].equals(shapely.geometry.LineString([(0, 0), (1, 1)]))


def test_line_parts_returns_empty_for_point() -> None:
    assert (
        peri_scribe.administrative_boundaries.line_parts(
            shapely.geometry.Point(0, 0),
        )
        == []
    )


def test_shared_border_returns_shared_edge() -> None:
    border = peri_scribe.administrative_boundaries.shared_border(
        CALIFORNIA,
        ARIZONA,
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
    border = peri_scribe.administrative_boundaries.shared_border(
        CALIFORNIA,
        neighbor,
    )
    assert not border.is_empty
    assert peri_scribe.administrative_boundaries.total_line_length_in_degrees(
        border,
    ) == pytest.approx(10.0, abs=1e-3)


def test_shared_border_returns_multi_line_string_for_multiple_segments() -> None:
    neighbor = shapely.geometry.MultiPolygon([ARIZONA, OREGON])
    border = peri_scribe.administrative_boundaries.shared_border(
        CALIFORNIA,
        neighbor,
    )
    assert border.geom_type == "MultiLineString"
    assert len(border.geoms) > 1
    assert peri_scribe.administrative_boundaries.total_line_length_in_degrees(
        border,
    ) == pytest.approx(20.0, abs=1e-2)


def test_shared_border_raises_when_geometries_share_no_border() -> None:
    distant = shapely.geometry.Polygon([
        (50, 50),
        (50, 60),
        (60, 60),
        (60, 50),
    ])
    with pytest.raises(
        peri_scribe.exceptions.AdministrativeBoundariesError,
        match="share no border",
    ):
        peri_scribe.administrative_boundaries.shared_border(CALIFORNIA, distant)


def test_border_length_in_kilometers() -> None:
    line = shapely.geometry.LineString([(0, 0), (1, 0)])
    length_in_kilometers = (
        peri_scribe.administrative_boundaries.border_length_in_kilometers(line)
    )
    assert length_in_kilometers == pytest.approx(111.319, rel=1e-4)


def test_border_length_in_kilometers_sums_line_parts() -> None:
    multi_line = shapely.geometry.MultiLineString([
        shapely.geometry.LineString([(0, 0), (1, 0)]),
        shapely.geometry.LineString([(1, 0), (2, 0)]),
    ])
    length_in_kilometers = (
        peri_scribe.administrative_boundaries.border_length_in_kilometers(multi_line)
    )
    assert length_in_kilometers == pytest.approx(222.638, rel=1e-4)


def test_border_dataframe_builds_neighbor_rows() -> None:
    neighbor_states = peri_scribe.administrative_boundaries.NEIGHBOR_STATES
    neighbor_state_names = [state.name for state in neighbor_states]
    neighbor_state_abbreviations = [state.abbr for state in neighbor_states]
    neighbors = geopandas.GeoDataFrame(
        {
            "STATE_NAME": neighbor_state_names,
            "STATE_ABBR": neighbor_state_abbreviations,
        },
        geometry=[ARIZONA, NEVADA, OREGON],
        crs=pyproj.CRS.from_epsg(4326),
    )
    border = peri_scribe.administrative_boundaries.border_dataframe(
        CALIFORNIA,
        neighbors,
    )
    assert list(border["NEIGHBOR"]) == neighbor_state_names
    assert list(border["NEIGHBOR_ABBR"]) == neighbor_state_abbreviations
    assert border.geometry.name == "geom"
    assert border.crs.to_epsg() == peri_scribe.models.WGS84_SPATIAL_REFERENCE_ID
    assert all(border["LENGTH_KM"] > 0)


def test_layer_dataframe_queries_features_in_wgs84() -> None:
    feature_set = polygon_feature_set([ARIZONA], ["Arizona"], ["AZ"])
    layer = FeatureLayerStub(feature_set)
    dataframe = peri_scribe.administrative_boundaries.layer_dataframe(
        as_feature_layer(layer),
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
        },
    ]


def test_layer_dataframe_raises_when_layer_has_no_features() -> None:
    layer = FeatureLayerStub(arcgis.features.FeatureSet([]))
    with pytest.raises(
        peri_scribe.exceptions.AdministrativeBoundariesError,
        match="returned no features",
    ):
        peri_scribe.administrative_boundaries.layer_dataframe(
            as_feature_layer(layer),
            "California",
            where="STATE_ABBR='CA'",
        )


def test_layer_dataframe_logs_warning_when_geometry_missing() -> None:
    layer = FeatureLayerStub(GeometrylessFeatureSetStub(1))
    with structlog.testing.capture_logs() as captured:
        dataframe = peri_scribe.administrative_boundaries.layer_dataframe(
            as_feature_layer(layer),
            "California",
            where="STATE_ABBR='CA'",
        )
    assert len(dataframe) == 1
    assert dataframe.geometry.iloc[0] is None
    assert captured[0]["event"] == (
        "  warning: all features lack geometry; writing the layer with NULL geometry"
    )


def test_california_geometry_returns_polygon() -> None:
    layer = FeatureLayerStub(
        polygon_feature_set([CALIFORNIA], ["California"], ["CA"]),
    )
    geometry = peri_scribe.administrative_boundaries.california_geometry(
        as_feature_layer(layer),
    )
    assert geometry.equals(CALIFORNIA)
    assert layer.queries == [{"where": "STATE_ABBR='CA'", "out_sr": 4326}]


def test_california_geometry_raises_when_not_exactly_one_feature() -> None:
    layer = FeatureLayerStub(
        polygon_feature_set(
            [CALIFORNIA, CALIFORNIA],
            ["California", "California"],
            ["CA", "CA"],
        ),
    )
    with pytest.raises(
        peri_scribe.exceptions.AdministrativeBoundariesError,
        match="Expected one California feature, got 2",
    ):
        peri_scribe.administrative_boundaries.california_geometry(
            as_feature_layer(layer),
        )


def test_california_geometry_raises_when_feature_has_no_geometry() -> None:
    layer = FeatureLayerStub(GeometrylessFeatureSetStub(1))
    with pytest.raises(
        peri_scribe.exceptions.AdministrativeBoundariesError,
        match="has no geometry",
    ):
        peri_scribe.administrative_boundaries.california_geometry(
            as_feature_layer(layer),
        )


def test_neighbor_geometries_returns_expected_states() -> None:
    layer = FeatureLayerStub(
        polygon_feature_set(
            [ARIZONA, NEVADA, OREGON],
            ["Arizona", "Nevada", "Oregon"],
            ["AZ", "NV", "OR"],
        ),
    )
    neighbors = peri_scribe.administrative_boundaries.neighbor_geometries(
        as_feature_layer(layer),
    )
    assert len(neighbors) == (
        peri_scribe.administrative_boundaries.EXPECTED_FEATURE_COUNT
    )
    assert list(neighbors["STATE_ABBR"]) == ["AZ", "NV", "OR"]
    assert layer.queries == [
        {
            "where": "STATE_ABBR IN ('AZ','NV','OR')",
            "out_sr": 4326,
        },
    ]


def test_neighbor_geometries_raises_when_count_wrong() -> None:
    layer = FeatureLayerStub(
        polygon_feature_set(
            [ARIZONA, NEVADA],
            ["Arizona", "Nevada"],
            ["AZ", "NV"],
        ),
    )
    with pytest.raises(
        peri_scribe.exceptions.AdministrativeBoundariesError,
        match="Expected 3 neighboring states, got 2",
    ):
        peri_scribe.administrative_boundaries.neighbor_geometries(
            as_feature_layer(layer),
        )


def test_neighbor_geometries_raises_when_geometry_missing() -> None:
    layer = FeatureLayerStub(GeometrylessFeatureSetStub(3))
    with pytest.raises(
        peri_scribe.exceptions.AdministrativeBoundariesError,
        match="has no geometry",
    ):
        peri_scribe.administrative_boundaries.neighbor_geometries(
            as_feature_layer(layer),
        )


def test_is_usable_false_when_file_missing() -> None:
    assert not peri_scribe.administrative_boundaries.is_usable(
        pathlib.Path("/no/such/file.gpkg"),
    )


def test_is_usable_false_when_file_unreadable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pathlib.Path, "is_file", lambda _self: True)

    def fail_to_list(_path: object) -> typing.Never:
        message = "corrupt"
        raise RuntimeError(message)

    monkeypatch.setattr(
        peri_scribe.administrative_boundaries.geopandas,
        "list_layers",
        fail_to_list,
    )
    with structlog.testing.capture_logs() as captured:
        usable = peri_scribe.administrative_boundaries.is_usable(
            pathlib.Path("/data/file.gpkg"),
        )
    assert not usable
    assert captured[0]["event"] == "Administrative boundaries file is not usable"


def test_is_usable_false_when_layer_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_geopackage_reads(
        monkeypatch,
        ["Some_Other_Layer"],
        good_border_dataframe(),
    )
    assert not peri_scribe.administrative_boundaries.is_usable(
        pathlib.Path("/data/file.gpkg"),
    )


def test_is_usable_false_when_feature_count_wrong(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_geopackage_reads(
        monkeypatch,
        [OUTPUT_LAYER_NAME],
        good_border_dataframe().head(2),
    )
    assert not peri_scribe.administrative_boundaries.is_usable(
        pathlib.Path("/data/file.gpkg"),
    )


def test_is_usable_false_when_columns_wrong(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_geopackage_reads(
        monkeypatch,
        [OUTPUT_LAYER_NAME],
        typing.cast(
            "geopandas.GeoDataFrame",
            good_border_dataframe().drop(columns=["LENGTH_KM"]),
        ),
    )
    assert not peri_scribe.administrative_boundaries.is_usable(
        pathlib.Path("/data/file.gpkg"),
    )


def test_is_usable_false_when_geometry_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_geopackage_reads(
        monkeypatch,
        [OUTPUT_LAYER_NAME],
        is_usable_dataframe(geometry=[None, None, None]),
    )
    assert not peri_scribe.administrative_boundaries.is_usable(
        pathlib.Path("/data/file.gpkg"),
    )


def test_is_usable_false_when_geometry_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_geopackage_reads(
        monkeypatch,
        [OUTPUT_LAYER_NAME],
        is_usable_dataframe(
            geometry=[
                shapely.geometry.LineString(),
                shapely.geometry.LineString(),
                shapely.geometry.LineString(),
            ],
        ),
    )
    assert not peri_scribe.administrative_boundaries.is_usable(
        pathlib.Path("/data/file.gpkg"),
    )


def test_is_usable_false_when_spatial_reference_wrong(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_geopackage_reads(
        monkeypatch,
        [OUTPUT_LAYER_NAME],
        good_border_dataframe().to_crs(3857),
    )
    assert not peri_scribe.administrative_boundaries.is_usable(
        pathlib.Path("/data/file.gpkg"),
    )


def test_is_usable_false_when_no_spatial_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_geopackage_reads(
        monkeypatch,
        [OUTPUT_LAYER_NAME],
        is_usable_dataframe(
            geometry=[
                shapely.geometry.LineString([(0, 0), (1, 1)]),
                shapely.geometry.LineString([(2, 2), (3, 3)]),
                shapely.geometry.LineString([(4, 4), (5, 5)]),
            ],
            crs=None,
        ),
    )
    assert not peri_scribe.administrative_boundaries.is_usable(
        pathlib.Path("/data/file.gpkg"),
    )


def test_is_usable_true_when_file_good(monkeypatch: pytest.MonkeyPatch) -> None:
    stub_geopackage_reads(
        monkeypatch,
        [OUTPUT_LAYER_NAME],
        good_border_dataframe(),
    )
    assert peri_scribe.administrative_boundaries.is_usable(
        pathlib.Path("/data/file.gpkg"),
    )


def test_ensure_administrative_boundaries_skips_when_file_usable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        peri_scribe.administrative_boundaries,
        "is_usable",
        lambda _path: True,
    )
    constructed: list[str] = []
    monkeypatch.setattr(
        peri_scribe.administrative_boundaries.arcgis.features,
        "FeatureLayer",
        lambda url, _gis: constructed.append(url) or object(),
    )
    with structlog.testing.capture_logs() as captured:
        result = peri_scribe.administrative_boundaries.ensure_administrative_boundaries(
            BASE_DIRECTORY,
        )
    assert result == (
        peri_scribe.administrative_boundaries.output_geopackage_path(
            BASE_DIRECTORY,
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
        peri_scribe.administrative_boundaries,
        "is_usable",
        lambda _path: False,
    )
    monkeypatch.setattr(pathlib.Path, "cwd", staticmethod(lambda: BASE_DIRECTORY))
    monkeypatch.setattr(
        peri_scribe.administrative_boundaries.arcgis.gis,
        "GIS",
        object,
    )
    california_set = polygon_feature_set([CALIFORNIA], ["California"], ["CA"])
    neighbor_set = polygon_feature_set(
        [ARIZONA, NEVADA, OREGON],
        ["Arizona", "Nevada", "Oregon"],
        ["AZ", "NV", "OR"],
    )

    def layer_factory(url: str, gis: object) -> FeatureLayerStub:
        if url == peri_scribe.administrative_boundaries.CALIFORNIA_LAYER_URL:
            return FeatureLayerStub(california_set)
        if url == peri_scribe.administrative_boundaries.NEIGHBOR_LAYER_URL:
            return FeatureLayerStub(neighbor_set)
        raise AssertionError(url)

    monkeypatch.setattr(
        peri_scribe.administrative_boundaries.arcgis.features,
        "FeatureLayer",
        layer_factory,
    )
    output_path = peri_scribe.administrative_boundaries.output_geopackage_path(
        BASE_DIRECTORY,
    )
    result = peri_scribe.administrative_boundaries.ensure_administrative_boundaries()
    assert result == output_path
    assert geo_package_store.has(output_path)
    written = geo_package_store.layer(output_path, OUTPUT_LAYER_NAME)
    assert list(written["NEIGHBOR"]) == ["Arizona", "Nevada", "Oregon"]
    assert list(written["NEIGHBOR_ABBR"]) == ["AZ", "NV", "OR"]
    assert list(written.columns) == [
        "NEIGHBOR",
        "NEIGHBOR_ABBR",
        "LENGTH_KM",
        "geom",
    ]
    assert written.crs.to_epsg() == peri_scribe.models.WGS84_SPATIAL_REFERENCE_ID


def test_ensure_administrative_boundaries_raises_when_fetch_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        peri_scribe.administrative_boundaries,
        "is_usable",
        lambda _path: False,
    )
    monkeypatch.setattr(pathlib.Path, "cwd", staticmethod(lambda: BASE_DIRECTORY))
    monkeypatch.setattr(
        peri_scribe.administrative_boundaries.arcgis.gis,
        "GIS",
        object,
    )
    monkeypatch.setattr(
        peri_scribe.administrative_boundaries.arcgis.features,
        "FeatureLayer",
        lambda _url, _gis: FailingFeatureLayerStub(),
    )
    with pytest.raises(
        peri_scribe.exceptions.AdministrativeBoundariesError,
        match="Failed to build administrative boundaries: boom",
    ):
        peri_scribe.administrative_boundaries.ensure_administrative_boundaries()


def test_load_border_geometry_returns_stored_lines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_border_file(monkeypatch, good_border_dataframe())
    result = peri_scribe.administrative_boundaries.load_border_geometry(BASE_DIRECTORY)
    assert isinstance(result, shapely.geometry.MultiLineString)


def test_load_border_geometry_returns_single_line_when_one_part(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    single = geopandas.GeoDataFrame(
        {
            "NEIGHBOR": ["Oregon"],
            "NEIGHBOR_ABBR": ["OR"],
            "LENGTH_KM": [10.0],
        },
        geometry=[shapely.geometry.LineString([(0.0, 0.0), (10.0, 0.0)])],
        crs=pyproj.CRS.from_epsg(4326),
    )
    stub_border_file(monkeypatch, single)
    result = peri_scribe.administrative_boundaries.load_border_geometry(BASE_DIRECTORY)
    assert isinstance(result, shapely.geometry.LineString)


def california_like_border() -> shapely.geometry.MultiLineString:
    """Return a synthetic border shaped like California's interstate border.

    Returns:
        An Oregon segment across the top and a Nevada/Arizona segment down the east.
    """
    return shapely.geometry.MultiLineString([
        shapely.geometry.LineString([(-124.0, 42.0), (-120.0, 42.0)]),
        shapely.geometry.LineString([(-120.0, 42.0), (-114.0, 32.7)]),
    ])


def test_ordered_border_coordinates_orders_single_path() -> None:
    parts = [
        shapely.geometry.LineString([(0.0, 10.0), (5.0, 10.0), (10.0, 5.0)]),
    ]
    assert peri_scribe.administrative_boundaries.ordered_border_coordinates(parts) == [
        (0.0, 10.0),
        (5.0, 10.0),
        (10.0, 5.0),
    ]


def test_ordered_border_coordinates_orders_multiple_parts() -> None:
    parts = [
        shapely.geometry.LineString([(0.0, 10.0), (5.0, 10.0)]),
        shapely.geometry.LineString([(5.0, 10.0), (10.0, 5.0)]),
    ]
    assert peri_scribe.administrative_boundaries.ordered_border_coordinates(parts) == [
        (0.0, 10.0),
        (5.0, 10.0),
        (10.0, 5.0),
    ]


def test_ordered_border_coordinates_bridges_small_gaps() -> None:
    parts = [
        shapely.geometry.LineString([(0.0, 10.0), (5.0, 10.0)]),
        shapely.geometry.LineString([(5.00001, 10.0), (10.0, 5.0)]),
    ]
    assert peri_scribe.administrative_boundaries.ordered_border_coordinates(parts) == [
        (0.0, 10.0),
        (5.0, 10.0),
        (10.0, 5.0),
    ]


def test_ordered_border_coordinates_raises_when_no_segments() -> None:
    with pytest.raises(
        peri_scribe.exceptions.AdministrativeBoundariesError,
        match="no line segments",
    ):
        peri_scribe.administrative_boundaries.ordered_border_coordinates([])


def test_ordered_border_coordinates_raises_when_not_a_single_path() -> None:
    parts = [
        shapely.geometry.LineString([(0.0, 0.0), (1.0, 0.0)]),
        shapely.geometry.LineString([(10.0, 0.0), (11.0, 0.0)]),
    ]
    with pytest.raises(
        peri_scribe.exceptions.AdministrativeBoundariesError,
        match="not a single continuous path",
    ):
        peri_scribe.administrative_boundaries.ordered_border_coordinates(parts)


def test_california_box_polygon_contains_california() -> None:
    box = peri_scribe.administrative_boundaries.california_box_polygon(
        california_like_border(),
    )
    assert box.is_valid
    assert box.contains(shapely.geometry.Point(-120.0, 40.0))
    assert box.contains(shapely.geometry.Point(-123.0, 34.0))


def test_california_box_polygon_excludes_neighboring_states() -> None:
    box = peri_scribe.administrative_boundaries.california_box_polygon(
        california_like_border(),
    )
    assert not box.contains(shapely.geometry.Point(-117.0, 40.0))
    assert not box.contains(shapely.geometry.Point(-120.0, 43.0))


def test_california_box_polygon_absorbs_maritime_and_mexico() -> None:
    box = peri_scribe.administrative_boundaries.california_box_polygon(
        california_like_border(),
    )
    assert box.contains(shapely.geometry.Point(-116.0, 32.3))
    assert not box.contains(shapely.geometry.Point(-116.0, 30.0))
    assert not box.contains(shapely.geometry.Point(-127.0, 38.0))
