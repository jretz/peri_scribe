"""Verify coordinate-reference selection against metadata and geometry."""

import unittest.mock

import pyproj
import pytest
import shapely
import shapely.geometry
import structlog

import arcgis_access.exceptions
import arcgis_access.spatial_reference
import tests.helpers.doubles.arcgis
import tests.helpers.doubles.pyproj
import tests.helpers.factories.arcgis_access.spatial_reference
import tests.helpers.factories.geography


@pytest.mark.parametrize(
    "geometry",
    [shapely.Point(), shapely.Polygon(), shapely.GeometryCollection()],
)
def test_bounds_of_returns_none_for_empty_geometry(geometry: shapely.Geometry) -> None:
    assert arcgis_access.spatial_reference.bounds_of([geometry]) is None


def test_spatial_reference_wkids_none_is_empty() -> None:
    assert arcgis_access.spatial_reference.spatial_reference_wkids(None) == set()


def test_spatial_reference_wkids_non_dict_is_empty() -> None:
    assert arcgis_access.spatial_reference.spatial_reference_wkids("EPSG:4326") == set()


def test_spatial_reference_wkids_empty_dict_is_empty() -> None:
    assert arcgis_access.spatial_reference.spatial_reference_wkids({}) == set()


def test_spatial_reference_wkids_integer_wkid() -> None:
    assert arcgis_access.spatial_reference.spatial_reference_wkids({
        "wkid": tests.helpers.factories.geography.WGS84_WKID,
    }) == {tests.helpers.factories.geography.WGS84_WKID}


def test_spatial_reference_wkids_numeric_string_wkid() -> None:
    assert arcgis_access.spatial_reference.spatial_reference_wkids({
        "wkid": "102100",
    }) == {102100}


def test_spatial_reference_wkids_non_numeric_string_ignored() -> None:
    assert (
        arcgis_access.spatial_reference.spatial_reference_wkids({"wkid": "abc"})
        == set()
    )


def test_spatial_reference_wkids_latest_wkid() -> None:
    assert arcgis_access.spatial_reference.spatial_reference_wkids({
        "latestWkid": tests.helpers.factories.geography.WEB_MERCATOR_WKID,
    }) == {tests.helpers.factories.geography.WEB_MERCATOR_WKID}


def test_spatial_reference_wkids_ignores_other_value_types() -> None:
    assert (
        arcgis_access.spatial_reference.spatial_reference_wkids({
            "wkid": 1.5,
            "latestWkid": None,
        })
        == set()
    )


def test_spatial_reference_wkids_unions_both_keys() -> None:
    assert arcgis_access.spatial_reference.spatial_reference_wkids({
        "wkid": tests.helpers.factories.geography.WGS84_WKID,
        "latestWkid": tests.helpers.factories.geography.WEB_MERCATOR_WKID,
    }) == {
        tests.helpers.factories.geography.WGS84_WKID,
        tests.helpers.factories.geography.WEB_MERCATOR_WKID,
    }


def test_layer_wkids_no_reported_references_is_empty() -> None:
    layer = tests.helpers.doubles.arcgis.LayerStub(properties={})
    assert arcgis_access.spatial_reference.layer_wkids(layer) == set()


def test_layer_wkids_from_layer_properties() -> None:
    layer = tests.helpers.doubles.arcgis.LayerStub(
        properties={
            "spatialReference": {"wkid": tests.helpers.factories.geography.WGS84_WKID},
        },
    )
    assert arcgis_access.spatial_reference.layer_wkids(layer) == {
        tests.helpers.factories.geography.WGS84_WKID,
    }


def test_layer_wkids_from_extents() -> None:
    layer = tests.helpers.doubles.arcgis.LayerStub(
        properties={
            "extent": {
                "spatialReference": {
                    "wkid": tests.helpers.factories.geography.WGS84_WKID,
                },
            },
            "fullExtent": {
                "spatialReference": {
                    "wkid": tests.helpers.factories.geography.NAD83_WKID,
                },
            },
            "initialExtent": {
                "spatialReference": {
                    "latestWkid": tests.helpers.factories.geography.WEB_MERCATOR_WKID,
                },
            },
        },
    )
    assert arcgis_access.spatial_reference.layer_wkids(layer) == {
        tests.helpers.factories.geography.WGS84_WKID,
        tests.helpers.factories.geography.NAD83_WKID,
        tests.helpers.factories.geography.WEB_MERCATOR_WKID,
    }


def test_layer_wkids_ignores_non_dict_spatial_reference() -> None:
    layer = tests.helpers.doubles.arcgis.LayerStub(
        properties={"spatialReference": "EPSG:4326"},
    )
    assert arcgis_access.spatial_reference.layer_wkids(layer) == set()


def test_bounds_of_empty_list_is_none() -> None:
    assert arcgis_access.spatial_reference.bounds_of([]) is None


def test_bounds_of_all_null_geometries_is_none() -> None:
    geometries: list[shapely.Geometry | None] = [None, None]
    assert arcgis_access.spatial_reference.bounds_of(geometries) is None


def test_bounds_of_single_point() -> None:
    geometries: list[shapely.Geometry | None] = [shapely.geometry.Point(1.0, 2.0)]
    assert arcgis_access.spatial_reference.bounds_of(geometries) == (
        1.0,
        1.0,
        2.0,
        2.0,
    )


def test_bounds_of_multiple_points() -> None:
    geometries: list[shapely.Geometry | None] = [
        shapely.geometry.Point(1.0, 2.0),
        shapely.geometry.Point(3.0, 4.0),
    ]
    assert arcgis_access.spatial_reference.bounds_of(geometries) == (
        1.0,
        3.0,
        2.0,
        4.0,
    )


def test_bounds_of_ignores_null_geometries() -> None:
    geometries: list[shapely.Geometry | None] = [
        None,
        shapely.geometry.Point(-1.0, -2.0),
        shapely.geometry.Point(3.0, 4.0),
    ]
    assert arcgis_access.spatial_reference.bounds_of(geometries) == (
        -1.0,
        3.0,
        -2.0,
        4.0,
    )


def test_bounds_of_polygon() -> None:
    polygon = shapely.geometry.Polygon([
        (0.0, 0.0),
        (10.0, 0.0),
        (10.0, 5.0),
        (0.0, 5.0),
    ])
    geometries: list[shapely.Geometry | None] = [polygon]
    assert arcgis_access.spatial_reference.bounds_of(geometries) == (
        0.0,
        10.0,
        0.0,
        5.0,
    )


def test_projected_maximum_magnitude_in_crs_units_web_mercator() -> None:
    crs = pyproj.CRS.from_epsg(tests.helpers.factories.geography.WEB_MERCATOR_WKID)
    assert arcgis_access.spatial_reference.projected_maximum_magnitude_in_crs_units(
        crs,
    ) == pytest.approx(tests.helpers.factories.geography.WEB_MERCATOR_MAXIMUM_MAGNITUDE)


@pytest.mark.parametrize(
    "coordinates",
    [(float("inf"), 1.0), (1.0, float("inf")), (float("nan"), float("nan"))],
)
def test_projected_maximum_magnitude_in_crs_units_ignores_nonfinite_corners(
    monkeypatch: pytest.MonkeyPatch,
    coordinates: tuple[float, float],
) -> None:
    transformer = unittest.mock.Mock(spec=pyproj.Transformer)
    transformer.transform.side_effect = [
        coordinates,
        (-20.0, 10.0),
        (5.0, -30.0),
        (1.0, 2.0),
    ]
    monkeypatch.setattr(
        pyproj.Transformer,
        "from_crs",
        lambda *_args, **_kwargs: transformer,
    )
    crs = pyproj.CRS.from_epsg(tests.helpers.factories.geography.WEB_MERCATOR_WKID)
    assert arcgis_access.spatial_reference.projected_maximum_magnitude_in_crs_units(
        crs,
    ) == pytest.approx(30.0)


def test_projected_maximum_magnitude_in_crs_units_falls_back_for_nonfinite_corners(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transformer = unittest.mock.Mock(spec=pyproj.Transformer)
    transformer.transform.return_value = (float("inf"), float("inf"))
    monkeypatch.setattr(
        pyproj.Transformer,
        "from_crs",
        lambda *_args, **_kwargs: transformer,
    )
    crs = pyproj.CRS.from_epsg(tests.helpers.factories.geography.WEB_MERCATOR_WKID)
    assert arcgis_access.spatial_reference.projected_maximum_magnitude_in_crs_units(
        crs,
    ) == arcgis_access.spatial_reference.PROJECTED_MAXIMUM_MAGNITUDE_FALLBACK.m_as(
        "meters",
    )


def test_projected_maximum_magnitude_in_crs_units_fallback_without_area_of_use() -> (
    None
):
    crs = pyproj.CRS.from_proj4("+proj=aeqd +lat_0=0 +lon_0=0 +datum=WGS84 +units=m")
    assert arcgis_access.spatial_reference.projected_maximum_magnitude_in_crs_units(
        crs,
    ) == arcgis_access.spatial_reference.PROJECTED_MAXIMUM_MAGNITUDE_FALLBACK.m_as(
        "meters",
    )


def test_projected_maximum_magnitude_in_crs_units_uses_fallback_when_transforms_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        pyproj.Transformer,
        "from_crs",
        tests.helpers.doubles.pyproj.failing_from_crs,
    )
    crs = pyproj.CRS.from_epsg(tests.helpers.factories.geography.WEB_MERCATOR_WKID)
    assert arcgis_access.spatial_reference.projected_maximum_magnitude_in_crs_units(
        crs,
    ) == arcgis_access.spatial_reference.PROJECTED_MAXIMUM_MAGNITUDE_FALLBACK.m_as(
        "meters",
    )


def test_spatial_reference_domain_geographic() -> None:
    domain = arcgis_access.spatial_reference.spatial_reference_domain(
        tests.helpers.factories.geography.WGS84_WKID,
    )
    assert domain is not None
    assert domain.crs.is_geographic
    assert domain.bands == (0.0, 180.0, 0.0, 90.0)
    assert domain.description == "geographic (degrees)"


def test_spatial_reference_domain_projected() -> None:
    domain = arcgis_access.spatial_reference.spatial_reference_domain(
        tests.helpers.factories.geography.WEB_MERCATOR_WKID,
    )
    assert domain is not None
    assert domain.crs.is_projected
    x_minimum_band, x_maximum_band, y_minimum_band, y_maximum_band = domain.bands
    assert (
        x_minimum_band
        == arcgis_access.spatial_reference.MINIMUM_PROJECTED_MAGNITUDE.m_as(
            "meter",
        )
    )
    assert x_maximum_band == pytest.approx(
        tests.helpers.factories.geography.WEB_MERCATOR_MAXIMUM_MAGNITUDE.m_as("meters"),
    )
    assert (
        y_minimum_band
        == arcgis_access.spatial_reference.MINIMUM_PROJECTED_MAGNITUDE.m_as(
            "meter",
        )
    )
    assert y_maximum_band == pytest.approx(
        tests.helpers.factories.geography.WEB_MERCATOR_MAXIMUM_MAGNITUDE.m_as("meters"),
    )
    assert domain.description == "projected (metre)"


def test_spatial_reference_domain_unknown_wkid_is_none() -> None:
    assert (
        arcgis_access.spatial_reference.spatial_reference_domain(
            tests.helpers.factories.geography.UNKNOWN_WKID,
        )
        is None
    )


def test_spatial_reference_domain_vertical_crs_is_none() -> None:
    assert (
        arcgis_access.spatial_reference.spatial_reference_domain(
            tests.helpers.factories.geography.NAVD88_HEIGHT_WKID,
        )
        is None
    )


def test_axis_fits_within_band() -> None:
    assert arcgis_access.spatial_reference.axis_fits(10.0, 20.0, 5.0, 30.0)


def test_axis_fits_exact_boundaries() -> None:
    assert arcgis_access.spatial_reference.axis_fits(5.0, 30.0, 5.0, 30.0)


def test_axis_fits_exceeds_maximum_magnitude() -> None:
    assert not arcgis_access.spatial_reference.axis_fits(10.0, 31.0, 5.0, 30.0)


def test_axis_fits_below_minimum_magnitude() -> None:
    assert not arcgis_access.spatial_reference.axis_fits(4.0, 20.0, 5.0, 30.0)


def test_axis_fits_crosses_zero_with_positive_minimum() -> None:
    assert not arcgis_access.spatial_reference.axis_fits(-5.0, 5.0, 5.0, 30.0)


def test_axis_fits_zero_crossing_allowed_when_minimum_is_zero() -> None:
    assert arcgis_access.spatial_reference.axis_fits(-5.0, 5.0, 0.0, 30.0)


def test_coordinates_match_domain_when_all_axes_fit() -> None:
    domain = (1_000.0, 20_000_000.0, 1_000.0, 20_000_000.0)
    bounds = (2_000_000.0, 3_000_000.0, 4_000_000.0, 5_000_000.0)
    assert arcgis_access.spatial_reference.coordinates_match_domain(domain, bounds)


def test_coordinates_match_domain_x_axis_too_small() -> None:
    domain = (1_000.0, 20_000_000.0, 1_000.0, 20_000_000.0)
    bounds = (100.0, 3_000_000.0, 4_000_000.0, 5_000_000.0)
    assert not arcgis_access.spatial_reference.coordinates_match_domain(
        domain,
        bounds,
    )


def test_coordinates_match_domain_y_axis_too_large() -> None:
    domain = (1_000.0, 20_000_000.0, 1_000.0, 20_000_000.0)
    bounds = (2_000_000.0, 3_000_000.0, 4_000_000.0, 50_000_000.0)
    assert not arcgis_access.spatial_reference.coordinates_match_domain(
        domain,
        bounds,
    )


def test_longitudes_in_area_inside_normal_area() -> None:
    assert arcgis_access.spatial_reference.longitudes_in_area(
        -124.45,
        -114.12,
        -120.0,
        -119.0,
    )


def test_longitudes_in_area_outside_normal_area_west() -> None:
    assert not arcgis_access.spatial_reference.longitudes_in_area(
        -124.45,
        -114.12,
        -125.0,
        -124.0,
    )


def test_longitudes_in_area_outside_normal_area_east() -> None:
    assert not arcgis_access.spatial_reference.longitudes_in_area(
        -124.45,
        -114.12,
        -113.0,
        -112.0,
    )


def test_longitudes_in_area_inside_wrap_east_side() -> None:
    assert arcgis_access.spatial_reference.longitudes_in_area(
        167.65,
        -40.73,
        175.0,
        179.0,
    )


def test_longitudes_in_area_inside_wrap_west_side() -> None:
    assert arcgis_access.spatial_reference.longitudes_in_area(
        167.65,
        -40.73,
        -170.0,
        -160.0,
    )


def test_longitudes_in_area_outside_area_wrapping_antimeridian() -> None:
    assert not arcgis_access.spatial_reference.longitudes_in_area(
        167.65,
        -40.73,
        0.0,
        10.0,
    )


def test_longitudes_in_area_exact_point_in_normal_area() -> None:
    assert arcgis_access.spatial_reference.longitudes_in_area(
        -120.0,
        -120.0,
        -120.0,
        -120.0,
    )


def test_coordinates_in_area_unknown_area_of_use_matches() -> None:
    crs = pyproj.CRS.from_proj4("+proj=aeqd +lat_0=0 +lon_0=0 +datum=WGS84 +units=m")
    assert arcgis_access.spatial_reference.coordinates_in_area(
        crs,
        (-124.45, -114.12, 32.53, 42.01),
    )


def test_coordinates_in_area_inside_california_albers() -> None:
    crs = pyproj.CRS.from_epsg(tests.helpers.factories.geography.CALIFORNIA_ALBERS_WKID)
    assert arcgis_access.spatial_reference.coordinates_in_area(
        crs,
        tests.helpers.factories.arcgis_access.spatial_reference.CALIFORNIA_BOUNDS,
    )


def test_coordinates_in_area_outside_california_albers() -> None:
    crs = pyproj.CRS.from_epsg(tests.helpers.factories.geography.CALIFORNIA_ALBERS_WKID)
    assert not arcgis_access.spatial_reference.coordinates_in_area(
        crs,
        (-99.0, -98.0, 30.0, 31.0),
    )


def test_coordinates_in_area_inside_area_wrapping_antimeridian() -> None:
    crs = pyproj.CRS.from_epsg(tests.helpers.factories.geography.NAD83_WKID)
    assert arcgis_access.spatial_reference.coordinates_in_area(
        crs,
        (-170.0, -160.0, 55.0, 65.0),
    )


def test_coordinates_in_area_outside_area_wrapping_antimeridian() -> None:
    crs = pyproj.CRS.from_epsg(tests.helpers.factories.geography.NAD83_WKID)
    assert not arcgis_access.spatial_reference.coordinates_in_area(
        crs,
        (150.0, 151.0, -35.0, -34.0),
    )


def test_coordinates_in_area_latitude_outside_wrapping_area() -> None:
    crs = pyproj.CRS.from_epsg(tests.helpers.factories.geography.NAD83_WKID)
    assert not arcgis_access.spatial_reference.coordinates_in_area(
        crs,
        (-170.0, -160.0, 0.0, 5.0),
    )


def test_area_of_use_text_formats_bounds() -> None:
    crs = pyproj.CRS.from_epsg(tests.helpers.factories.geography.CALIFORNIA_ALBERS_WKID)
    assert (
        arcgis_access.spatial_reference.area_of_use_text(crs)
        == "longitude -124.45..-114.12, latitude 32.53..42.01"
    )


def test_area_of_use_text_unknown() -> None:
    crs = pyproj.CRS.from_proj4("+proj=aeqd +lat_0=0 +lon_0=0 +datum=WGS84 +units=m")
    assert arcgis_access.spatial_reference.area_of_use_text(crs) == "unknown"


def test_choose_spatial_reference_id_no_reported_wkids_fails() -> None:
    layer = tests.helpers.doubles.arcgis.LayerStub(properties={})
    feature_set = tests.helpers.doubles.arcgis.FeatureSetStub(spatial_reference={})
    with pytest.raises(
        arcgis_access.exceptions.NoSpatialReferenceError,
        match="no spatial reference wkid reported by the layer or its query",
    ):
        arcgis_access.spatial_reference.choose_spatial_reference_id(
            layer,
            feature_set,
            None,
        )


def test_choose_spatial_reference_id_single_candidate_without_geometry() -> None:
    layer = tests.helpers.doubles.arcgis.LayerStub(
        properties={
            "spatialReference": {"wkid": tests.helpers.factories.geography.WGS84_WKID},
        },
    )
    feature_set = tests.helpers.doubles.arcgis.FeatureSetStub(spatial_reference=None)
    assert (
        arcgis_access.spatial_reference.choose_spatial_reference_id(
            layer,
            feature_set,
            None,
        )
        == tests.helpers.factories.geography.WGS84_WKID
    )


def test_choose_spatial_reference_id_multiple_candidates_without_geometry_fails() -> (
    None
):
    layer = tests.helpers.doubles.arcgis.LayerStub(
        properties={
            "spatialReference": {"wkid": tests.helpers.factories.geography.WGS84_WKID},
        },
    )
    feature_set = tests.helpers.doubles.arcgis.FeatureSetStub(
        spatial_reference={"wkid": tests.helpers.factories.geography.NAD83_WKID},
    )
    with pytest.raises(
        arcgis_access.exceptions.NoSpatialReferenceError,
        match="no feature geometry is available to check them",
    ):
        arcgis_access.spatial_reference.choose_spatial_reference_id(
            layer,
            feature_set,
            None,
        )


def test_choose_spatial_reference_id_uses_query_spatial_reference() -> None:
    layer = tests.helpers.doubles.arcgis.LayerStub(properties={})
    feature_set = tests.helpers.doubles.arcgis.FeatureSetStub(
        spatial_reference={"wkid": tests.helpers.factories.geography.WGS84_WKID},
    )
    bounds = tests.helpers.factories.arcgis_access.spatial_reference.CALIFORNIA_BOUNDS
    chosen = arcgis_access.spatial_reference.choose_spatial_reference_id(
        layer,
        feature_set,
        bounds,
    )
    assert chosen == tests.helpers.factories.geography.WGS84_WKID


def test_choose_spatial_reference_id_single_match_without_exclusions_is_quiet() -> None:
    layer = tests.helpers.doubles.arcgis.LayerStub(
        properties={
            "spatialReference": {"wkid": tests.helpers.factories.geography.WGS84_WKID},
        },
    )
    feature_set = tests.helpers.doubles.arcgis.FeatureSetStub(spatial_reference=None)
    bounds = tests.helpers.factories.arcgis_access.spatial_reference.CALIFORNIA_BOUNDS
    with structlog.testing.capture_logs() as captured:
        chosen = arcgis_access.spatial_reference.choose_spatial_reference_id(
            layer,
            feature_set,
            bounds,
        )
    assert chosen == tests.helpers.factories.geography.WGS84_WKID
    assert captured == []


@pytest.mark.parametrize(
    ("properties", "bounds", "expected_substrings"),
    [
        pytest.param(
            {
                "spatialReference": {
                    "wkid": tests.helpers.factories.geography.WGS84_WKID,
                    "latestWkid": tests.helpers.factories.geography.WEB_MERCATOR_WKID,
                },
            },
            tests.helpers.factories.arcgis_access.spatial_reference.CALIFORNIA_BOUNDS,
            ["picked spatial reference EPSG:4326", "excluded 3857"],
            id="projected",
        ),
        pytest.param(
            {
                "spatialReference": {
                    "wkid": tests.helpers.factories.geography.WGS84_WKID,
                    "latestWkid": tests.helpers.factories.geography.NAD83_WKID,
                },
            },
            (150.0, 151.0, -35.0, -34.0),
            ["excluded 4269", "coordinates outside its area of use"],
            id="out_of_area",
        ),
        pytest.param(
            {
                "spatialReference": {
                    "wkid": tests.helpers.factories.geography.WGS84_WKID,
                    "latestWkid": tests.helpers.factories.geography.UNKNOWN_WKID,
                },
            },
            tests.helpers.factories.arcgis_access.spatial_reference.CALIFORNIA_BOUNDS,
            ["no expected coordinate range known"],
            id="unknown_wkid",
        ),
    ],
)
def test_choose_spatial_reference_id_reports_excluded_candidate(
    properties: dict[str, object],
    bounds: tuple[float, float, float, float],
    expected_substrings: list[str],
) -> None:
    layer = tests.helpers.doubles.arcgis.LayerStub(properties=properties)
    feature_set = tests.helpers.doubles.arcgis.FeatureSetStub(spatial_reference=None)
    with structlog.testing.capture_logs() as captured:
        chosen = arcgis_access.spatial_reference.choose_spatial_reference_id(
            layer,
            feature_set,
            bounds,
        )
    assert chosen == tests.helpers.factories.geography.WGS84_WKID
    assert len(captured) == 1
    for substring in expected_substrings:
        assert substring in captured[0]["event"]


def test_choose_spatial_reference_id_fails_when_no_candidate_matches() -> None:
    layer = tests.helpers.doubles.arcgis.LayerStub(
        properties={
            "spatialReference": {
                "wkid": tests.helpers.factories.geography.WEB_MERCATOR_WKID,
            },
        },
    )
    feature_set = tests.helpers.doubles.arcgis.FeatureSetStub(spatial_reference=None)
    bounds = tests.helpers.factories.arcgis_access.spatial_reference.CALIFORNIA_BOUNDS
    with pytest.raises(
        arcgis_access.exceptions.NoSpatialReferenceError,
        match="no reported spatial reference wkid matches",
    ):
        arcgis_access.spatial_reference.choose_spatial_reference_id(
            layer,
            feature_set,
            bounds,
        )


def test_choose_spatial_reference_id_fails_when_several_candidates_match() -> None:
    layer = tests.helpers.doubles.arcgis.LayerStub(
        properties={
            "spatialReference": {
                "wkid": tests.helpers.factories.geography.WGS84_WKID,
                "latestWkid": tests.helpers.factories.geography.NAD83_WKID,
            },
        },
    )
    feature_set = tests.helpers.doubles.arcgis.FeatureSetStub(spatial_reference=None)
    bounds = tests.helpers.factories.arcgis_access.spatial_reference.CALIFORNIA_BOUNDS
    with pytest.raises(
        arcgis_access.exceptions.NoSpatialReferenceError,
        match="ambiguous spatial reference",
    ):
        arcgis_access.spatial_reference.choose_spatial_reference_id(
            layer,
            feature_set,
            bounds,
        )


def test_select_spatial_reference_wkid_no_candidates() -> None:
    selection = arcgis_access.spatial_reference.select_spatial_reference_wkid(
        set(),
        None,
    )
    assert selection.wkid is None
    assert (
        selection.failure_message
        == "no spatial reference wkid reported by the layer or its query"
    )


def test_select_spatial_reference_wkid_single_candidate_without_bounds() -> None:
    selection = arcgis_access.spatial_reference.select_spatial_reference_wkid(
        {tests.helpers.factories.geography.WGS84_WKID},
        None,
    )
    assert selection.wkid == tests.helpers.factories.geography.WGS84_WKID
    assert selection.warning is None
    assert selection.failure_message == ""


def test_select_spatial_reference_wkid_ambiguous_without_bounds() -> None:
    selection = arcgis_access.spatial_reference.select_spatial_reference_wkid(
        {
            tests.helpers.factories.geography.WGS84_WKID,
            tests.helpers.factories.geography.NAD83_WKID,
        },
        None,
    )
    assert selection.wkid is None
    assert selection.failure_message is not None
    assert "cannot determine spatial reference" in selection.failure_message


def test_select_spatial_reference_wkid_single_match_keeps_exclusions() -> None:
    selection = arcgis_access.spatial_reference.select_spatial_reference_wkid(
        {
            tests.helpers.factories.geography.WGS84_WKID,
            tests.helpers.factories.geography.WEB_MERCATOR_WKID,
        },
        tests.helpers.factories.arcgis_access.spatial_reference.CALIFORNIA_BOUNDS,
    )
    assert selection.wkid == tests.helpers.factories.geography.WGS84_WKID
    assert selection.failure_message == ""
    assert selection.warning is not None
    assert "3857" in selection.warning


def test_select_spatial_reference_wkid_no_match_reports_exclusions() -> None:
    selection = arcgis_access.spatial_reference.select_spatial_reference_wkid(
        {tests.helpers.factories.geography.WEB_MERCATOR_WKID},
        tests.helpers.factories.arcgis_access.spatial_reference.CALIFORNIA_BOUNDS,
    )
    assert selection.wkid is None
    assert selection.failure_message is not None
    assert "no reported spatial reference wkid matches" in selection.failure_message
    assert "3857" in selection.failure_message


def test_select_spatial_reference_wkid_ambiguous_with_bounds() -> None:
    selection = arcgis_access.spatial_reference.select_spatial_reference_wkid(
        {
            tests.helpers.factories.geography.WGS84_WKID,
            tests.helpers.factories.geography.NAD83_WKID,
        },
        tests.helpers.factories.arcgis_access.spatial_reference.CALIFORNIA_BOUNDS,
    )
    assert selection.wkid is None
    assert selection.failure_message is not None
    assert "ambiguous spatial reference" in selection.failure_message


def test_select_spatial_reference_wkid_single_out_of_area_candidate_is_chosen() -> None:
    selection = arcgis_access.spatial_reference.select_spatial_reference_wkid(
        {tests.helpers.factories.geography.NAD83_WKID},
        tests.helpers.factories.arcgis_access.spatial_reference.OUTSIDE_NAD83_AREA_BOUNDS,
    )
    assert selection.wkid == tests.helpers.factories.geography.NAD83_WKID
    assert selection.failure_message == ""
    assert selection.warning is not None
    assert "picked spatial reference EPSG:4269" in selection.warning
    assert "coordinates fall outside its area of use" in selection.warning


def test_select_spatial_reference_wkid_multiple_out_of_area_candidates_fail() -> None:
    selection = arcgis_access.spatial_reference.select_spatial_reference_wkid(
        {
            tests.helpers.factories.geography.NAD83_WKID,
            tests.helpers.factories.geography.NAD83_2011_WKID,
        },
        tests.helpers.factories.arcgis_access.spatial_reference.OUTSIDE_NAD83_AREA_BOUNDS,
    )
    assert selection.wkid is None
    assert selection.failure_message is not None
    assert "no reported spatial reference wkid matches" in selection.failure_message
    assert "coordinates outside its area of use" in selection.failure_message


def test_choose_spatial_reference_id_single_out_of_area_candidate_logs_warning() -> (
    None
):
    layer = tests.helpers.doubles.arcgis.LayerStub(
        properties={
            "spatialReference": {"wkid": tests.helpers.factories.geography.NAD83_WKID},
        },
    )
    feature_set = tests.helpers.doubles.arcgis.FeatureSetStub(spatial_reference=None)
    with structlog.testing.capture_logs() as captured:
        chosen = arcgis_access.spatial_reference.choose_spatial_reference_id(
            layer,
            feature_set,
            tests.helpers.factories.arcgis_access.spatial_reference.OUTSIDE_NAD83_AREA_BOUNDS,
        )
    assert chosen == tests.helpers.factories.geography.NAD83_WKID
    assert len(captured) == 1
    assert captured[0]["log_level"] == "info"
    assert "area of use" in captured[0]["event"]
