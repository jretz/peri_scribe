"""Independent feeds overlap while collection order and failures stay explicit."""

import asyncio
import functools
import pathlib

import pytest

import peri_scribe.sources.feeds
import peri_scribe.sources.fetching
import tests.helpers.doubles.concurrency
import tests.helpers.doubles.errors
import tests.helpers.doubles.peri_scribe.sources.fetching


@pytest.mark.asyncio
async def test_collect_feeds_bounds_overlap_and_preserves_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capacity = 2
    probe = tests.helpers.doubles.concurrency.ConcurrentCalls(capacity)
    feeds = [
        tests.helpers.doubles.peri_scribe.sources.fetching.FeedStub(
            name=str(index),
            url=f"https://example.test/{index}",
            last_edit_timestamp=1,
        )
        for index in range(5)
    ]
    monkeypatch.setattr(peri_scribe.sources.feeds, "FEEDS", feeds)
    monkeypatch.setattr(peri_scribe.sources.fetching, "FEED_CONCURRENCY", capacity)
    task = asyncio.create_task(
        peri_scribe.sources.fetching.collect_feeds(
            functools.partial(
                tests.helpers.doubles.peri_scribe.sources.fetching.fetch_with_probe,
                probe,
            ),
        ),
    )
    try:
        assert await asyncio.to_thread(probe.ready.wait, 5)
        assert len(probe.started) == capacity
    finally:
        probe.release.set()
    outcomes = await task
    assert probe.peak == capacity
    assert len(probe.started) == len(feeds)
    assert [outcome.path for outcome in outcomes] == [
        pathlib.Path("0"),
        None,
        pathlib.Path("2"),
        pathlib.Path("3"),
        pathlib.Path("4"),
    ]
    assert outcomes[1].error == "source unavailable"


def test_fetch_all_feeds_complete_aggregates_connection_failures(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    feeds = [
        tests.helpers.doubles.peri_scribe.sources.fetching.FeedStub(
            name=name,
            url=f"https://example.test/{name}",
            last_edit_timestamp=1,
        )
        for name in ("first", "second")
    ]
    monkeypatch.setattr(peri_scribe.sources.feeds, "FEEDS", feeds)
    monkeypatch.setattr(
        peri_scribe.sources.fetching.arcgis.gis,
        "GIS",
        tests.helpers.doubles.errors.raising_stub(RuntimeError("connection failed")),
    )
    with pytest.raises(SystemExit) as error:
        peri_scribe.sources.fetching.fetch_all_feeds_complete(tmp_path, year=2026)
    assert str(error.value).splitlines() == [
        f"Failed to fetch {feed.name}: connection failed" for feed in feeds
    ]
