"""Tests for peri_scribe.sources.feed_types."""

from __future__ import annotations

import http
import time
import typing

import pydantic
import pytest
import requests

import arcgis_access.retry
import peri_scribe.sources.feed_types
import tests.helpers.factories.peri_scribe.sources.feed_types


if typing.TYPE_CHECKING:
    import requests_mock


def test_arc_gis_feed_path_segments(
    feed: peri_scribe.sources.feed_types.ArcGISFeed,
) -> None:
    assert (
        feed.path_segments
        == tests.helpers.factories.peri_scribe.sources.feed_types.SAMPLE_PATH_SEGMENTS
    )


def test_arc_gis_feed_path_segments_ignore_empty_segments(
    feed: peri_scribe.sources.feed_types.ArcGISFeed,
) -> None:
    feed = feed.model_copy(
        update={
            "url": (
                tests.helpers.factories.peri_scribe.sources.feed_types
            ).SAMPLE_FEED_URL
            + "/",
        },
    )
    assert (
        feed.path_segments
        == tests.helpers.factories.peri_scribe.sources.feed_types.SAMPLE_PATH_SEGMENTS
    )


def test_arc_gis_feed_service_name(
    feed: peri_scribe.sources.feed_types.ArcGISFeed,
) -> None:
    assert (
        feed.service_name
        == tests.helpers.factories.peri_scribe.sources.feed_types.SAMPLE_SERVICE_NAME
    )


def test_arc_gis_feed_layer_id(feed: peri_scribe.sources.feed_types.ArcGISFeed) -> None:
    assert (
        feed.layer_id
        == tests.helpers.factories.peri_scribe.sources.feed_types.SAMPLE_LAYER_ID
    )


def test_arc_gis_feed_name(feed: peri_scribe.sources.feed_types.ArcGISFeed) -> None:
    assert (
        feed.name
        == tests.helpers.factories.peri_scribe.sources.feed_types.SAMPLE_FEED_NAME
    )


def test_arc_gis_feed_stores_fire_name_and_status_columns(
    feed: peri_scribe.sources.feed_types.ArcGISFeed,
) -> None:
    assert (
        feed.fire_name_column
        == (
            tests.helpers.factories.peri_scribe.sources.feed_types
        ).SAMPLE_FIRE_NAME_COLUMN
    )
    assert (
        feed.status_column
        == tests.helpers.factories.peri_scribe.sources.feed_types.SAMPLE_STATUS_COLUMN
    )


def test_arc_gis_feed_exposes_identifier_and_complex_columns(
    feed: peri_scribe.sources.feed_types.ArcGISFeed,
) -> None:
    feed = feed.model_copy(
        update={
            "fire_identifier_columns": ("incident_number", "other_number"),
            "mission_column": "mission",
            "observation_time_column": "poly_DateCurrent",
            "complex_identifier_column": "CpxID",
            "complex_name_column": "CpxName",
            "is_complex_child_column": "IsCpxChild",
        },
    )
    assert feed.fire_identifier_columns == ("incident_number", "other_number")
    assert feed.mission_column == "mission"
    assert feed.observation_time_column == "poly_DateCurrent"
    assert feed.complex_identifier_column == "CpxID"
    assert feed.complex_name_column == "CpxName"
    assert feed.is_complex_child_column == "IsCpxChild"


def test_arc_gis_feed_rejects_missing_url() -> None:
    document = tests.helpers.factories.peri_scribe.sources.feed_types.feed_document()
    del document["url"]
    with pytest.raises(pydantic.ValidationError):
        peri_scribe.sources.feed_types.ArcGISFeed.model_validate(document)


def test_arc_gis_feed_current_last_edit_timestamp(
    feed: peri_scribe.sources.feed_types.ArcGISFeed,
    requests_mock: requests_mock.Mocker,
) -> None:
    requests_mock.get(
        tests.helpers.factories.peri_scribe.sources.feed_types.SAMPLE_FEED_URL,
        json={
            "editingInfo": {
                "lastEditDate": (
                    tests.helpers.factories.peri_scribe.sources.feed_types
                ).SAMPLE_LAST_EDIT_DATE,
            },
        },
    )
    assert (
        feed.current_last_edit_timestamp
        == tests.helpers.factories.peri_scribe.sources.feed_types.SAMPLE_LAST_EDIT_DATE
    )


def test_arc_gis_feed_current_last_edit_timestamp_retries_on_429(
    monkeypatch: pytest.MonkeyPatch,
    feed: peri_scribe.sources.feed_types.ArcGISFeed,
    requests_mock: requests_mock.Mocker,
) -> None:
    sleep_calls: list[float] = []
    monkeypatch.setattr(time, "sleep", sleep_calls.append)
    requests_mock.get(
        tests.helpers.factories.peri_scribe.sources.feed_types.SAMPLE_FEED_URL,
        [
            {
                "status_code": http.HTTPStatus.TOO_MANY_REQUESTS,
                "headers": {"Retry-After": "5"},
            },
            {
                "json": {
                    "editingInfo": {
                        "lastEditDate": (
                            tests.helpers.factories.peri_scribe.sources.feed_types
                        ).SAMPLE_LAST_EDIT_DATE,
                    },
                },
            },
        ],
    )
    assert (
        feed.current_last_edit_timestamp
        == tests.helpers.factories.peri_scribe.sources.feed_types.SAMPLE_LAST_EDIT_DATE
    )
    assert sleep_calls == [5.0]


def test_arc_gis_feed_current_last_edit_timestamp_retries_on_transient_error(
    monkeypatch: pytest.MonkeyPatch,
    feed: peri_scribe.sources.feed_types.ArcGISFeed,
    requests_mock: requests_mock.Mocker,
) -> None:
    sleep_calls: list[float] = []
    monkeypatch.setattr(time, "sleep", sleep_calls.append)
    requests_mock.get(
        tests.helpers.factories.peri_scribe.sources.feed_types.SAMPLE_FEED_URL,
        [
            {"exc": requests.exceptions.ConnectionError("Connection broken")},
            {
                "json": {
                    "editingInfo": {
                        "lastEditDate": (
                            tests.helpers.factories.peri_scribe.sources.feed_types
                        ).SAMPLE_LAST_EDIT_DATE,
                    },
                },
            },
        ],
    )
    assert (
        feed.current_last_edit_timestamp
        == tests.helpers.factories.peri_scribe.sources.feed_types.SAMPLE_LAST_EDIT_DATE
    )
    assert sleep_calls == [arcgis_access.retry.BACKOFF_BASE.m_as("seconds")]


def test_arc_gis_feed_current_last_edit_timestamp_returns_none_on_get_error(
    feed: peri_scribe.sources.feed_types.ArcGISFeed,
    requests_mock: requests_mock.Mocker,
) -> None:
    requests_mock.get(
        tests.helpers.factories.peri_scribe.sources.feed_types.SAMPLE_FEED_URL,
        status_code=http.HTTPStatus.INTERNAL_SERVER_ERROR,
    )
    assert feed.current_last_edit_timestamp is None


def test_arc_gis_feed_current_last_edit_timestamp_returns_none_on_invalid_json(
    feed: peri_scribe.sources.feed_types.ArcGISFeed,
    requests_mock: requests_mock.Mocker,
) -> None:
    requests_mock.get(
        tests.helpers.factories.peri_scribe.sources.feed_types.SAMPLE_FEED_URL,
        text="not json",
    )
    assert feed.current_last_edit_timestamp is None


def test_arc_gis_feed_current_last_edit_timestamp_returns_none_for_non_dict_payload(
    feed: peri_scribe.sources.feed_types.ArcGISFeed,
    requests_mock: requests_mock.Mocker,
) -> None:
    requests_mock.get(
        tests.helpers.factories.peri_scribe.sources.feed_types.SAMPLE_FEED_URL,
        json=["not", "a", "dict"],
    )
    assert feed.current_last_edit_timestamp is None


def test_arc_gis_feed_current_last_edit_timestamp_returns_none_without_editing_info(
    feed: peri_scribe.sources.feed_types.ArcGISFeed,
    requests_mock: requests_mock.Mocker,
) -> None:
    requests_mock.get(
        tests.helpers.factories.peri_scribe.sources.feed_types.SAMPLE_FEED_URL,
        json={"other": 1},
    )
    assert feed.current_last_edit_timestamp is None


def test_arc_gis_feed_current_last_edit_timestamp_returns_none_without_last_edit_date(
    feed: peri_scribe.sources.feed_types.ArcGISFeed,
    requests_mock: requests_mock.Mocker,
) -> None:
    requests_mock.get(
        tests.helpers.factories.peri_scribe.sources.feed_types.SAMPLE_FEED_URL,
        json={"editingInfo": {}},
    )
    assert feed.current_last_edit_timestamp is None
