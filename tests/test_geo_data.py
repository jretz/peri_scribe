import arcgis.features
import pandas as pd
import pyproj
import pytest
import shapely
import shapely.geometry
import structlog

import peri_scribe.exceptions
import peri_scribe.geo_data
import peri_scribe.models
from tests.conftest import (
    SAMPLE_FEED_NAME,
    SAMPLE_FEED_URL,
    WGS84_WKID,
    LayerStub,
)


def test_extract_geometries_without_shape_column() -> None:
    dataframe = pd.DataFrame({"name": ["a", "b"]})
    attributes, geometries, geometry_warning = peri_scribe.geo_data.extract_geometries(
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
    attributes, geometries, geometry_warning = peri_scribe.geo_data.extract_geometries(
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
    result = peri_scribe.geo_data.geo_data_frame_from(
        dataframe,
        geometries,
        WGS84_WKID,
    )
    assert result.crs == pyproj.CRS.from_epsg(WGS84_WKID)
    assert result.geometry.name == peri_scribe.models.GEOMETRY_COLUMN_NAME
    assert list(result["name"]) == ["a", "b"]
    assert list(result.geometry) == geometries


def test_geo_data_frame_from_allows_null_geometries() -> None:
    dataframe = pd.DataFrame({"name": ["a"]})
    geometries: list[shapely.Geometry | None] = [None]
    result = peri_scribe.geo_data.geo_data_frame_from(
        dataframe,
        geometries,
        WGS84_WKID,
    )
    assert list(result.geometry) == [None]


def test_dataframe_for_layer_raises_no_features_error_when_feed_is_empty() -> None:
    feed = peri_scribe.models.ArcGISFeed(url=SAMPLE_FEED_URL)
    layer = LayerStub(properties={})
    feature_set = arcgis.features.FeatureSet([])
    with pytest.raises(
        peri_scribe.exceptions.NoFeaturesError,
        match=(
            f"Feed {SAMPLE_FEED_NAME} returned no features; "
            f"{peri_scribe.models.OUTPUT_FILENAME} was not modified"
        ),
    ):
        peri_scribe.geo_data.dataframe_for_layer(feed, layer, feature_set)


def test_dataframe_for_layer_builds_geo_data_frame(
    feature_set_with_geometry: arcgis.features.FeatureSet,
) -> None:
    feed = peri_scribe.models.ArcGISFeed(url=SAMPLE_FEED_URL)
    layer = LayerStub(properties={"spatialReference": {"wkid": WGS84_WKID}})
    result = peri_scribe.geo_data.dataframe_for_layer(
        feed,
        layer,
        feature_set_with_geometry,
    )
    assert result.crs == pyproj.CRS.from_epsg(WGS84_WKID)
    assert result.geometry.name == peri_scribe.models.GEOMETRY_COLUMN_NAME
    assert list(result["name"]) == ["a", "b"]
    assert list(result.geometry) == [
        shapely.geometry.Point(1.0, 2.0),
        shapely.geometry.Point(3.0, 4.0),
    ]


def test_dataframe_for_layer_warns_when_features_lack_geometry() -> None:
    feed = peri_scribe.models.ArcGISFeed(url=SAMPLE_FEED_URL)
    layer = LayerStub(properties={"spatialReference": {"wkid": WGS84_WKID}})
    feature_set = arcgis.features.FeatureSet(
        [
            arcgis.features.Feature(attributes={"name": "a"}),
            arcgis.features.Feature(attributes={"name": "b"}),
        ],
    )
    with structlog.testing.capture_logs() as captured:
        result = peri_scribe.geo_data.dataframe_for_layer(feed, layer, feature_set)
    assert len(captured) == 1
    assert captured[0]["log_level"] == "warning"
    assert "all features lack geometry" in captured[0]["event"]
    assert list(result.geometry) == [None, None]
