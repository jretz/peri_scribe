"""Tests for peri_scribe.feed_types."""

import dataclasses

import pytest

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
