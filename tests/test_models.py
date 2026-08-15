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


def test_fire_complex_links_fires_circularly() -> None:
    fire = peri_scribe.models.Fire(
        name="Crosswhite",
        status=peri_scribe.models.FireStatus.ACTIVE,
    )
    fire_complex = peri_scribe.models.FireComplex(
        name="ROWE CREEK COMPLEX",
        identifier="b8431c26-6a9b-4ef0-88d8-f7ea9a3f56c3",
        fires=frozenset({fire}),
    )
    assert fire.complex is fire_complex
    assert fire_complex.fires == frozenset({fire})
    assert next(iter(fire_complex.fires)).complex is fire_complex


def test_fire_complex_does_not_link_when_it_has_no_fires() -> None:
    fire_complex = peri_scribe.models.FireComplex(
        name="ROWE CREEK COMPLEX",
        identifier="b8431c26-6a9b-4ef0-88d8-f7ea9a3f56c3",
        fires=frozenset(),
    )
    assert fire_complex.fires == frozenset()


def test_fire_equality_ignores_complex() -> None:
    left_fire = peri_scribe.models.Fire(
        name="Crosswhite",
        status=peri_scribe.models.FireStatus.ACTIVE,
        identifier="1b0219ee-5298-4fef-9927-c2666d9d53fc",
    )
    right_fire = peri_scribe.models.Fire(
        name="Crosswhite",
        status=peri_scribe.models.FireStatus.ACTIVE,
        identifier="1b0219ee-5298-4fef-9927-c2666d9d53fc",
    )
    peri_scribe.models.FireComplex(
        name="ROWE CREEK COMPLEX",
        identifier="b8431c26-6a9b-4ef0-88d8-f7ea9a3f56c3",
        fires=frozenset({left_fire}),
    )
    peri_scribe.models.FireComplex(
        name="HAY CREEK COMPLEX",
        identifier="851ddf21-4ead-4835-b54b-b3cf7bd6ac21",
        fires=frozenset({right_fire}),
    )
    assert left_fire == right_fire


def test_fire_hash_ignores_complex() -> None:
    fire = peri_scribe.models.Fire(
        name="Crosswhite",
        status=peri_scribe.models.FireStatus.ACTIVE,
        identifier="1b0219ee-5298-4fef-9927-c2666d9d53fc",
    )
    hash_before = hash(fire)
    peri_scribe.models.FireComplex(
        name="ROWE CREEK COMPLEX",
        identifier="b8431c26-6a9b-4ef0-88d8-f7ea9a3f56c3",
        fires=frozenset({fire}),
    )
    assert hash(fire) == hash_before
    assert fire == peri_scribe.models.Fire(
        name="Crosswhite",
        status=peri_scribe.models.FireStatus.ACTIVE,
        identifier="1b0219ee-5298-4fef-9927-c2666d9d53fc",
    )


def test_fire_complex_equality() -> None:
    left = peri_scribe.models.FireComplex(
        name="ROWE CREEK COMPLEX",
        identifier="b8431c26-6a9b-4ef0-88d8-f7ea9a3f56c3",
        fires=frozenset({
            peri_scribe.models.Fire(
                name="Crosswhite",
                status=peri_scribe.models.FireStatus.ACTIVE,
            ),
        }),
    )
    right = peri_scribe.models.FireComplex(
        name="ROWE CREEK COMPLEX",
        identifier="b8431c26-6a9b-4ef0-88d8-f7ea9a3f56c3",
        fires=frozenset({
            peri_scribe.models.Fire(
                name="Crosswhite",
                status=peri_scribe.models.FireStatus.ACTIVE,
            ),
        }),
    )
    assert left == right


def test_fire_complex_repr_does_not_recurse() -> None:
    fire = peri_scribe.models.Fire(
        name="Crosswhite",
        status=peri_scribe.models.FireStatus.ACTIVE,
    )
    fire_complex = peri_scribe.models.FireComplex(
        name="ROWE CREEK COMPLEX",
        identifier="b8431c26-6a9b-4ef0-88d8-f7ea9a3f56c3",
        fires=frozenset({fire}),
    )
    assert "ROWE CREEK COMPLEX" in repr(fire_complex)
    assert "Crosswhite" in repr(fire_complex)
    assert "complex" not in repr(fire)
