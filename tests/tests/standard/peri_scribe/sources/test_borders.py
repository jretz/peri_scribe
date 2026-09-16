"""Tests for peri_scribe.sources.borders."""

from __future__ import annotations

import arcgis.features
import geopandas
import pyproj
import pytest
import shapely.geometry
import structlog

import peri_scribe.exceptions
import peri_scribe.models
import peri_scribe.sources.borders
import tests.helpers.doubles.peri_scribe.sources.administrative_boundaries
import tests.helpers.factories.peri_scribe.sources.administrative_boundaries


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
        tests.helpers.factories.peri_scribe.sources.administrative_boundaries.CALIFORNIA,
        tests.helpers.factories.peri_scribe.sources.administrative_boundaries.ARIZONA,
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
        tests.helpers.factories.peri_scribe.sources.administrative_boundaries.CALIFORNIA,
        neighbor,
    )
    assert not border.is_empty
    assert peri_scribe.sources.borders.total_line_length(border).m_as(
        "degree",
    ) == pytest.approx(10.0, abs=1e-3)


def test_shared_border_returns_multi_line_string_for_multiple_segments() -> None:
    neighbor = shapely.geometry.MultiPolygon([
        tests.helpers.factories.peri_scribe.sources.administrative_boundaries.ARIZONA,
        tests.helpers.factories.peri_scribe.sources.administrative_boundaries.OREGON,
    ])
    border = peri_scribe.sources.borders.shared_border(
        tests.helpers.factories.peri_scribe.sources.administrative_boundaries.CALIFORNIA,
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
            tests.helpers.factories.peri_scribe.sources.administrative_boundaries.CALIFORNIA,
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
            tests.helpers.factories.peri_scribe.sources.administrative_boundaries.ARIZONA,
            tests.helpers.factories.peri_scribe.sources.administrative_boundaries.NEVADA,
            tests.helpers.factories.peri_scribe.sources.administrative_boundaries.OREGON,
        ],
        crs=pyproj.CRS.from_epsg(4326),
    )
    border = peri_scribe.sources.borders.border_dataframe(
        tests.helpers.factories.peri_scribe.sources.administrative_boundaries.CALIFORNIA,
        neighbors,
    )
    assert list(border["NEIGHBOR"]) == neighbor_state_names
    assert list(border["NEIGHBOR_ABBR"]) == neighbor_state_abbreviations
    assert border.geometry.name == "geom"
    assert border.crs.to_epsg() == peri_scribe.models.WGS84_SPATIAL_REFERENCE_ID
    assert all(border["LENGTH_KM"] > 0)


def test_layer_dataframe_queries_features_in_wgs84() -> None:
    feature_set = (
        tests.helpers.factories.peri_scribe.sources.administrative_boundaries
    ).polygon_feature_set(
        [tests.helpers.factories.peri_scribe.sources.administrative_boundaries.ARIZONA],
        ["Arizona"],
        ["AZ"],
    )
    layer = (
        tests.helpers.doubles.peri_scribe.sources.administrative_boundaries
    ).FeatureLayerStub(
        feature_set,
    )
    dataframe = peri_scribe.sources.borders.layer_dataframe(
        tests.helpers.doubles.peri_scribe.sources.administrative_boundaries.as_feature_layer(
            layer,
        ),
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
    layer = (
        tests.helpers.doubles.peri_scribe.sources.administrative_boundaries
    ).FeatureLayerStub(
        arcgis.features.FeatureSet([]),
    )
    with pytest.raises(
        peri_scribe.exceptions.AdministrativeBoundariesError,
        match="returned no features",
    ):
        peri_scribe.sources.borders.layer_dataframe(
            tests.helpers.doubles.peri_scribe.sources.administrative_boundaries.as_feature_layer(
                layer,
            ),
            "California",
            where="STATE_ABBR='CA'",
        )


def test_layer_dataframe_logs_warning_when_geometry_missing() -> None:
    layer = (
        tests.helpers.doubles.peri_scribe.sources.administrative_boundaries
    ).FeatureLayerStub(
        tests.helpers.doubles.peri_scribe.sources.administrative_boundaries.GeometrylessFeatureSetStub(
            1,
        ),
    )
    with structlog.testing.capture_logs() as captured:
        dataframe = peri_scribe.sources.borders.layer_dataframe(
            tests.helpers.doubles.peri_scribe.sources.administrative_boundaries.as_feature_layer(
                layer,
            ),
            "California",
            where="STATE_ABBR='CA'",
        )
    assert len(dataframe) == 1
    assert dataframe.geometry.iloc[0] is None
    assert captured[0]["event"] == (
        "  warning: all features lack geometry; writing the layer with NULL geometry"
    )


def test_boundary_geometries_queries_california_and_neighbors_once() -> None:
    layer = (
        tests.helpers.doubles.peri_scribe.sources.administrative_boundaries
    ).FeatureLayerStub(
        tests.helpers.factories.peri_scribe.sources.administrative_boundaries.polygon_feature_set(
            [
                tests.helpers.factories.peri_scribe.sources.administrative_boundaries.CALIFORNIA,
                tests.helpers.factories.peri_scribe.sources.administrative_boundaries.ARIZONA,
                tests.helpers.factories.peri_scribe.sources.administrative_boundaries.NEVADA,
                tests.helpers.factories.peri_scribe.sources.administrative_boundaries.OREGON,
            ],
            ["California", "Arizona", "Nevada", "Oregon"],
            ["CA", "AZ", "NV", "OR"],
        ),
    )
    states = peri_scribe.sources.borders.boundary_geometries(
        tests.helpers.doubles.peri_scribe.sources.administrative_boundaries.as_feature_layer(
            layer,
        ),
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
    layer = (
        tests.helpers.doubles.peri_scribe.sources.administrative_boundaries
    ).FeatureLayerStub(
        tests.helpers.factories.peri_scribe.sources.administrative_boundaries.polygon_feature_set(
            [
                tests.helpers.factories.peri_scribe.sources.administrative_boundaries.CALIFORNIA,
                tests.helpers.factories.peri_scribe.sources.administrative_boundaries.ARIZONA,
                tests.helpers.factories.peri_scribe.sources.administrative_boundaries.NEVADA,
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
            tests.helpers.doubles.peri_scribe.sources.administrative_boundaries.as_feature_layer(
                layer,
            ),
        )


def test_boundary_geometries_raises_when_geometry_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    states = geopandas.GeoDataFrame(
        {"STATE_ABBR": ["CA", "AZ", "NV", "OR"]},
        geometry=[
            tests.helpers.factories.peri_scribe.sources.administrative_boundaries.CALIFORNIA,
            tests.helpers.factories.peri_scribe.sources.administrative_boundaries.ARIZONA,
            tests.helpers.factories.peri_scribe.sources.administrative_boundaries.NEVADA,
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
            tests.helpers.doubles.peri_scribe.sources.administrative_boundaries.as_feature_layer(
                object(),
            ),
        )


def test_california_geometry_from_states_raises_when_missing() -> None:
    states = geopandas.GeoDataFrame(
        {"STATE_ABBR": ["AZ", "NV", "OR"]},
        geometry=[
            tests.helpers.factories.peri_scribe.sources.administrative_boundaries.ARIZONA,
            tests.helpers.factories.peri_scribe.sources.administrative_boundaries.NEVADA,
            tests.helpers.factories.peri_scribe.sources.administrative_boundaries.OREGON,
        ],
        crs=pyproj.CRS.from_epsg(4326),
    )
    with pytest.raises(
        peri_scribe.exceptions.AdministrativeBoundariesError,
        match="Expected one California feature, got 0",
    ):
        peri_scribe.sources.borders.california_geometry_from_states(states)


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


def test_ordered_border_coordinates_rejects_an_isolated_triangle() -> None:
    parts = [
        shapely.LineString([(0, 0), (1, 0)]),
        shapely.LineString([(2, 0), (3, 0), (3, 1), (2, 0)]),
    ]
    with pytest.raises(
        peri_scribe.exceptions.AdministrativeBoundariesError,
        match="not a single continuous path",
    ):
        peri_scribe.sources.borders.ordered_border_coordinates(parts)


def test_ordered_border_coordinates_rejects_a_loop_attached_to_a_path() -> None:
    parts = [
        shapely.LineString([(0, 0), (1, 0), (2, 0)]),
        shapely.LineString([(1, 0), (1, 1), (2, 1), (1, 0)]),
    ]
    with pytest.raises(
        peri_scribe.exceptions.AdministrativeBoundariesError,
        match="not a single continuous path",
    ):
        peri_scribe.sources.borders.ordered_border_coordinates(parts)


def test_california_box_polygon_contains_california() -> None:
    box = peri_scribe.sources.borders.california_box_polygon(
        tests.helpers.factories.peri_scribe.sources.administrative_boundaries.california_like_border(),
    )
    assert box.is_valid
    assert box.contains(shapely.geometry.Point(-120.0, 40.0))
    assert box.contains(shapely.geometry.Point(-123.0, 34.0))


def test_california_box_polygon_excludes_neighboring_states() -> None:
    box = peri_scribe.sources.borders.california_box_polygon(
        tests.helpers.factories.peri_scribe.sources.administrative_boundaries.california_like_border(),
    )
    assert not box.contains(shapely.geometry.Point(-117.0, 40.0))
    assert not box.contains(shapely.geometry.Point(-120.0, 43.0))


def test_california_box_polygon_absorbs_maritime_and_mexico() -> None:
    box = peri_scribe.sources.borders.california_box_polygon(
        tests.helpers.factories.peri_scribe.sources.administrative_boundaries.california_like_border(),
    )
    assert box.contains(shapely.geometry.Point(-116.0, 32.3))
    assert not box.contains(shapely.geometry.Point(-116.0, 30.0))
    assert not box.contains(shapely.geometry.Point(-127.0, 38.0))
