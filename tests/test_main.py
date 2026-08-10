"""Tests for peri_scribe.main."""

import logging
import pathlib
import typing

import arcgis.features
import click.testing
import geopandas as gpd
import pandas as pd
import pyproj
import pyproj.exceptions
import pytest
import shapely
import shapely.geometry
import structlog

import peri_scribe.main


WGS84_WKID = 4326
WEB_MERCATOR_WKID = 3857
CALIFORNIA_ALBERS_WKID = 3310
NAD83_WKID = 4269
NAVD88_HEIGHT_WKID = 5703
UNKNOWN_WKID = 999999

WEB_MERCATOR_MAXIMUM_MAGNITUDE = 20048966.104014598

CLICK_USAGE_ERROR_EXIT_CODE = 2

SAMPLE_FEED_URL = (
    "https://example.test/ArcGIS/rest/services/Fire_Layers/FeatureServer/3"
)
SAMPLE_PATH_SEGMENTS = [
    "ArcGIS",
    "rest",
    "services",
    "Fire_Layers",
    "FeatureServer",
    "3",
]
SAMPLE_SERVICE_NAME = "Fire_Layers"
SAMPLE_LAYER_ID = 3
SAMPLE_FEED_NAME = "Fire_Layers_3"


class LayerStub(arcgis.features.FeatureLayer):
    """Minimal stand-in for an ArcGIS FeatureLayer exposing properties."""

    def __init__(self, properties: dict[str, object]) -> None:
        self._properties = properties

    @property
    def properties(self) -> dict[str, object]:
        return self._properties


class FeatureSetStub(arcgis.features.FeatureSet):
    """Minimal stand-in for an ArcGIS FeatureSet exposing spatial_reference."""

    def __init__(self, spatial_reference: object) -> None:
        self._spatial_reference = spatial_reference

    @property
    def spatial_reference(self) -> object:
        return self._spatial_reference


class FeatureLayerStub:
    """Minimal stand-in for an ArcGIS FeatureLayer with a fixed query result."""

    def __init__(
        self,
        url: str,
        gis: object,
        feature_set: arcgis.features.FeatureSet,
        query_error: Exception | None = None,
    ) -> None:
        self._url = url
        self._gis = gis
        self._feature_set = feature_set
        self._query_error = query_error
        self._properties: dict[str, object] = {
            "spatialReference": {"wkid": WGS84_WKID},
        }

    @property
    def properties(self) -> dict[str, object]:
        return self._properties

    def query(self) -> arcgis.features.FeatureSet:
        if self._query_error is not None:
            raise self._query_error
        return self._feature_set


class FailingTransformer:
    """Transformer stand-in whose corner transforms always fail."""

    def transform(
        self,
        _longitude: float,
        _latitude: float,
    ) -> tuple[float, float]:
        message = "transform failed"
        raise pyproj.exceptions.ProjError(message)


def failing_from_crs(
    crs_from: str,
    crs_to: pyproj.CRS,
    *,
    always_xy: bool = True,
) -> FailingTransformer:
    return FailingTransformer()


@pytest.fixture
def runner() -> click.testing.CliRunner:
    return click.testing.CliRunner()


@pytest.fixture
def feature_set_with_geometry() -> arcgis.features.FeatureSet:
    """A FeatureSet whose features carry point geometries in WGS84."""
    return arcgis.features.FeatureSet(
        [
            arcgis.features.Feature(
                geometry={
                    "x": 1.0,
                    "y": 2.0,
                    "spatialReference": {"wkid": WGS84_WKID},
                },
                attributes={"name": "a"},
            ),
            arcgis.features.Feature(
                geometry={
                    "x": 3.0,
                    "y": 4.0,
                    "spatialReference": {"wkid": WGS84_WKID},
                },
                attributes={"name": "b"},
            ),
        ],
    )


@pytest.fixture
def layer_data_factory() -> typing.Callable[[str], peri_scribe.main.LayerData]:
    """Build LayerData entries with two point features in WGS84."""

    def make_layer_data(name: str) -> peri_scribe.main.LayerData:
        dataframe = gpd.GeoDataFrame(
            {"name": ["a", "b"]},
            geometry=[
                shapely.geometry.Point(1.0, 2.0),
                shapely.geometry.Point(3.0, 4.0),
            ],
            crs=pyproj.CRS.from_epsg(WGS84_WKID),
        )
        return peri_scribe.main.LayerData(name=name, dataframe=dataframe)

    return make_layer_data


@pytest.fixture
def _fetch_setup(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
    tmp_path: pathlib.Path,
) -> None:
    """Point the fetch command's ArcGIS boundary at stubs writing into tmp_path."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        peri_scribe.main,
        "configure_logging",
        lambda _log_level: None,
    )
    monkeypatch.setattr(
        peri_scribe.main,
        "FEEDS",
        [peri_scribe.main.ArcGISFeed(url=SAMPLE_FEED_URL)],
    )
    monkeypatch.setattr(peri_scribe.main.arcgis.gis, "GIS", object)


def test_no_features_error_is_a_value_error() -> None:
    assert issubclass(peri_scribe.main.NoFeaturesError, ValueError)


def test_no_spatial_reference_error_default_message() -> None:
    error = peri_scribe.main.NoSpatialReferenceError()
    assert str(error) == "no usable spatial reference wkid"


def test_no_spatial_reference_error_custom_message() -> None:
    error = peri_scribe.main.NoSpatialReferenceError("custom message")
    assert str(error) == "custom message"


def test_arc_gis_feed_path_segments() -> None:
    feed = peri_scribe.main.ArcGISFeed(url=SAMPLE_FEED_URL)
    assert feed.path_segments == SAMPLE_PATH_SEGMENTS


def test_arc_gis_feed_path_segments_ignore_empty_segments() -> None:
    feed = peri_scribe.main.ArcGISFeed(url=SAMPLE_FEED_URL + "/")
    assert feed.path_segments == SAMPLE_PATH_SEGMENTS


def test_arc_gis_feed_service_name() -> None:
    feed = peri_scribe.main.ArcGISFeed(url=SAMPLE_FEED_URL)
    assert feed.service_name == SAMPLE_SERVICE_NAME


def test_arc_gis_feed_layer_id() -> None:
    feed = peri_scribe.main.ArcGISFeed(url=SAMPLE_FEED_URL)
    assert feed.layer_id == SAMPLE_LAYER_ID


def test_arc_gis_feed_name() -> None:
    feed = peri_scribe.main.ArcGISFeed(url=SAMPLE_FEED_URL)
    assert feed.name == SAMPLE_FEED_NAME


def test_spatial_reference_wkids_none_is_empty() -> None:
    assert peri_scribe.main.spatial_reference_wkids(None) == set()


def test_spatial_reference_wkids_non_dict_is_empty() -> None:
    assert peri_scribe.main.spatial_reference_wkids("EPSG:4326") == set()


def test_spatial_reference_wkids_empty_dict_is_empty() -> None:
    assert peri_scribe.main.spatial_reference_wkids({}) == set()


def test_spatial_reference_wkids_integer_wkid() -> None:
    assert peri_scribe.main.spatial_reference_wkids({"wkid": WGS84_WKID}) == {
        WGS84_WKID,
    }


def test_spatial_reference_wkids_numeric_string_wkid() -> None:
    assert peri_scribe.main.spatial_reference_wkids({"wkid": "102100"}) == {102100}


def test_spatial_reference_wkids_non_numeric_string_ignored() -> None:
    assert peri_scribe.main.spatial_reference_wkids({"wkid": "abc"}) == set()


def test_spatial_reference_wkids_latest_wkid() -> None:
    assert peri_scribe.main.spatial_reference_wkids(
        {"latestWkid": WEB_MERCATOR_WKID},
    ) == {
        WEB_MERCATOR_WKID,
    }


def test_spatial_reference_wkids_ignores_other_value_types() -> None:
    assert (
        peri_scribe.main.spatial_reference_wkids(
            {"wkid": 1.5, "latestWkid": None},
        )
        == set()
    )


def test_spatial_reference_wkids_unions_both_keys() -> None:
    assert peri_scribe.main.spatial_reference_wkids(
        {"wkid": WGS84_WKID, "latestWkid": WEB_MERCATOR_WKID},
    ) == {WGS84_WKID, WEB_MERCATOR_WKID}


def test_layer_wkids_no_reported_references_is_empty() -> None:
    layer = LayerStub(properties={})
    assert peri_scribe.main.layer_wkids(layer) == set()


def test_layer_wkids_from_layer_properties() -> None:
    layer = LayerStub(properties={"spatialReference": {"wkid": WGS84_WKID}})
    assert peri_scribe.main.layer_wkids(layer) == {WGS84_WKID}


def test_layer_wkids_from_extents() -> None:
    layer = LayerStub(
        properties={
            "extent": {"spatialReference": {"wkid": WGS84_WKID}},
            "fullExtent": {"spatialReference": {"wkid": NAD83_WKID}},
            "initialExtent": {"spatialReference": {"latestWkid": WEB_MERCATOR_WKID}},
        },
    )
    assert peri_scribe.main.layer_wkids(layer) == {
        WGS84_WKID,
        NAD83_WKID,
        WEB_MERCATOR_WKID,
    }


def test_layer_wkids_ignores_non_dict_spatial_reference() -> None:
    layer = LayerStub(properties={"spatialReference": "EPSG:4326"})
    assert peri_scribe.main.layer_wkids(layer) == set()


def test_bounds_of_empty_list_is_none() -> None:
    assert peri_scribe.main.bounds_of([]) is None


def test_bounds_of_all_null_geometries_is_none() -> None:
    geometries: list[shapely.Geometry | None] = [None, None]
    assert peri_scribe.main.bounds_of(geometries) is None


def test_bounds_of_single_point() -> None:
    geometries: list[shapely.Geometry | None] = [
        shapely.geometry.Point(1.0, 2.0),
    ]
    assert peri_scribe.main.bounds_of(geometries) == (1.0, 1.0, 2.0, 2.0)


def test_bounds_of_multiple_points() -> None:
    geometries: list[shapely.Geometry | None] = [
        shapely.geometry.Point(1.0, 2.0),
        shapely.geometry.Point(3.0, 4.0),
    ]
    assert peri_scribe.main.bounds_of(geometries) == (1.0, 3.0, 2.0, 4.0)


def test_bounds_of_ignores_null_geometries() -> None:
    geometries: list[shapely.Geometry | None] = [
        None,
        shapely.geometry.Point(-1.0, -2.0),
        shapely.geometry.Point(3.0, 4.0),
    ]
    assert peri_scribe.main.bounds_of(geometries) == (-1.0, 3.0, -2.0, 4.0)


def test_bounds_of_polygon() -> None:
    polygon = shapely.geometry.Polygon(
        [(0.0, 0.0), (10.0, 0.0), (10.0, 5.0), (0.0, 5.0)],
    )
    geometries: list[shapely.Geometry | None] = [polygon]
    assert peri_scribe.main.bounds_of(geometries) == (0.0, 10.0, 0.0, 5.0)


def test_projected_maximum_magnitude_web_mercator() -> None:
    crs = pyproj.CRS.from_epsg(WEB_MERCATOR_WKID)
    assert peri_scribe.main.projected_maximum_magnitude(crs) == pytest.approx(
        WEB_MERCATOR_MAXIMUM_MAGNITUDE,
    )


def test_projected_maximum_magnitude_fallback_without_area_of_use() -> None:
    crs = pyproj.CRS.from_proj4("+proj=aeqd +lat_0=0 +lon_0=0 +datum=WGS84 +units=m")
    assert (
        peri_scribe.main.projected_maximum_magnitude(crs)
        == peri_scribe.main.PROJECTED_MAXIMUM_MAGNITUDE_FALLBACK
    )


def test_projected_maximum_magnitude_falls_back_when_all_corner_transforms_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pyproj.Transformer, "from_crs", failing_from_crs)
    crs = pyproj.CRS.from_epsg(WEB_MERCATOR_WKID)
    assert (
        peri_scribe.main.projected_maximum_magnitude(crs)
        == peri_scribe.main.PROJECTED_MAXIMUM_MAGNITUDE_FALLBACK
    )


def test_spatial_reference_domain_geographic() -> None:
    domain = peri_scribe.main.spatial_reference_domain(WGS84_WKID)
    assert domain is not None
    assert domain.crs.is_geographic
    assert domain.bands == (0.0, 180.0, 0.0, 90.0)
    assert domain.description == "geographic (degrees)"


def test_spatial_reference_domain_projected() -> None:
    domain = peri_scribe.main.spatial_reference_domain(WEB_MERCATOR_WKID)
    assert domain is not None
    assert domain.crs.is_projected
    x_minimum_band, x_maximum_band, y_minimum_band, y_maximum_band = domain.bands
    assert x_minimum_band == peri_scribe.main.MINIMUM_PROJECTED_MAGNITUDE
    assert x_maximum_band == pytest.approx(WEB_MERCATOR_MAXIMUM_MAGNITUDE)
    assert y_minimum_band == peri_scribe.main.MINIMUM_PROJECTED_MAGNITUDE
    assert y_maximum_band == pytest.approx(WEB_MERCATOR_MAXIMUM_MAGNITUDE)
    assert domain.description == "projected (metre)"


def test_spatial_reference_domain_unknown_wkid_is_none() -> None:
    assert peri_scribe.main.spatial_reference_domain(UNKNOWN_WKID) is None


def test_spatial_reference_domain_vertical_crs_is_none() -> None:
    assert peri_scribe.main.spatial_reference_domain(NAVD88_HEIGHT_WKID) is None


def test_axis_fits_within_band() -> None:
    assert peri_scribe.main.axis_fits(10.0, 20.0, 5.0, 30.0)


def test_axis_fits_exact_boundaries() -> None:
    assert peri_scribe.main.axis_fits(5.0, 30.0, 5.0, 30.0)


def test_axis_fits_exceeds_maximum_magnitude() -> None:
    assert not peri_scribe.main.axis_fits(10.0, 31.0, 5.0, 30.0)


def test_axis_fits_below_minimum_magnitude() -> None:
    assert not peri_scribe.main.axis_fits(4.0, 20.0, 5.0, 30.0)


def test_axis_fits_crosses_zero_with_positive_minimum() -> None:
    assert not peri_scribe.main.axis_fits(-5.0, 5.0, 5.0, 30.0)


def test_axis_fits_zero_crossing_allowed_when_minimum_is_zero() -> None:
    assert peri_scribe.main.axis_fits(-5.0, 5.0, 0.0, 30.0)


def test_coordinates_match_domain_when_all_axes_fit() -> None:
    domain = (1000.0, 20000000.0, 1000.0, 20000000.0)
    bounds = (2000000.0, 3000000.0, 4000000.0, 5000000.0)
    assert peri_scribe.main.coordinates_match_domain(domain, bounds)


def test_coordinates_match_domain_x_axis_too_small() -> None:
    domain = (1000.0, 20000000.0, 1000.0, 20000000.0)
    bounds = (100.0, 3000000.0, 4000000.0, 5000000.0)
    assert not peri_scribe.main.coordinates_match_domain(domain, bounds)


def test_coordinates_match_domain_y_axis_too_large() -> None:
    domain = (1000.0, 20000000.0, 1000.0, 20000000.0)
    bounds = (2000000.0, 3000000.0, 4000000.0, 50000000.0)
    assert not peri_scribe.main.coordinates_match_domain(domain, bounds)


def test_longitudes_in_area_inside_normal_area() -> None:
    assert peri_scribe.main.longitudes_in_area(-124.45, -114.12, -120.0, -119.0)


def test_longitudes_in_area_outside_normal_area_west() -> None:
    assert not peri_scribe.main.longitudes_in_area(-124.45, -114.12, -125.0, -124.0)


def test_longitudes_in_area_outside_normal_area_east() -> None:
    assert not peri_scribe.main.longitudes_in_area(-124.45, -114.12, -113.0, -112.0)


def test_longitudes_in_area_inside_wrap_east_side() -> None:
    assert peri_scribe.main.longitudes_in_area(167.65, -40.73, 175.0, 179.0)


def test_longitudes_in_area_inside_wrap_west_side() -> None:
    assert peri_scribe.main.longitudes_in_area(167.65, -40.73, -170.0, -160.0)


def test_longitudes_in_area_outside_area_wrapping_antimeridian() -> None:
    assert not peri_scribe.main.longitudes_in_area(167.65, -40.73, 0.0, 10.0)


def test_longitudes_in_area_exact_point_in_normal_area() -> None:
    assert peri_scribe.main.longitudes_in_area(-120.0, -120.0, -120.0, -120.0)


def test_coordinates_in_area_unknown_area_of_use_matches() -> None:
    crs = pyproj.CRS.from_proj4("+proj=aeqd +lat_0=0 +lon_0=0 +datum=WGS84 +units=m")
    assert peri_scribe.main.coordinates_in_area(crs, (-124.45, -114.12, 32.53, 42.01))


def test_coordinates_in_area_inside_california_albers() -> None:
    crs = pyproj.CRS.from_epsg(CALIFORNIA_ALBERS_WKID)
    assert peri_scribe.main.coordinates_in_area(crs, (-121.0, -120.0, 33.0, 34.0))


def test_coordinates_in_area_outside_california_albers() -> None:
    crs = pyproj.CRS.from_epsg(CALIFORNIA_ALBERS_WKID)
    assert not peri_scribe.main.coordinates_in_area(crs, (-99.0, -98.0, 30.0, 31.0))


def test_coordinates_in_area_inside_area_wrapping_antimeridian() -> None:
    crs = pyproj.CRS.from_epsg(NAD83_WKID)
    assert peri_scribe.main.coordinates_in_area(crs, (-170.0, -160.0, 55.0, 65.0))


def test_coordinates_in_area_outside_area_wrapping_antimeridian() -> None:
    crs = pyproj.CRS.from_epsg(NAD83_WKID)
    assert not peri_scribe.main.coordinates_in_area(crs, (150.0, 151.0, -35.0, -34.0))


def test_coordinates_in_area_latitude_outside_wrapping_area() -> None:
    crs = pyproj.CRS.from_epsg(NAD83_WKID)
    assert not peri_scribe.main.coordinates_in_area(crs, (-170.0, -160.0, 0.0, 5.0))


def test_area_of_use_text_formats_bounds() -> None:
    crs = pyproj.CRS.from_epsg(CALIFORNIA_ALBERS_WKID)
    assert (
        peri_scribe.main.area_of_use_text(crs)
        == "longitude -124.45..-114.12, latitude 32.53..42.01"
    )


def test_area_of_use_text_unknown() -> None:
    crs = pyproj.CRS.from_proj4("+proj=aeqd +lat_0=0 +lon_0=0 +datum=WGS84 +units=m")
    assert peri_scribe.main.area_of_use_text(crs) == "unknown"


def test_choose_spatial_reference_id_no_reported_wkids_fails() -> None:
    layer = LayerStub(properties={})
    feature_set = FeatureSetStub(spatial_reference={})
    with pytest.raises(
        peri_scribe.main.NoSpatialReferenceError,
        match="no spatial reference wkid reported by the layer or its query",
    ):
        peri_scribe.main.choose_spatial_reference_id(layer, feature_set, None)


def test_choose_spatial_reference_id_single_candidate_without_geometry() -> None:
    layer = LayerStub(properties={"spatialReference": {"wkid": WGS84_WKID}})
    feature_set = FeatureSetStub(spatial_reference=None)
    assert (
        peri_scribe.main.choose_spatial_reference_id(layer, feature_set, None)
        == WGS84_WKID
    )


def test_choose_spatial_reference_id_multiple_candidates_without_geometry_fails() -> (
    None
):
    layer = LayerStub(properties={"spatialReference": {"wkid": WGS84_WKID}})
    feature_set = FeatureSetStub(spatial_reference={"wkid": NAD83_WKID})
    with pytest.raises(
        peri_scribe.main.NoSpatialReferenceError,
        match="no feature geometry is available to check them",
    ):
        peri_scribe.main.choose_spatial_reference_id(layer, feature_set, None)


def test_choose_spatial_reference_id_uses_query_spatial_reference() -> None:
    layer = LayerStub(properties={})
    feature_set = FeatureSetStub(spatial_reference={"wkid": WGS84_WKID})
    bounds = (-121.0, -120.0, 33.0, 34.0)
    chosen = peri_scribe.main.choose_spatial_reference_id(layer, feature_set, bounds)
    assert chosen == WGS84_WKID


def test_choose_spatial_reference_id_single_match_without_exclusions_is_quiet() -> None:
    layer = LayerStub(properties={"spatialReference": {"wkid": WGS84_WKID}})
    feature_set = FeatureSetStub(spatial_reference=None)
    bounds = (-121.0, -120.0, 33.0, 34.0)
    with structlog.testing.capture_logs() as captured:
        chosen = peri_scribe.main.choose_spatial_reference_id(
            layer,
            feature_set,
            bounds,
        )
    assert chosen == WGS84_WKID
    assert captured == []


def test_choose_spatial_reference_id_reports_excluded_projected_candidate() -> None:
    layer = LayerStub(
        properties={
            "spatialReference": {"wkid": WGS84_WKID, "latestWkid": WEB_MERCATOR_WKID},
        },
    )
    feature_set = FeatureSetStub(spatial_reference=None)
    bounds = (-121.0, -120.0, 33.0, 34.0)
    with structlog.testing.capture_logs() as captured:
        chosen = peri_scribe.main.choose_spatial_reference_id(
            layer,
            feature_set,
            bounds,
        )
    assert chosen == WGS84_WKID
    assert len(captured) == 1
    assert captured[0]["log_level"] == "warning"
    assert "picked spatial reference EPSG:4326" in captured[0]["event"]
    assert "excluded 3857" in captured[0]["event"]


def test_choose_spatial_reference_id_reports_excluded_out_of_area_candidate() -> None:
    layer = LayerStub(
        properties={"spatialReference": {"wkid": WGS84_WKID, "latestWkid": NAD83_WKID}},
    )
    feature_set = FeatureSetStub(spatial_reference=None)
    bounds = (150.0, 151.0, -35.0, -34.0)
    with structlog.testing.capture_logs() as captured:
        chosen = peri_scribe.main.choose_spatial_reference_id(
            layer,
            feature_set,
            bounds,
        )
    assert chosen == WGS84_WKID
    assert len(captured) == 1
    assert captured[0]["log_level"] == "warning"
    assert "excluded 4269" in captured[0]["event"]
    assert "coordinates outside its area of use" in captured[0]["event"]


def test_choose_spatial_reference_id_reports_excluded_unknown_wkid() -> None:
    layer = LayerStub(
        properties={
            "spatialReference": {"wkid": WGS84_WKID, "latestWkid": UNKNOWN_WKID},
        },
    )
    feature_set = FeatureSetStub(spatial_reference=None)
    bounds = (-121.0, -120.0, 33.0, 34.0)
    with structlog.testing.capture_logs() as captured:
        chosen = peri_scribe.main.choose_spatial_reference_id(
            layer,
            feature_set,
            bounds,
        )
    assert chosen == WGS84_WKID
    assert len(captured) == 1
    assert captured[0]["log_level"] == "warning"
    assert "no expected coordinate range known" in captured[0]["event"]


def test_choose_spatial_reference_id_fails_when_no_candidate_matches() -> None:
    layer = LayerStub(properties={"spatialReference": {"wkid": WEB_MERCATOR_WKID}})
    feature_set = FeatureSetStub(spatial_reference=None)
    bounds = (-121.0, -120.0, 33.0, 34.0)
    with pytest.raises(
        peri_scribe.main.NoSpatialReferenceError,
        match="no reported spatial reference wkid matches",
    ):
        peri_scribe.main.choose_spatial_reference_id(layer, feature_set, bounds)


def test_choose_spatial_reference_id_fails_when_several_candidates_match() -> None:
    layer = LayerStub(
        properties={"spatialReference": {"wkid": WGS84_WKID, "latestWkid": NAD83_WKID}},
    )
    feature_set = FeatureSetStub(spatial_reference=None)
    bounds = (-121.0, -120.0, 33.0, 34.0)
    with pytest.raises(
        peri_scribe.main.NoSpatialReferenceError,
        match="ambiguous spatial reference",
    ):
        peri_scribe.main.choose_spatial_reference_id(layer, feature_set, bounds)


def test_select_spatial_reference_wkid_no_candidates() -> None:
    selection = peri_scribe.main.select_spatial_reference_wkid(set(), None)
    assert selection.wkid is None
    assert (
        selection.failure_message
        == "no spatial reference wkid reported by the layer or its query"
    )


def test_select_spatial_reference_wkid_single_candidate_without_bounds() -> None:
    selection = peri_scribe.main.select_spatial_reference_wkid(
        {WGS84_WKID},
        None,
    )
    assert selection.wkid == WGS84_WKID
    assert selection.warning is None
    assert selection.failure_message == ""


def test_select_spatial_reference_wkid_ambiguous_without_bounds() -> None:
    selection = peri_scribe.main.select_spatial_reference_wkid(
        {WGS84_WKID, NAD83_WKID},
        None,
    )
    assert selection.wkid is None
    assert selection.failure_message is not None
    assert "cannot determine spatial reference" in selection.failure_message


def test_select_spatial_reference_wkid_single_match_keeps_exclusions() -> None:
    selection = peri_scribe.main.select_spatial_reference_wkid(
        {WGS84_WKID, WEB_MERCATOR_WKID},
        (-121.0, -120.0, 33.0, 34.0),
    )
    assert selection.wkid == WGS84_WKID
    assert selection.failure_message == ""
    assert selection.warning is not None
    assert "3857" in selection.warning


def test_select_spatial_reference_wkid_no_match_reports_exclusions() -> None:
    selection = peri_scribe.main.select_spatial_reference_wkid(
        {WEB_MERCATOR_WKID},
        (-121.0, -120.0, 33.0, 34.0),
    )
    assert selection.wkid is None
    assert selection.failure_message is not None
    assert "no reported spatial reference wkid matches" in selection.failure_message
    assert "3857" in selection.failure_message


def test_select_spatial_reference_wkid_ambiguous_with_bounds() -> None:
    selection = peri_scribe.main.select_spatial_reference_wkid(
        {WGS84_WKID, NAD83_WKID},
        (-121.0, -120.0, 33.0, 34.0),
    )
    assert selection.wkid is None
    assert selection.failure_message is not None
    assert "ambiguous spatial reference" in selection.failure_message


def test_extract_geometries_without_shape_column() -> None:
    dataframe = pd.DataFrame({"name": ["a", "b"]})
    attributes, geometries, geometry_warning = peri_scribe.main.extract_geometries(
        dataframe,
    )
    assert geometry_warning == (
        "  warning: all features lack geometry; writing the layer with NULL geometry"
    )
    assert geometries == [None, None]
    assert list(attributes.columns) == ["name"]


def test_extract_geometries_with_shape_column(
    feature_set_with_geometry: arcgis.features.FeatureSet,
) -> None:
    attributes, geometries, geometry_warning = peri_scribe.main.extract_geometries(
        feature_set_with_geometry.sdf,
    )
    assert geometry_warning is None
    assert "SHAPE" not in attributes.columns
    assert geometries == [
        shapely.geometry.Point(1.0, 2.0),
        shapely.geometry.Point(3.0, 4.0),
    ]


def test_geo_data_frame_from_builds_native_crs_dataframe() -> None:
    dataframe = pd.DataFrame({"name": ["a", "b"]})
    geometries: list[shapely.Geometry | None] = [
        shapely.geometry.Point(1.0, 2.0),
        shapely.geometry.Point(3.0, 4.0),
    ]
    result = peri_scribe.main.geo_data_frame_from(
        dataframe,
        geometries,
        WGS84_WKID,
    )
    assert result.crs == pyproj.CRS.from_epsg(WGS84_WKID)
    assert result.geometry.name == peri_scribe.main.GEOMETRY_COLUMN_NAME
    assert list(result["name"]) == ["a", "b"]
    assert list(result.geometry) == geometries


def test_geo_data_frame_from_allows_null_geometries() -> None:
    dataframe = pd.DataFrame({"name": ["a"]})
    geometries: list[shapely.Geometry | None] = [None]
    result = peri_scribe.main.geo_data_frame_from(
        dataframe,
        geometries,
        WGS84_WKID,
    )
    assert list(result.geometry) == [None]


def test_dataframe_for_layer_raises_no_features_error_when_feed_is_empty() -> None:
    feed = peri_scribe.main.ArcGISFeed(url=SAMPLE_FEED_URL)
    layer = LayerStub(properties={})
    feature_set = arcgis.features.FeatureSet([])
    with pytest.raises(
        peri_scribe.main.NoFeaturesError,
        match=(
            f"Feed {SAMPLE_FEED_NAME} returned no features; "
            f"{peri_scribe.main.OUTPUT_FILENAME} was not modified"
        ),
    ):
        peri_scribe.main.dataframe_for_layer(feed, layer, feature_set)


def test_dataframe_for_layer_builds_geo_data_frame(
    feature_set_with_geometry: arcgis.features.FeatureSet,
) -> None:
    feed = peri_scribe.main.ArcGISFeed(url=SAMPLE_FEED_URL)
    layer = LayerStub(properties={"spatialReference": {"wkid": WGS84_WKID}})
    result = peri_scribe.main.dataframe_for_layer(
        feed,
        layer,
        feature_set_with_geometry,
    )
    assert result.crs == pyproj.CRS.from_epsg(WGS84_WKID)
    assert result.geometry.name == peri_scribe.main.GEOMETRY_COLUMN_NAME
    assert list(result["name"]) == ["a", "b"]
    assert list(result.geometry) == [
        shapely.geometry.Point(1.0, 2.0),
        shapely.geometry.Point(3.0, 4.0),
    ]


def test_dataframe_for_layer_warns_when_features_lack_geometry() -> None:
    feed = peri_scribe.main.ArcGISFeed(url=SAMPLE_FEED_URL)
    layer = LayerStub(properties={"spatialReference": {"wkid": WGS84_WKID}})
    feature_set = arcgis.features.FeatureSet(
        [
            arcgis.features.Feature(attributes={"name": "a"}),
            arcgis.features.Feature(attributes={"name": "b"}),
        ],
    )
    with structlog.testing.capture_logs() as captured:
        result = peri_scribe.main.dataframe_for_layer(feed, layer, feature_set)
    assert len(captured) == 1
    assert captured[0]["log_level"] == "warning"
    assert "all features lack geometry" in captured[0]["event"]
    assert list(result.geometry) == [None, None]


def test_write_geopackage_writes_every_layer(
    tmp_path: pathlib.Path,
    layer_data_factory: typing.Callable[[str], peri_scribe.main.LayerData],
) -> None:
    path = tmp_path / "out.gpkg"
    peri_scribe.main.write_geopackage(
        path,
        [
            layer_data_factory("first_layer"),
            layer_data_factory("second_layer"),
        ],
    )
    first = gpd.read_file(path, layer="first_layer")
    second = gpd.read_file(path, layer="second_layer")
    assert list(first["name"]) == ["a", "b"]
    assert list(second["name"]) == ["a", "b"]


def test_write_geopackage_replaces_existing_file(
    tmp_path: pathlib.Path,
    layer_data_factory: typing.Callable[[str], peri_scribe.main.LayerData],
) -> None:
    path = tmp_path / "out.gpkg"
    path.write_bytes(b"not a geopackage")
    with structlog.testing.capture_logs() as captured:
        peri_scribe.main.write_geopackage(
            path,
            [layer_data_factory("replacement_layer")],
        )
    assert "Replaced existing" in [event["event"] for event in captured]
    written = gpd.read_file(path, layer="replacement_layer")
    assert list(written["name"]) == ["a", "b"]


def test_configure_logging_filters_below_configured_level() -> None:
    with structlog.testing.capture_logs():
        peri_scribe.main.configure_logging("warning")
        logger = structlog.get_logger()
        assert not logger.is_enabled_for(logging.DEBUG)
        assert not logger.is_enabled_for(logging.INFO)
        assert logger.is_enabled_for(logging.WARNING)
        assert logger.is_enabled_for(logging.ERROR)


def test_configure_logging_debug_level_enables_every_level() -> None:
    with structlog.testing.capture_logs():
        peri_scribe.main.configure_logging("debug")
        logger = structlog.get_logger()
        assert logger.is_enabled_for(logging.DEBUG)
        assert logger.is_enabled_for(logging.CRITICAL)


def test_cli_help(runner: click.testing.CliRunner) -> None:
    result = runner.invoke(peri_scribe.main.cli, ["--help"])
    assert result.exit_code == 0
    assert (
        "Fetch current wildfire data feeds into a single GeoPackage." in result.output
    )


def test_cli_invalid_log_level(runner: click.testing.CliRunner) -> None:
    result = runner.invoke(peri_scribe.main.cli, ["--log-level", "verbose"])
    assert result.exit_code == CLICK_USAGE_ERROR_EXIT_CODE
    assert "Invalid value for '--log-level'" in result.output


def test_cli_requires_subcommand(runner: click.testing.CliRunner) -> None:
    result = runner.invoke(peri_scribe.main.cli, [])
    assert result.exit_code == CLICK_USAGE_ERROR_EXIT_CODE
    assert "Commands:" in result.output
    assert "fetch" in result.output


def test_cli_configures_logging_from_log_level(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
) -> None:
    configured_levels: list[str] = []
    monkeypatch.setattr(
        peri_scribe.main,
        "configure_logging",
        configured_levels.append,
    )
    result = runner.invoke(
        peri_scribe.main.cli,
        ["--log-level", "DEBUG", "feed-config"],
    )
    assert result.exit_code == 0
    assert configured_levels == ["debug"]


@pytest.mark.usefixtures("_fetch_setup")
def test_fetch_writes_geo_package(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
    feature_set_with_geometry: arcgis.features.FeatureSet,
    tmp_path: pathlib.Path,
) -> None:
    monkeypatch.setattr(
        peri_scribe.main.arcgis.features,
        "FeatureLayer",
        lambda url, gis: FeatureLayerStub(url, gis, feature_set_with_geometry),
    )
    result = runner.invoke(peri_scribe.main.cli, ["fetch"])
    output_path = tmp_path / peri_scribe.main.OUTPUT_FILENAME
    assert result.exit_code == 0
    assert output_path.exists()
    written = gpd.read_file(output_path, layer=SAMPLE_FEED_NAME)
    assert list(written["name"]) == ["a", "b"]
    assert written.crs == pyproj.CRS.from_epsg(WGS84_WKID)


@pytest.mark.usefixtures("_fetch_setup")
def test_fetch_fails_fast_when_query_fails(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
    tmp_path: pathlib.Path,
) -> None:
    monkeypatch.setattr(
        peri_scribe.main.arcgis.features,
        "FeatureLayer",
        lambda url, gis: FeatureLayerStub(
            url,
            gis,
            arcgis.features.FeatureSet([]),
            query_error=RuntimeError("boom"),
        ),
    )
    result = runner.invoke(peri_scribe.main.cli, ["fetch"])
    assert result.exit_code == 1
    assert f"Failed to fetch {SAMPLE_FEED_NAME}: boom" in result.output
    assert not (tmp_path / peri_scribe.main.OUTPUT_FILENAME).exists()


@pytest.mark.usefixtures("_fetch_setup")
def test_fetch_fails_fast_when_feed_returns_no_features(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
    tmp_path: pathlib.Path,
) -> None:
    monkeypatch.setattr(
        peri_scribe.main.arcgis.features,
        "FeatureLayer",
        lambda url, gis: FeatureLayerStub(
            url,
            gis,
            arcgis.features.FeatureSet([]),
        ),
    )
    result = runner.invoke(peri_scribe.main.cli, ["fetch"])
    assert result.exit_code == 1
    assert (
        f"Failed to fetch {SAMPLE_FEED_NAME}: "
        f"Feed {SAMPLE_FEED_NAME} returned no features; "
        f"{peri_scribe.main.OUTPUT_FILENAME} was not modified"
    ) in result.output
    assert not (tmp_path / peri_scribe.main.OUTPUT_FILENAME).exists()


def test_feed_config_logs_each_configured_feed(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
) -> None:
    monkeypatch.setattr(
        peri_scribe.main,
        "configure_logging",
        lambda _log_level: None,
    )
    with structlog.testing.capture_logs() as captured:
        result = runner.invoke(peri_scribe.main.cli, ["feed-config"])
    assert result.exit_code == 0
    assert len(captured) == len(peri_scribe.main.FEEDS)
    for index, (event, feed) in enumerate(
        zip(captured, peri_scribe.main.FEEDS, strict=True),
    ):
        assert event["event"] == f"Feed {index + 1}"
        assert event["name"] == feed.name
        assert event["url"] == feed.url
