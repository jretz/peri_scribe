"""Tests for peri_scribe.feed_types."""

from __future__ import annotations

import http
import time
from typing import TYPE_CHECKING

import pydantic
import pytest
import requests

import peri_scribe.feed_types
from tests.conftest import (
    SAMPLE_FEED_NAME,
    SAMPLE_FEED_URL,
    SAMPLE_FIRE_NAME_COLUMN,
    SAMPLE_LAYER_ID,
    SAMPLE_PATH_SEGMENTS,
    SAMPLE_SERVICE_NAME,
    SAMPLE_STATUS_COLUMN,
)


if TYPE_CHECKING:
    import requests_mock


def test_arc_gis_feed_path_segments() -> None:
    feed = peri_scribe.feed_types.ArcGISFeed(
        url=SAMPLE_FEED_URL,
        fire_name_column=SAMPLE_FIRE_NAME_COLUMN,
        status_column=SAMPLE_STATUS_COLUMN,
    )
    assert feed.path_segments == SAMPLE_PATH_SEGMENTS


def test_arc_gis_feed_path_segments_ignore_empty_segments() -> None:
    feed = peri_scribe.feed_types.ArcGISFeed(
        url=SAMPLE_FEED_URL + "/",
        fire_name_column=SAMPLE_FIRE_NAME_COLUMN,
        status_column=SAMPLE_STATUS_COLUMN,
    )
    assert feed.path_segments == SAMPLE_PATH_SEGMENTS


def test_arc_gis_feed_service_name() -> None:
    feed = peri_scribe.feed_types.ArcGISFeed(
        url=SAMPLE_FEED_URL,
        fire_name_column=SAMPLE_FIRE_NAME_COLUMN,
        status_column=SAMPLE_STATUS_COLUMN,
    )
    assert feed.service_name == SAMPLE_SERVICE_NAME


def test_arc_gis_feed_layer_id() -> None:
    feed = peri_scribe.feed_types.ArcGISFeed(
        url=SAMPLE_FEED_URL,
        fire_name_column=SAMPLE_FIRE_NAME_COLUMN,
        status_column=SAMPLE_STATUS_COLUMN,
    )
    assert feed.layer_id == SAMPLE_LAYER_ID


def test_arc_gis_feed_name() -> None:
    feed = peri_scribe.feed_types.ArcGISFeed(
        url=SAMPLE_FEED_URL,
        fire_name_column=SAMPLE_FIRE_NAME_COLUMN,
        status_column=SAMPLE_STATUS_COLUMN,
    )
    assert feed.name == SAMPLE_FEED_NAME


def test_arc_gis_feed_stores_fire_name_and_status_columns() -> None:
    feed = peri_scribe.feed_types.ArcGISFeed(
        url=SAMPLE_FEED_URL,
        fire_name_column=SAMPLE_FIRE_NAME_COLUMN,
        status_column=SAMPLE_STATUS_COLUMN,
    )
    assert feed.fire_name_column == SAMPLE_FIRE_NAME_COLUMN
    assert feed.status_column == SAMPLE_STATUS_COLUMN


def test_arc_gis_feed_exposes_identifier_and_complex_columns() -> None:
    feed = peri_scribe.feed_types.ArcGISFeed(
        url=SAMPLE_FEED_URL,
        fire_name_column=SAMPLE_FIRE_NAME_COLUMN,
        status_column=SAMPLE_STATUS_COLUMN,
        fire_identifier_column="incident_number",
        complex_identifier_column="CpxID",
        complex_name_column="CpxName",
        is_complex_child_column="IsCpxChild",
    )
    assert feed.fire_identifier_column == "incident_number"
    assert feed.complex_identifier_column == "CpxID"
    assert feed.complex_name_column == "CpxName"
    assert feed.is_complex_child_column == "IsCpxChild"


def test_arc_gis_feed_validates_configuration() -> None:
    feed = peri_scribe.feed_types.ArcGISFeed.model_validate({
        "feed_type": "ArcGISFeed",
        "url": SAMPLE_FEED_URL,
        "fire_name_column": SAMPLE_FIRE_NAME_COLUMN,
        "status_column": SAMPLE_STATUS_COLUMN,
    })
    assert feed.name == SAMPLE_FEED_NAME
    assert feed.feed_type == "ArcGISFeed"


def test_arc_gis_feed_rejects_unknown_feed_type() -> None:
    with pytest.raises(pydantic.ValidationError):
        peri_scribe.feed_types.ArcGISFeed.model_validate({
            "feed_type": "NotAFeed",
            "url": SAMPLE_FEED_URL,
            "fire_name_column": SAMPLE_FIRE_NAME_COLUMN,
            "status_column": SAMPLE_STATUS_COLUMN,
        })


def test_arc_gis_feed_rejects_unknown_configuration_key() -> None:
    with pytest.raises(pydantic.ValidationError):
        peri_scribe.feed_types.ArcGISFeed.model_validate({
            "feed_type": "ArcGISFeed",
            "url": SAMPLE_FEED_URL,
            "fire_name_column": SAMPLE_FIRE_NAME_COLUMN,
            "status_column": SAMPLE_STATUS_COLUMN,
            "not_a_feed_column": "value",
        })


def test_arc_gis_feed_rejects_missing_url() -> None:
    with pytest.raises(pydantic.ValidationError):
        peri_scribe.feed_types.ArcGISFeed.model_validate({
            "feed_type": "ArcGISFeed",
            "fire_name_column": SAMPLE_FIRE_NAME_COLUMN,
            "status_column": SAMPLE_STATUS_COLUMN,
        })


def test_arc_gis_feed_current_watermark(
    requests_mock: requests_mock.Mocker,
) -> None:
    feed = peri_scribe.feed_types.ArcGISFeed(
        url=SAMPLE_FEED_URL,
        fire_name_column=SAMPLE_FIRE_NAME_COLUMN,
        status_column=SAMPLE_STATUS_COLUMN,
    )
    requests_mock.get(SAMPLE_FEED_URL, json={"editingInfo": {"lastEditDate": 123}})
    assert feed.current_watermark == "lastEdit=123"


def test_arc_gis_feed_current_watermark_retries_on_429(
    monkeypatch: pytest.MonkeyPatch,
    requests_mock: requests_mock.Mocker,
) -> None:
    feed = peri_scribe.feed_types.ArcGISFeed(
        url=SAMPLE_FEED_URL,
        fire_name_column=SAMPLE_FIRE_NAME_COLUMN,
        status_column=SAMPLE_STATUS_COLUMN,
    )
    sleep_calls: list[float] = []
    monkeypatch.setattr(time, "sleep", sleep_calls.append)
    requests_mock.get(
        SAMPLE_FEED_URL,
        [
            {
                "status_code": http.HTTPStatus.TOO_MANY_REQUESTS,
                "headers": {"Retry-After": "5"},
            },
            {"json": {"editingInfo": {"lastEditDate": 123}}},
        ],
    )
    assert feed.current_watermark == "lastEdit=123"
    assert sleep_calls == [5.0]


def test_arc_gis_feed_current_watermark_retries_on_transient_error(
    monkeypatch: pytest.MonkeyPatch,
    requests_mock: requests_mock.Mocker,
) -> None:
    feed = peri_scribe.feed_types.ArcGISFeed(
        url=SAMPLE_FEED_URL,
        fire_name_column=SAMPLE_FIRE_NAME_COLUMN,
        status_column=SAMPLE_STATUS_COLUMN,
    )
    sleep_calls: list[float] = []
    monkeypatch.setattr(time, "sleep", sleep_calls.append)
    requests_mock.get(
        SAMPLE_FEED_URL,
        [
            {"exc": requests.exceptions.ConnectionError("Connection broken")},
            {"json": {"editingInfo": {"lastEditDate": 123}}},
        ],
    )
    assert feed.current_watermark == "lastEdit=123"
    assert sleep_calls == [2.0]


def test_arc_gis_feed_current_watermark_returns_none_on_get_error(
    requests_mock: requests_mock.Mocker,
) -> None:
    feed = peri_scribe.feed_types.ArcGISFeed(
        url=SAMPLE_FEED_URL,
        fire_name_column=SAMPLE_FIRE_NAME_COLUMN,
        status_column=SAMPLE_STATUS_COLUMN,
    )
    requests_mock.get(
        SAMPLE_FEED_URL,
        status_code=http.HTTPStatus.INTERNAL_SERVER_ERROR,
    )
    assert feed.current_watermark is None


def test_arc_gis_feed_current_watermark_returns_none_on_invalid_json(
    requests_mock: requests_mock.Mocker,
) -> None:
    feed = peri_scribe.feed_types.ArcGISFeed(
        url=SAMPLE_FEED_URL,
        fire_name_column=SAMPLE_FIRE_NAME_COLUMN,
        status_column=SAMPLE_STATUS_COLUMN,
    )
    requests_mock.get(SAMPLE_FEED_URL, text="not json")
    assert feed.current_watermark is None


def test_arc_gis_feed_current_watermark_returns_none_for_non_dict_payload(
    requests_mock: requests_mock.Mocker,
) -> None:
    feed = peri_scribe.feed_types.ArcGISFeed(
        url=SAMPLE_FEED_URL,
        fire_name_column=SAMPLE_FIRE_NAME_COLUMN,
        status_column=SAMPLE_STATUS_COLUMN,
    )
    requests_mock.get(SAMPLE_FEED_URL, json=["not", "a", "dict"])
    assert feed.current_watermark is None


def test_arc_gis_feed_current_watermark_returns_none_without_editing_info(
    requests_mock: requests_mock.Mocker,
) -> None:
    feed = peri_scribe.feed_types.ArcGISFeed(
        url=SAMPLE_FEED_URL,
        fire_name_column=SAMPLE_FIRE_NAME_COLUMN,
        status_column=SAMPLE_STATUS_COLUMN,
    )
    requests_mock.get(SAMPLE_FEED_URL, json={"other": 1})
    assert feed.current_watermark is None


def test_arc_gis_feed_current_watermark_returns_none_without_last_edit_date(
    requests_mock: requests_mock.Mocker,
) -> None:
    feed = peri_scribe.feed_types.ArcGISFeed(
        url=SAMPLE_FEED_URL,
        fire_name_column=SAMPLE_FIRE_NAME_COLUMN,
        status_column=SAMPLE_STATUS_COLUMN,
    )
    requests_mock.get(SAMPLE_FEED_URL, json={"editingInfo": {}})
    assert feed.current_watermark is None


def test_arc_gis_feed_satisfies_feed_protocol() -> None:
    feed = peri_scribe.feed_types.ArcGISFeed(
        url=SAMPLE_FEED_URL,
        fire_name_column=SAMPLE_FIRE_NAME_COLUMN,
        status_column=SAMPLE_STATUS_COLUMN,
    )
    assert isinstance(feed, peri_scribe.feed_types.Feed)
