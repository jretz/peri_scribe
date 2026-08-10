import peri_scribe.models
from tests.conftest import (
    SAMPLE_FEED_NAME,
    SAMPLE_FEED_URL,
    SAMPLE_LAYER_ID,
    SAMPLE_PATH_SEGMENTS,
    SAMPLE_SERVICE_NAME,
)


def test_arc_gis_feed_path_segments() -> None:
    feed = peri_scribe.models.ArcGISFeed(url=SAMPLE_FEED_URL)
    assert feed.path_segments == SAMPLE_PATH_SEGMENTS


def test_arc_gis_feed_path_segments_ignore_empty_segments() -> None:
    feed = peri_scribe.models.ArcGISFeed(url=SAMPLE_FEED_URL + "/")
    assert feed.path_segments == SAMPLE_PATH_SEGMENTS


def test_arc_gis_feed_service_name() -> None:
    feed = peri_scribe.models.ArcGISFeed(url=SAMPLE_FEED_URL)
    assert feed.service_name == SAMPLE_SERVICE_NAME


def test_arc_gis_feed_layer_id() -> None:
    feed = peri_scribe.models.ArcGISFeed(url=SAMPLE_FEED_URL)
    assert feed.layer_id == SAMPLE_LAYER_ID


def test_arc_gis_feed_name() -> None:
    feed = peri_scribe.models.ArcGISFeed(url=SAMPLE_FEED_URL)
    assert feed.name == SAMPLE_FEED_NAME
