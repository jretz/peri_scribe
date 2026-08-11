import re

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
import peri_scribe.retry
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
    feed = peri_scribe.models.build_feeds([
        {"feed_type": "ArcGISFeed", "url": SAMPLE_FEED_URL},
    ])[0]
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
    feed = peri_scribe.models.build_feeds([
        {"feed_type": "ArcGISFeed", "url": SAMPLE_FEED_URL},
    ])[0]
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
    feed = peri_scribe.models.build_feeds([
        {"feed_type": "ArcGISFeed", "url": SAMPLE_FEED_URL},
    ])[0]
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


RATE_LIMIT_RETRY_AFTER_SECONDS = 60
RATE_LIMIT_ERROR_BODY = (
    "{'error': {'code': 429, 'message': 'Unable to perform query. "
    "Too many requests.', 'details': ['API calls quota exceeded "
    "(120975 request units)! maximum allowed request units (115200) "
    f"per Minute. Retry after {RATE_LIMIT_RETRY_AFTER_SECONDS} sec.']}}"
)
LOOSE_429_ERROR_BODY = "{'error': {'code': 429, 'message': 'Too many requests.'}}"


class QueryStub:
    """Callable that returns or raises successive outcomes from a list."""

    def __init__(self, outcomes: list[arcgis.features.FeatureSet | Exception]) -> None:
        self.outcomes = list(outcomes)
        self.call_count = 0

    def query(self) -> arcgis.features.FeatureSet:
        outcome = self.outcomes[self.call_count]
        self.call_count += 1
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def test_query_with_retry_succeeds_on_first_attempt(
    monkeypatch: pytest.MonkeyPatch,
    feature_set_with_geometry: arcgis.features.FeatureSet,
) -> None:
    sleep_calls: list[float] = []
    monkeypatch.setattr(peri_scribe.geo_data.time, "sleep", sleep_calls.append)
    outcomes: list[arcgis.features.FeatureSet | Exception] = [
        feature_set_with_geometry,
    ]
    layer = QueryStub(outcomes)
    result = peri_scribe.geo_data.query_with_retry(
        SAMPLE_FEED_NAME,
        layer,  # ty: ignore
    )
    assert result is feature_set_with_geometry
    assert sleep_calls == []


def test_query_with_retry_retries_on_429_with_retry_after(
    monkeypatch: pytest.MonkeyPatch,
    feature_set_with_geometry: arcgis.features.FeatureSet,
) -> None:
    sleep_calls: list[float] = []
    monkeypatch.setattr(peri_scribe.geo_data.time, "sleep", sleep_calls.append)
    rate_limit_error = ValueError(RATE_LIMIT_ERROR_BODY)
    outcomes: list[arcgis.features.FeatureSet | Exception] = [
        rate_limit_error,
        feature_set_with_geometry,
    ]
    layer = QueryStub(outcomes)
    result = peri_scribe.geo_data.query_with_retry(
        SAMPLE_FEED_NAME,
        layer,  # ty: ignore
    )
    assert result is feature_set_with_geometry
    assert sleep_calls == [60.0]


def test_query_with_retry_retries_on_loose_429(
    monkeypatch: pytest.MonkeyPatch,
    feature_set_with_geometry: arcgis.features.FeatureSet,
) -> None:
    sleep_calls: list[float] = []
    monkeypatch.setattr(peri_scribe.geo_data.time, "sleep", sleep_calls.append)
    loose_429_error = ValueError(LOOSE_429_ERROR_BODY)
    outcomes: list[arcgis.features.FeatureSet | Exception] = [
        loose_429_error,
        feature_set_with_geometry,
    ]
    layer = QueryStub(outcomes)
    result = peri_scribe.geo_data.query_with_retry(
        SAMPLE_FEED_NAME,
        layer,  # ty: ignore
    )
    assert result is feature_set_with_geometry
    assert sleep_calls == [
        float(peri_scribe.retry.FALLBACK_RETRY_SECONDS),
    ]


def test_query_with_retry_exhausts_retries_and_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleep_calls: list[float] = []
    monkeypatch.setattr(peri_scribe.geo_data.time, "sleep", sleep_calls.append)
    rate_limit_error = ValueError(RATE_LIMIT_ERROR_BODY)
    max_retries = peri_scribe.retry.DEFAULT_MAX_RETRIES
    outcomes: list[arcgis.features.FeatureSet | Exception] = [rate_limit_error] * (
        max_retries + 2
    )
    layer = QueryStub(outcomes)
    with pytest.raises(ValueError, match=re.escape(RATE_LIMIT_ERROR_BODY)):
        peri_scribe.geo_data.query_with_retry(
            SAMPLE_FEED_NAME,
            layer,  # ty: ignore
        )
    # Sleep called once per retry (max_retries times), not for the final failure.
    assert sleep_calls == [60.0] * max_retries


def test_query_with_retry_fails_immediately_on_non_429(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleep_calls: list[float] = []
    monkeypatch.setattr(peri_scribe.geo_data.time, "sleep", sleep_calls.append)
    generic_error = RuntimeError("something else broke")
    outcomes: list[arcgis.features.FeatureSet | Exception] = [generic_error]
    layer = QueryStub(outcomes)
    with pytest.raises(RuntimeError, match="something else broke"):
        peri_scribe.geo_data.query_with_retry(
            SAMPLE_FEED_NAME,
            layer,  # ty: ignore
        )
    assert sleep_calls == []


def test_query_with_retry_retries_on_transient_error(
    monkeypatch: pytest.MonkeyPatch,
    feature_set_with_geometry: arcgis.features.FeatureSet,
) -> None:
    sleep_calls: list[float] = []
    monkeypatch.setattr(peri_scribe.geo_data.time, "sleep", sleep_calls.append)
    transient_error = ValueError("Connection broken: IncompleteRead(…)")
    outcomes: list[arcgis.features.FeatureSet | Exception] = [
        transient_error,
        feature_set_with_geometry,
    ]
    layer = QueryStub(outcomes)
    result = peri_scribe.geo_data.query_with_retry(
        SAMPLE_FEED_NAME,
        layer,  # ty: ignore
    )
    assert result is feature_set_with_geometry
    # First transient error on attempt 1 → backoff = 2.0s
    assert sleep_calls == [peri_scribe.retry.BACKOFF_BASE_SECONDS]


def test_query_with_retry_exhausts_transient_retries_and_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleep_calls: list[float] = []
    monkeypatch.setattr(peri_scribe.geo_data.time, "sleep", sleep_calls.append)
    transient_error = ValueError("Connection broken: IncompleteRead(…)")
    max_retries = peri_scribe.retry.DEFAULT_MAX_RETRIES
    outcomes: list[arcgis.features.FeatureSet | Exception] = [transient_error] * (
        max_retries + 2
    )
    layer = QueryStub(outcomes)
    with pytest.raises(ValueError, match="Connection broken"):
        peri_scribe.geo_data.query_with_retry(
            SAMPLE_FEED_NAME,
            layer,  # ty: ignore
        )
    # Backoff for attempts 1, 2, 3: 2.0s, 4.0s, 8.0s
    assert sleep_calls == [2.0, 4.0, 8.0]


def test_query_with_retry_logs_rate_limit_reason(
    monkeypatch: pytest.MonkeyPatch,
    feature_set_with_geometry: arcgis.features.FeatureSet,
) -> None:
    sleep_calls: list[float] = []
    monkeypatch.setattr(peri_scribe.geo_data.time, "sleep", sleep_calls.append)
    rate_limit_error = ValueError(RATE_LIMIT_ERROR_BODY)
    outcomes: list[arcgis.features.FeatureSet | Exception] = [
        rate_limit_error,
        feature_set_with_geometry,
    ]
    layer = QueryStub(outcomes)
    with structlog.testing.capture_logs() as captured:
        peri_scribe.geo_data.query_with_retry(
            SAMPLE_FEED_NAME,
            layer,  # ty: ignore
        )
    assert captured[0]["event"] == "Rate-limited; retrying after server-suggested delay"
    assert captured[0]["attempt"] == 1
    assert captured[0]["retry_seconds"] == RATE_LIMIT_RETRY_AFTER_SECONDS


def test_query_with_retry_logs_transient_reason(
    monkeypatch: pytest.MonkeyPatch,
    feature_set_with_geometry: arcgis.features.FeatureSet,
) -> None:
    sleep_calls: list[float] = []
    monkeypatch.setattr(peri_scribe.geo_data.time, "sleep", sleep_calls.append)
    transient_error = ValueError("Connection broken: IncompleteRead(…)")
    outcomes: list[arcgis.features.FeatureSet | Exception] = [
        transient_error,
        feature_set_with_geometry,
    ]
    layer = QueryStub(outcomes)
    with structlog.testing.capture_logs() as captured:
        peri_scribe.geo_data.query_with_retry(
            SAMPLE_FEED_NAME,
            layer,  # ty: ignore
        )
    assert captured[0]["event"] == "Transient network error; retrying after backoff"
    assert captured[0]["attempt"] == 1
    assert captured[0]["retry_seconds"] == peri_scribe.retry.BACKOFF_BASE_SECONDS
