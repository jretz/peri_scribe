"""Tests for peri_scribe.sources.feed_types."""

from __future__ import annotations

import http
import time
from typing import TYPE_CHECKING

import pydantic
import pytest
import requests

import peri_scribe.retry
import peri_scribe.sources.feed_types
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


SAMPLE_LAST_EDIT_DATE = 123


def feed_document(**overrides: object) -> dict[str, object]:
    """Return the sample feed's configuration document with *overrides*.

    Args:
        overrides: Configuration keys to add or replace.

    Returns:
        The feed configuration document.
    """
    return {
        "feed_type": "ArcGISFeed",
        "url": SAMPLE_FEED_URL,
        "fire_name_column": SAMPLE_FIRE_NAME_COLUMN,
        "status_column": SAMPLE_STATUS_COLUMN,
        **overrides,
    }


def test_arc_gis_feed_path_segments(
    feed: peri_scribe.sources.feed_types.ArcGISFeed,
) -> None:
    assert feed.path_segments == SAMPLE_PATH_SEGMENTS


def test_arc_gis_feed_path_segments_ignore_empty_segments(
    feed: peri_scribe.sources.feed_types.ArcGISFeed,
) -> None:
    feed = feed.model_copy(update={"url": SAMPLE_FEED_URL + "/"})
    assert feed.path_segments == SAMPLE_PATH_SEGMENTS


def test_arc_gis_feed_service_name(
    feed: peri_scribe.sources.feed_types.ArcGISFeed,
) -> None:
    assert feed.service_name == SAMPLE_SERVICE_NAME


def test_arc_gis_feed_layer_id(
    feed: peri_scribe.sources.feed_types.ArcGISFeed,
) -> None:
    assert feed.layer_id == SAMPLE_LAYER_ID


def test_arc_gis_feed_name(
    feed: peri_scribe.sources.feed_types.ArcGISFeed,
) -> None:
    assert feed.name == SAMPLE_FEED_NAME


def test_arc_gis_feed_stores_fire_name_and_status_columns(
    feed: peri_scribe.sources.feed_types.ArcGISFeed,
) -> None:
    assert feed.fire_name_column == SAMPLE_FIRE_NAME_COLUMN
    assert feed.status_column == SAMPLE_STATUS_COLUMN


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
    document = feed_document()
    del document["url"]
    with pytest.raises(pydantic.ValidationError):
        peri_scribe.sources.feed_types.ArcGISFeed.model_validate(document)


def test_arc_gis_feed_current_last_edit_timestamp(
    feed: peri_scribe.sources.feed_types.ArcGISFeed,
    requests_mock: requests_mock.Mocker,
) -> None:
    requests_mock.get(
        SAMPLE_FEED_URL,
        json={"editingInfo": {"lastEditDate": SAMPLE_LAST_EDIT_DATE}},
    )
    assert feed.current_last_edit_timestamp == SAMPLE_LAST_EDIT_DATE


def test_arc_gis_feed_current_last_edit_timestamp_retries_on_429(
    monkeypatch: pytest.MonkeyPatch,
    feed: peri_scribe.sources.feed_types.ArcGISFeed,
    requests_mock: requests_mock.Mocker,
) -> None:
    sleep_calls: list[float] = []
    monkeypatch.setattr(time, "sleep", sleep_calls.append)
    requests_mock.get(
        SAMPLE_FEED_URL,
        [
            {
                "status_code": http.HTTPStatus.TOO_MANY_REQUESTS,
                "headers": {"Retry-After": "5"},
            },
            {"json": {"editingInfo": {"lastEditDate": SAMPLE_LAST_EDIT_DATE}}},
        ],
    )
    assert feed.current_last_edit_timestamp == SAMPLE_LAST_EDIT_DATE
    assert sleep_calls == [5.0]


def test_arc_gis_feed_current_last_edit_timestamp_retries_on_transient_error(
    monkeypatch: pytest.MonkeyPatch,
    feed: peri_scribe.sources.feed_types.ArcGISFeed,
    requests_mock: requests_mock.Mocker,
) -> None:
    sleep_calls: list[float] = []
    monkeypatch.setattr(time, "sleep", sleep_calls.append)
    requests_mock.get(
        SAMPLE_FEED_URL,
        [
            {"exc": requests.exceptions.ConnectionError("Connection broken")},
            {"json": {"editingInfo": {"lastEditDate": SAMPLE_LAST_EDIT_DATE}}},
        ],
    )
    assert feed.current_last_edit_timestamp == SAMPLE_LAST_EDIT_DATE
    assert sleep_calls == [peri_scribe.retry.BACKOFF_BASE_IN_SECONDS]


def test_arc_gis_feed_current_last_edit_timestamp_returns_none_on_get_error(
    feed: peri_scribe.sources.feed_types.ArcGISFeed,
    requests_mock: requests_mock.Mocker,
) -> None:
    requests_mock.get(
        SAMPLE_FEED_URL,
        status_code=http.HTTPStatus.INTERNAL_SERVER_ERROR,
    )
    assert feed.current_last_edit_timestamp is None


def test_arc_gis_feed_current_last_edit_timestamp_returns_none_on_invalid_json(
    feed: peri_scribe.sources.feed_types.ArcGISFeed,
    requests_mock: requests_mock.Mocker,
) -> None:
    requests_mock.get(SAMPLE_FEED_URL, text="not json")
    assert feed.current_last_edit_timestamp is None


def test_arc_gis_feed_current_last_edit_timestamp_returns_none_for_non_dict_payload(
    feed: peri_scribe.sources.feed_types.ArcGISFeed,
    requests_mock: requests_mock.Mocker,
) -> None:
    requests_mock.get(SAMPLE_FEED_URL, json=["not", "a", "dict"])
    assert feed.current_last_edit_timestamp is None


def test_arc_gis_feed_current_last_edit_timestamp_returns_none_without_editing_info(
    feed: peri_scribe.sources.feed_types.ArcGISFeed,
    requests_mock: requests_mock.Mocker,
) -> None:
    requests_mock.get(SAMPLE_FEED_URL, json={"other": 1})
    assert feed.current_last_edit_timestamp is None


def test_arc_gis_feed_current_last_edit_timestamp_returns_none_without_last_edit_date(
    feed: peri_scribe.sources.feed_types.ArcGISFeed,
    requests_mock: requests_mock.Mocker,
) -> None:
    requests_mock.get(SAMPLE_FEED_URL, json={"editingInfo": {}})
    assert feed.current_last_edit_timestamp is None
