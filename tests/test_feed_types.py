"""Tests for peri_scribe.feed_types."""

import dataclasses

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


@dataclasses.dataclass(frozen=True, kw_only=True)
class SampleFeedAlpha:
    name: str
    count: int


@dataclasses.dataclass(frozen=True, kw_only=True)
class SampleFeedBeta:
    label: str


class ResponseStub:
    """Minimal stand-in for a requests.Response."""

    def __init__(
        self,
        *,
        payload: object | None = None,
        headers: dict[str, str] | None = None,
        status_error: Exception | None = None,
        json_error: Exception | None = None,
    ) -> None:
        self.payload = payload
        self.headers = headers if headers is not None else {}
        self.status_error = status_error
        self.json_error = json_error

    def raise_for_status(self) -> None:
        if self.status_error is not None:
            raise self.status_error

    def json(self) -> object:
        if self.json_error is not None:
            raise self.json_error
        return self.payload


def test_feed_types_register_returns_class_unchanged() -> None:
    decorated = peri_scribe.feed_types.FeedTypes.register(SampleFeedAlpha)
    assert decorated is SampleFeedAlpha


def test_feed_types_register_stores_class_by_name() -> None:
    peri_scribe.feed_types.FeedTypes.register(SampleFeedAlpha)
    assert (
        peri_scribe.feed_types.FeedTypes.get_feed_class("SampleFeedAlpha")
        is SampleFeedAlpha
    )


def test_feed_types_register_works_as_decorator() -> None:
    @peri_scribe.feed_types.FeedTypes.register
    @dataclasses.dataclass(frozen=True, kw_only=True)
    class DecoratedFeed:
        value: str

    assert (
        peri_scribe.feed_types.FeedTypes.get_feed_class("DecoratedFeed")
        is DecoratedFeed
    )


def test_feed_types_get_feed_class_returns_registered_class() -> None:
    peri_scribe.feed_types.FeedTypes.register(SampleFeedBeta)
    result = peri_scribe.feed_types.FeedTypes.get_feed_class("SampleFeedBeta")
    assert result is SampleFeedBeta


def test_feed_types_get_feed_class_raises_key_error_for_unregistered() -> None:
    with pytest.raises(KeyError):
        peri_scribe.feed_types.FeedTypes.get_feed_class("NoSuchFeed")


def test_feed_types_has_no_instance_methods() -> None:
    """FeedTypes should have no instance methods — only classmethods."""
    instance_methods = [
        name
        for name, value in vars(peri_scribe.feed_types.FeedTypes).items()
        if callable(value)
        and not name.startswith("__")
        and not isinstance(value, classmethod)
    ]
    assert not instance_methods


def test_feed_types_instance_has_no_own_attributes() -> None:
    """Instances of FeedTypes should carry no per-instance state."""
    instance = peri_scribe.feed_types.FeedTypes()
    # __dict__ holds instance attributes; should be empty
    assert not instance.__dict__


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


def test_arc_gis_feed_registered_in_feed_types() -> None:
    feed_class = peri_scribe.feed_types.FeedTypes.get_feed_class("ArcGISFeed")
    assert feed_class is peri_scribe.feed_types.ArcGISFeed


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


def test_arc_gis_feed_current_watermark(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    feed = peri_scribe.feed_types.ArcGISFeed(
        url=SAMPLE_FEED_URL,
        fire_name_column=SAMPLE_FIRE_NAME_COLUMN,
        status_column=SAMPLE_STATUS_COLUMN,
    )
    monkeypatch.setattr(
        peri_scribe.feed_types.requests,
        "get",
        lambda *_arguments, **_keywords: ResponseStub(
            payload={"editingInfo": {"lastEditDate": 123}},
        ),
    )
    assert feed.current_watermark == "lastEdit=123"


def test_arc_gis_feed_current_watermark_returns_none_on_get_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    feed = peri_scribe.feed_types.ArcGISFeed(
        url=SAMPLE_FEED_URL,
        fire_name_column=SAMPLE_FIRE_NAME_COLUMN,
        status_column=SAMPLE_STATUS_COLUMN,
    )
    monkeypatch.setattr(
        peri_scribe.feed_types.requests,
        "get",
        lambda *_arguments, **_keywords: ResponseStub(
            status_error=requests.exceptions.HTTPError("boom"),
        ),
    )
    assert feed.current_watermark is None


def test_arc_gis_feed_current_watermark_returns_none_on_invalid_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    feed = peri_scribe.feed_types.ArcGISFeed(
        url=SAMPLE_FEED_URL,
        fire_name_column=SAMPLE_FIRE_NAME_COLUMN,
        status_column=SAMPLE_STATUS_COLUMN,
    )
    monkeypatch.setattr(
        peri_scribe.feed_types.requests,
        "get",
        lambda *_arguments, **_keywords: ResponseStub(
            json_error=ValueError("not json"),
        ),
    )
    assert feed.current_watermark is None


def test_arc_gis_feed_current_watermark_returns_none_for_non_dict_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    feed = peri_scribe.feed_types.ArcGISFeed(
        url=SAMPLE_FEED_URL,
        fire_name_column=SAMPLE_FIRE_NAME_COLUMN,
        status_column=SAMPLE_STATUS_COLUMN,
    )
    monkeypatch.setattr(
        peri_scribe.feed_types.requests,
        "get",
        lambda *_arguments, **_keywords: ResponseStub(payload=["not", "a", "dict"]),
    )
    assert feed.current_watermark is None


def test_arc_gis_feed_current_watermark_returns_none_without_editing_info(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    feed = peri_scribe.feed_types.ArcGISFeed(
        url=SAMPLE_FEED_URL,
        fire_name_column=SAMPLE_FIRE_NAME_COLUMN,
        status_column=SAMPLE_STATUS_COLUMN,
    )
    monkeypatch.setattr(
        peri_scribe.feed_types.requests,
        "get",
        lambda *_arguments, **_keywords: ResponseStub(payload={"other": 1}),
    )
    assert feed.current_watermark is None


def test_arc_gis_feed_current_watermark_returns_none_without_last_edit_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    feed = peri_scribe.feed_types.ArcGISFeed(
        url=SAMPLE_FEED_URL,
        fire_name_column=SAMPLE_FIRE_NAME_COLUMN,
        status_column=SAMPLE_STATUS_COLUMN,
    )
    monkeypatch.setattr(
        peri_scribe.feed_types.requests,
        "get",
        lambda *_arguments, **_keywords: ResponseStub(payload={"editingInfo": {}}),
    )
    assert feed.current_watermark is None


def test_arc_gis_feed_satisfies_feed_protocol() -> None:
    feed = peri_scribe.feed_types.ArcGISFeed(
        url=SAMPLE_FEED_URL,
        fire_name_column=SAMPLE_FIRE_NAME_COLUMN,
        status_column=SAMPLE_STATUS_COLUMN,
    )
    assert isinstance(feed, peri_scribe.feed_types.Feed)
