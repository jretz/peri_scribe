import dataclasses

import peri_scribe.feed_types
import peri_scribe.models
from tests.conftest import (
    SAMPLE_FEED_NAME,
    SAMPLE_FEED_URL,
    SAMPLE_FIRE_NAME_COLUMN,
    SAMPLE_STATUS_COLUMN,
)


EXPECTED_TWO_FEEDS = 2


def test_build_feeds_creates_arc_gis_feed_from_config() -> None:
    configs = [
        {
            "feed_type": "ArcGISFeed",
            "url": SAMPLE_FEED_URL,
            "fire_name_column": SAMPLE_FIRE_NAME_COLUMN,
            "status_column": SAMPLE_STATUS_COLUMN,
        },
    ]
    feeds = peri_scribe.models.build_feeds(configs)
    assert len(feeds) == 1
    feed = feeds[0]
    assert isinstance(feed, peri_scribe.feed_types.Feed)
    assert isinstance(feed, peri_scribe.feed_types.ArcGISFeed)
    assert feed.url == SAMPLE_FEED_URL
    assert feed.name == SAMPLE_FEED_NAME


def test_build_feeds_uses_decorator_style_registration() -> None:
    """build_feeds works with classes registered via the decorator."""

    @peri_scribe.feed_types.FeedTypes.register
    @dataclasses.dataclass(frozen=True, kw_only=True)
    class TestFeed:
        label: str

    configs = [{"feed_type": "TestFeed", "label": "hello"}]
    feeds = peri_scribe.models.build_feeds(configs)
    assert len(feeds) == 1
    feed = feeds[0]
    assert isinstance(feed, TestFeed)
    assert feed.label == "hello"


def test_build_feeds_constructs_multiple_feeds() -> None:
    configs = [
        {
            "feed_type": "ArcGISFeed",
            "url": SAMPLE_FEED_URL,
            "fire_name_column": SAMPLE_FIRE_NAME_COLUMN,
            "status_column": SAMPLE_STATUS_COLUMN,
        },
        {
            "feed_type": "ArcGISFeed",
            "url": SAMPLE_FEED_URL + "extra/",
            "fire_name_column": SAMPLE_FIRE_NAME_COLUMN,
            "status_column": SAMPLE_STATUS_COLUMN,
        },
    ]
    feeds = peri_scribe.models.build_feeds(configs)
    assert len(feeds) == EXPECTED_TWO_FEEDS
    assert feeds[0].url == SAMPLE_FEED_URL
    assert feeds[1].url == SAMPLE_FEED_URL + "extra/"
