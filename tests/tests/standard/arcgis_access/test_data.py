"""Tests for arcgis_access.data."""

from __future__ import annotations

import re
import time
import typing

import arcgis.features
import pandas as pd
import pyproj
import pytest
import requests
import shapely
import structlog

import arcgis_access.data
import arcgis_access.exceptions
import arcgis_access.retry
import peri_scribe.logging
import peri_scribe.models
import peri_scribe.sources.feed_types
import tests.helpers.doubles.arcgis
import tests.helpers.doubles.arcgis_access.data
import tests.helpers.factories.arcgis
import tests.helpers.factories.arcgis_access.retry
import tests.helpers.factories.geography
import tests.helpers.factories.peri_scribe.sources.feed_types
from measurement_units import units


def test_extract_geometries_without_shape_column() -> None:
    dataframe = pd.DataFrame({"name": ["a", "b"]})
    attributes, geometries, geometry_warning = arcgis_access.data.extract_geometries(
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
    attributes, geometries, geometry_warning = arcgis_access.data.extract_geometries(
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
    result = arcgis_access.data.geo_data_frame_from(
        dataframe,
        geometries,
        tests.helpers.factories.geography.WGS84_WKID,
    )
    assert result.crs == pyproj.CRS.from_epsg(
        tests.helpers.factories.geography.WGS84_WKID,
    )
    assert result.geometry.name == peri_scribe.models.GEOMETRY_COLUMN_NAME
    assert list(result["name"]) == ["a", "b"]
    assert list(result.geometry) == geometries


def test_geo_data_frame_from_allows_null_geometries() -> None:
    dataframe = pd.DataFrame({"name": ["a"]})
    geometries: list[shapely.Geometry | None] = [None]
    result = arcgis_access.data.geo_data_frame_from(
        dataframe,
        geometries,
        tests.helpers.factories.geography.WGS84_WKID,
    )
    assert list(result.geometry) == [None]


@pytest.mark.parametrize("geometry_column", ["geom", "shape"])
@pytest.mark.parametrize("include_schema", [False, True])
def test_geo_data_frame_from_feature_set_accepts_empty_response(
    geometry_column: str,
    log_output: structlog.testing.LogCapture,
    *,
    include_schema: bool,
) -> None:
    feature_set = (
        tests.helpers.factories.arcgis.empty_wgs84_feature_set()
        if include_schema
        else arcgis.features.FeatureSet([])
    )
    result = arcgis_access.data.geo_data_frame_from_feature_set(
        feature_set,
        geometry_column=geometry_column,
    )
    assert result.empty
    assert result.geometry.name == geometry_column
    assert result.columns.is_unique
    assert result.crs == pyproj.CRS.from_epsg(
        tests.helpers.factories.geography.WGS84_WKID,
    )
    assert not any(entry["log_level"] == "warning" for entry in log_output.entries)


def test_dataframe_for_layer_raises_no_features_error_when_feed_is_empty(
    feed: peri_scribe.sources.feed_types.Feed,
) -> None:
    feed_name = tests.helpers.factories.peri_scribe.sources.feed_types.SAMPLE_FEED_NAME
    layer = tests.helpers.doubles.arcgis.LayerStub(properties={})
    feature_set = arcgis.features.FeatureSet([])
    with pytest.raises(
        arcgis_access.exceptions.NoFeaturesError,
        match=(f"Feed {feed_name} returned no features; no output was written"),
    ):
        arcgis_access.data.dataframe_for_layer(feed.name, layer, feature_set)


def test_dataframe_for_layer_builds_geo_data_frame(
    feed: peri_scribe.sources.feed_types.Feed,
    feature_set_with_geometry: arcgis.features.FeatureSet,
) -> None:
    layer = tests.helpers.doubles.arcgis.LayerStub(
        properties={
            "spatialReference": {"wkid": tests.helpers.factories.geography.WGS84_WKID},
        },
    )
    result = arcgis_access.data.dataframe_for_layer(
        feed.name,
        layer,
        feature_set_with_geometry,
    )
    assert result.crs == pyproj.CRS.from_epsg(
        tests.helpers.factories.geography.WGS84_WKID,
    )
    assert result.geometry.name == peri_scribe.models.GEOMETRY_COLUMN_NAME
    assert list(result["name"]) == ["a", "b"]
    assert list(result.geometry) == [
        shapely.geometry.Point(1.0, 2.0),
        shapely.geometry.Point(3.0, 4.0),
    ]


def test_dataframe_for_layer_warns_when_features_lack_geometry(
    feed: peri_scribe.sources.feed_types.Feed,
) -> None:
    layer = tests.helpers.doubles.arcgis.LayerStub(
        properties={
            "spatialReference": {"wkid": tests.helpers.factories.geography.WGS84_WKID},
        },
    )
    feature_set = arcgis.features.FeatureSet([
        arcgis.features.Feature(attributes={"name": "a"}),
        arcgis.features.Feature(attributes={"name": "b"}),
    ])
    with structlog.testing.capture_logs() as captured:
        result = arcgis_access.data.dataframe_for_layer(feed.name, layer, feature_set)
    captured = [entry for entry in captured if entry["log_level"] == "warning"]
    assert len(captured) == 1
    assert captured[0]["log_level"] == "warning"
    assert "all features lack geometry" in captured[0]["event"]
    assert list(result.geometry) == [None, None]


def test_query_with_retry_succeeds_on_first_attempt(
    monkeypatch: pytest.MonkeyPatch,
    feature_set_with_geometry: arcgis.features.FeatureSet,
) -> None:
    sleep_calls: list[float] = []
    monkeypatch.setattr(time, "sleep", sleep_calls.append)
    outcomes: list[arcgis.features.FeatureSet | Exception] = [feature_set_with_geometry]
    layer = tests.helpers.doubles.arcgis_access.data.QueryStub(outcomes)
    result = arcgis_access.data.query_with_retry(
        tests.helpers.factories.peri_scribe.sources.feed_types.SAMPLE_FEED_NAME,
        typing.cast("arcgis.features.FeatureLayer", layer),
    )
    assert result is feature_set_with_geometry
    assert sleep_calls == []


def test_query_with_retry_retries_on_429_with_retry_after(
    monkeypatch: pytest.MonkeyPatch,
    feature_set_with_geometry: arcgis.features.FeatureSet,
) -> None:
    sleep_calls: list[float] = []
    monkeypatch.setattr(time, "sleep", sleep_calls.append)
    rate_limit_error = ValueError(
        tests.helpers.factories.arcgis_access.retry.RATE_LIMIT_ERROR_PAYLOAD,
    )
    outcomes: list[arcgis.features.FeatureSet | Exception] = [
        rate_limit_error,
        feature_set_with_geometry,
    ]
    layer = tests.helpers.doubles.arcgis_access.data.QueryStub(outcomes)
    result = arcgis_access.data.query_with_retry(
        tests.helpers.factories.peri_scribe.sources.feed_types.SAMPLE_FEED_NAME,
        typing.cast("arcgis.features.FeatureLayer", layer),
    )
    assert result is feature_set_with_geometry
    assert sleep_calls == [60.0]


def test_query_with_retry_retries_on_loose_429(
    monkeypatch: pytest.MonkeyPatch,
    feature_set_with_geometry: arcgis.features.FeatureSet,
) -> None:
    sleep_calls: list[float] = []
    monkeypatch.setattr(time, "sleep", sleep_calls.append)
    loose_429_error = ValueError(
        tests.helpers.factories.arcgis_access.retry.LOOSE_429_ERROR_PAYLOAD,
    )
    outcomes: list[arcgis.features.FeatureSet | Exception] = [
        loose_429_error,
        feature_set_with_geometry,
    ]
    layer = tests.helpers.doubles.arcgis_access.data.QueryStub(outcomes)
    result = arcgis_access.data.query_with_retry(
        tests.helpers.factories.peri_scribe.sources.feed_types.SAMPLE_FEED_NAME,
        typing.cast("arcgis.features.FeatureLayer", layer),
    )
    assert result is feature_set_with_geometry
    assert sleep_calls == [float(arcgis_access.retry.FALLBACK_RETRY.m_as("seconds"))]


def test_query_with_retry_exhausts_retries_and_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleep_calls: list[float] = []
    monkeypatch.setattr(time, "sleep", sleep_calls.append)
    rate_limit_error = ValueError(
        tests.helpers.factories.arcgis_access.retry.RATE_LIMIT_ERROR_PAYLOAD,
    )
    maximum_retries = arcgis_access.retry.DEFAULT_MAXIMUM_RETRIES
    outcomes: list[arcgis.features.FeatureSet | Exception] = [rate_limit_error] * (
        maximum_retries + 2
    )
    layer = tests.helpers.doubles.arcgis_access.data.QueryStub(outcomes)
    with pytest.raises(
        ValueError,
        match=re.escape(
            str(tests.helpers.factories.arcgis_access.retry.RATE_LIMIT_ERROR_PAYLOAD),
        ),
    ):
        arcgis_access.data.query_with_retry(
            tests.helpers.factories.peri_scribe.sources.feed_types.SAMPLE_FEED_NAME,
            typing.cast("arcgis.features.FeatureLayer", layer),
        )
    # Sleep called once per retry (maximum_retries times), not for the final failure.
    assert sleep_calls == [60.0] * maximum_retries


def test_query_with_retry_fails_immediately_on_non_429(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleep_calls: list[float] = []
    monkeypatch.setattr(time, "sleep", sleep_calls.append)
    generic_error = RuntimeError("something else broke")
    outcomes: list[arcgis.features.FeatureSet | Exception] = [generic_error]
    layer = tests.helpers.doubles.arcgis_access.data.QueryStub(outcomes)
    with pytest.raises(RuntimeError, match="something else broke"):
        arcgis_access.data.query_with_retry(
            tests.helpers.factories.peri_scribe.sources.feed_types.SAMPLE_FEED_NAME,
            typing.cast("arcgis.features.FeatureLayer", layer),
        )
    assert sleep_calls == []


def test_query_with_retry_retries_on_transient_error(
    monkeypatch: pytest.MonkeyPatch,
    feature_set_with_geometry: arcgis.features.FeatureSet,
) -> None:
    sleep_calls: list[float] = []
    monkeypatch.setattr(time, "sleep", sleep_calls.append)
    transient_error = requests.exceptions.ConnectionError(
        "Connection broken: IncompleteRead(…)",
    )
    outcomes: list[arcgis.features.FeatureSet | Exception] = [
        transient_error,
        feature_set_with_geometry,
    ]
    layer = tests.helpers.doubles.arcgis_access.data.QueryStub(outcomes)
    result = arcgis_access.data.query_with_retry(
        tests.helpers.factories.peri_scribe.sources.feed_types.SAMPLE_FEED_NAME,
        typing.cast("arcgis.features.FeatureLayer", layer),
    )
    assert result is feature_set_with_geometry
    # First transient error on attempt 1 → backoff = 2.0s
    assert sleep_calls == [arcgis_access.retry.BACKOFF_BASE.m_as("seconds")]


def test_query_with_retry_exhausts_transient_retries_and_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleep_calls: list[float] = []
    monkeypatch.setattr(time, "sleep", sleep_calls.append)
    transient_error = requests.exceptions.ConnectionError(
        "Connection broken: IncompleteRead(…)",
    )
    retries = 3
    outcomes: list[arcgis.features.FeatureSet | Exception] = [transient_error] * (
        retries + 2
    )
    layer = tests.helpers.doubles.arcgis_access.data.QueryStub(outcomes)
    with pytest.raises(requests.exceptions.ConnectionError, match="Connection broken"):
        arcgis_access.data.query_with_retry(
            tests.helpers.factories.peri_scribe.sources.feed_types.SAMPLE_FEED_NAME,
            typing.cast("arcgis.features.FeatureLayer", layer),
            maximum_retries=retries,
        )
    # Backoff for attempts 1, 2, 3 doubles from the base constant each time.
    assert sleep_calls == [
        arcgis_access.retry.BACKOFF_BASE.m_as("seconds") * 2**attempt
        for attempt in range(retries)
    ]


def test_query_with_retry_logs_rate_limit_reason(
    monkeypatch: pytest.MonkeyPatch,
    feature_set_with_geometry: arcgis.features.FeatureSet,
) -> None:
    sleep_calls: list[float] = []
    monkeypatch.setattr(time, "sleep", sleep_calls.append)
    rate_limit_error = ValueError(
        tests.helpers.factories.arcgis_access.retry.RATE_LIMIT_ERROR_PAYLOAD,
    )
    outcomes: list[arcgis.features.FeatureSet | Exception] = [
        rate_limit_error,
        feature_set_with_geometry,
    ]
    layer = tests.helpers.doubles.arcgis_access.data.QueryStub(outcomes)
    with structlog.testing.capture_logs(
        processors=[peri_scribe.logging.serialize_log_values],
    ) as captured:
        arcgis_access.data.query_with_retry(
            tests.helpers.factories.peri_scribe.sources.feed_types.SAMPLE_FEED_NAME,
            typing.cast("arcgis.features.FeatureLayer", layer),
        )
    captured = [entry for entry in captured if "retry_delay" in entry]
    assert captured[0]["event"] == "Rate-limited; retrying after server-suggested delay"
    assert captured[0]["attempt"] == 1
    assert captured[0]["retry_delay"] == {
        "value": (
            tests.helpers.factories.arcgis_access.retry.RATE_LIMIT_RETRY_AFTER
        ).m_as("seconds"),
        "units": units.seconds,
    }


def test_query_with_retry_logs_transient_reason(
    monkeypatch: pytest.MonkeyPatch,
    feature_set_with_geometry: arcgis.features.FeatureSet,
) -> None:
    sleep_calls: list[float] = []
    monkeypatch.setattr(time, "sleep", sleep_calls.append)
    transient_error = requests.exceptions.ConnectionError(
        "Connection broken: IncompleteRead(…)",
    )
    outcomes: list[arcgis.features.FeatureSet | Exception] = [
        transient_error,
        feature_set_with_geometry,
    ]
    layer = tests.helpers.doubles.arcgis_access.data.QueryStub(outcomes)
    with structlog.testing.capture_logs(
        processors=[peri_scribe.logging.serialize_log_values],
    ) as captured:
        arcgis_access.data.query_with_retry(
            tests.helpers.factories.peri_scribe.sources.feed_types.SAMPLE_FEED_NAME,
            typing.cast("arcgis.features.FeatureLayer", layer),
        )
    captured = [entry for entry in captured if "retry_delay" in entry]
    assert captured[0]["event"] == "Transient network error; retrying after backoff"
    assert captured[0]["attempt"] == 1
    assert captured[0]["retry_delay"] == {
        "value": arcgis_access.retry.BACKOFF_BASE.m_as("seconds"),
        "units": units.seconds,
    }


def test_query_object_ids_with_retry_returns_object_ids() -> None:
    layer = tests.helpers.doubles.arcgis_access.data.IdQueryStub({
        "objectIds": [3, 4],
    })
    result = arcgis_access.data.query_object_ids_with_retry(
        tests.helpers.factories.peri_scribe.sources.feed_types.SAMPLE_FEED_NAME,
        typing.cast("arcgis.features.FeatureLayer", layer),
        where="1=1",
    )
    assert result == [3, 4]


def test_query_object_ids_with_retry_raises_without_object_ids() -> None:
    layer = tests.helpers.doubles.arcgis_access.data.IdQueryStub({"count": 0})
    with pytest.raises(arcgis_access.exceptions.NoFeaturesError, match="no object ids"):
        arcgis_access.data.query_object_ids_with_retry(
            tests.helpers.factories.peri_scribe.sources.feed_types.SAMPLE_FEED_NAME,
            typing.cast("arcgis.features.FeatureLayer", layer),
            where="1=1",
        )


@pytest.mark.parametrize("geometry_column", ["geometry", "location"])
def test_geo_data_frame_from_uses_requested_geometry_column(
    geometry_column: str,
) -> None:
    result = arcgis_access.data.geo_data_frame_from(
        pd.DataFrame({"name": ["station"]}),
        [shapely.geometry.Point(1.0, 2.0)],
        tests.helpers.factories.geography.WGS84_WKID,
        geometry_column=geometry_column,
    )
    assert result.geometry.name == geometry_column
    assert result.geometry.iloc[0] == shapely.geometry.Point(1.0, 2.0)
    assert list(result["name"]) == ["station"]
    assert result.crs == pyproj.CRS.from_epsg(
        tests.helpers.factories.geography.WGS84_WKID,
    )
