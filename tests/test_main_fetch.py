"""Fetch and current-timestamps command tests for peri_scribe.main."""

from __future__ import annotations

import pathlib
import time
import typing

import arcgis.features
import pyproj
import pytest
import structlog

import peri_scribe.feeds
import peri_scribe.fire_index
import peri_scribe.main
import peri_scribe.output
import peri_scribe.retry
from tests.conftest import (
    RATE_LIMIT_ERROR_PAYLOAD,
    SAMPLE_FEED_NAME,
    SAMPLE_FEED_URL,
    invoke_fetch,
    snapshot_path,
)
from tests.factories import (
    WGS84_WKID,
    FeatureLayerStub,
    GeoPackageStore,
    wgs84_feature_set,
)
from tests.main_stubs import (
    BASE_DIRECTORY,
    SAMPLE_LAST_EDIT_TIMESTAMP,
    DeltaFeatureLayerStub,
    FeedStub,
    FetchStubs,
    MultiQueryLayerStub,
    RecordingFeatureLayerStub,
    SequenceFeatureLayerStub,
)


if typing.TYPE_CHECKING:
    import click.testing


@pytest.mark.usefixtures("fetch_setup")
def test_fetch_writes_geo_package(
    runner: click.testing.CliRunner,
    feature_set_with_geometry: arcgis.features.FeatureSet,
    geo_package_store: GeoPackageStore,
    fetch_stubs: FetchStubs,
) -> None:
    fetch_stubs.feature_layers(
        lambda url, gis: FeatureLayerStub(url, gis, feature_set_with_geometry),
    )
    result = invoke_fetch(runner)
    output_path = snapshot_path()
    assert result.exit_code == 0
    assert geo_package_store.has(output_path)
    written = geo_package_store.layer(output_path, SAMPLE_FEED_NAME)
    assert list(written["name"]) == ["a", "b"]
    assert written.crs == pyproj.CRS.from_epsg(WGS84_WKID)


@pytest.mark.usefixtures("fetch_setup")
def test_fetch_fails_fast_when_query_fails(
    runner: click.testing.CliRunner,
    geo_package_store: GeoPackageStore,
    fetch_stubs: FetchStubs,
) -> None:
    fetch_stubs.feature_layers(
        lambda url, gis: FeatureLayerStub(
            url,
            gis,
            arcgis.features.FeatureSet([]),
            query_error=RuntimeError("boom"),
        ),
    )
    result = invoke_fetch(runner)
    assert result.exit_code == 1
    assert f"Failed to fetch {SAMPLE_FEED_NAME}: boom" in result.output
    assert not geo_package_store.has(snapshot_path())


@pytest.mark.usefixtures("fetch_setup")
def test_fetch_fails_fast_when_feed_returns_no_features(
    runner: click.testing.CliRunner,
    geo_package_store: GeoPackageStore,
    fetch_stubs: FetchStubs,
) -> None:
    fetch_stubs.feature_layers(
        lambda url, gis: FeatureLayerStub(
            url,
            gis,
            arcgis.features.FeatureSet([]),
        ),
    )
    result = invoke_fetch(runner)
    assert result.exit_code == 1
    assert (
        f"Failed to fetch {SAMPLE_FEED_NAME}: "
        f"Feed {SAMPLE_FEED_NAME} returned no features; no output was written"
    ) in result.output
    assert not geo_package_store.has(snapshot_path())


def test_current_timestamps_logs_each_feed_last_edit_timestamp(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
) -> None:
    monkeypatch.setattr(
        peri_scribe.output,
        "configure_logging",
        lambda log_level: log_level,
    )
    feeds = [
        FeedStub(
            name="One",
            url="https://example.test/one",
            last_edit_timestamp=1,
        ),
        FeedStub(
            name="Two",
            url="https://example.test/two",
            last_edit_timestamp=2,
        ),
    ]
    monkeypatch.setattr(peri_scribe.feeds, "FEEDS", feeds)
    with structlog.testing.capture_logs() as captured:
        result = runner.invoke(peri_scribe.main.cli, ["current-timestamps"])
    assert result.exit_code == 0
    assert len(captured) == len(feeds)
    for index, (event, feed) in enumerate(
        zip(captured, feeds, strict=True),
        start=1,
    ):
        assert event["event"] == f"Feed {index}"
        assert event["name"] == feed.name
        assert event["url"] == feed.url
        assert event["last_edit_timestamp"] == feed.last_edit_timestamp


@pytest.mark.usefixtures("fetch_setup")
def test_fetch_retries_on_429_and_succeeds(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
    feature_set_with_geometry: arcgis.features.FeatureSet,
    geo_package_store: GeoPackageStore,
    fetch_stubs: FetchStubs,
) -> None:
    sleep_calls: list[float] = []
    monkeypatch.setattr(time, "sleep", sleep_calls.append)
    rate_limit_error = ValueError(RATE_LIMIT_ERROR_PAYLOAD)
    outcomes: list[arcgis.features.FeatureSet | Exception] = [
        rate_limit_error,
        feature_set_with_geometry,
    ]
    fetch_stubs.feature_layers(
        lambda url, gis: MultiQueryLayerStub(url, gis, outcomes),
    )
    result = invoke_fetch(runner)
    output_path = snapshot_path()
    assert result.exit_code == 0
    assert geo_package_store.has(output_path)
    assert sleep_calls == [60.0]
    written = geo_package_store.layer(output_path, SAMPLE_FEED_NAME)
    assert list(written["name"]) == ["a", "b"]


@pytest.mark.usefixtures("fetch_setup")
def test_fetch_exhausts_retries_and_exits(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
    geo_package_store: GeoPackageStore,
    fetch_stubs: FetchStubs,
) -> None:
    sleep_calls: list[float] = []
    monkeypatch.setattr(time, "sleep", sleep_calls.append)
    rate_limit_error = ValueError(RATE_LIMIT_ERROR_PAYLOAD)
    max_retries = peri_scribe.retry.DEFAULT_MAX_RETRIES
    outcomes: list[arcgis.features.FeatureSet | Exception] = [rate_limit_error] * (
        max_retries + 2
    )
    fetch_stubs.feature_layers(
        lambda url, gis: MultiQueryLayerStub(url, gis, outcomes),
    )
    result = invoke_fetch(runner)
    assert result.exit_code == 1
    assert (
        f"Failed to fetch {SAMPLE_FEED_NAME}: {RATE_LIMIT_ERROR_PAYLOAD}"
        in result.output
    )
    assert sleep_calls == [60.0] * max_retries
    assert not geo_package_store.has(snapshot_path())


@pytest.mark.usefixtures("fetch_setup")
def test_fetch_writes_one_file_per_source_named_by_last_edit_timestamp(
    runner: click.testing.CliRunner,
    feature_set_with_geometry: arcgis.features.FeatureSet,
    geo_package_store: GeoPackageStore,
    fetch_stubs: FetchStubs,
) -> None:
    first_last_edit_timestamp = 1
    second_last_edit_timestamp = 2
    first = FeedStub(
        name="First_Source_0",
        url="https://example.test/first",
        last_edit_timestamp=first_last_edit_timestamp,
    )
    second = FeedStub(
        name="Second_Source_0",
        url="https://example.test/second",
        last_edit_timestamp=second_last_edit_timestamp,
    )
    fetch_stubs.feeds(first, second)
    fetch_stubs.feature_layers(
        lambda url, gis: FeatureLayerStub(url, gis, feature_set_with_geometry),
    )
    result = invoke_fetch(runner)
    assert result.exit_code == 0
    first_path = snapshot_path(
        feed_name=first.name,
        last_edit_timestamp=first_last_edit_timestamp,
    )
    second_path = snapshot_path(
        feed_name=second.name,
        last_edit_timestamp=second_last_edit_timestamp,
    )
    assert geo_package_store.has(first_path)
    assert geo_package_store.has(second_path)
    assert first_path.parent == (
        BASE_DIRECTORY / "data" / "2026" / "sources" / "First_Source_0" / "000___"
    )
    assert second_path.parent == (
        BASE_DIRECTORY / "data" / "2026" / "sources" / "Second_Source_0" / "000___"
    )
    assert list(
        geo_package_store.layer(first_path, "First_Source_0")["name"],
    ) == [
        "a",
        "b",
    ]
    assert list(
        geo_package_store.layer(second_path, "Second_Source_0")["name"],
    ) == [
        "a",
        "b",
    ]


@pytest.mark.usefixtures("fetch_setup")
def test_fetch_increments_serial_number_for_new_last_edit_timestamp(
    runner: click.testing.CliRunner,
    geo_package_store: GeoPackageStore,
    fetch_stubs: FetchStubs,
) -> None:
    first_last_edit_timestamp = 1
    second_last_edit_timestamp = 2
    full = wgs84_feature_set([
        (1, "a", 1.0, 2.0),
        (2, "b", 3.0, 4.0),
    ])
    delta = wgs84_feature_set([(3, "c", 5.0, 6.0)])
    fetch_stubs.feature_layers(
        lambda url, gis: DeltaFeatureLayerStub(url, gis, full, delta),
    )
    fetch_stubs.feeds(
        FeedStub(
            name=SAMPLE_FEED_NAME,
            url=SAMPLE_FEED_URL,
            last_edit_timestamp=first_last_edit_timestamp,
        ),
    )
    assert invoke_fetch(runner).exit_code == 0
    fetch_stubs.feeds(
        FeedStub(
            name=SAMPLE_FEED_NAME,
            url=SAMPLE_FEED_URL,
            last_edit_timestamp=second_last_edit_timestamp,
        ),
    )
    assert invoke_fetch(runner).exit_code == 0
    first_path = snapshot_path(
        serial_number=0,
        last_edit_timestamp=first_last_edit_timestamp,
    )
    second_path = snapshot_path(
        serial_number=1,
        last_edit_timestamp=second_last_edit_timestamp,
    )
    assert geo_package_store.has(first_path)
    assert geo_package_store.has(second_path)
    assert list(
        geo_package_store.layer(first_path, SAMPLE_FEED_NAME)["name"],
    ) == [
        "a",
        "b",
    ]
    assert list(
        geo_package_store.layer(second_path, SAMPLE_FEED_NAME)["name"],
    ) == [
        "c",
    ]


@pytest.mark.usefixtures("fetch_setup")
def test_fetch_writes_no_new_file_when_nothing_changed(
    runner: click.testing.CliRunner,
    geo_package_store: GeoPackageStore,
    fetch_stubs: FetchStubs,
) -> None:
    first_last_edit_timestamp = 1
    second_last_edit_timestamp = 2
    full = wgs84_feature_set([
        (1, "a", 1.0, 2.0),
        (2, "b", 3.0, 4.0),
    ])
    fetch_stubs.feature_layers(
        lambda url, gis: DeltaFeatureLayerStub(
            url,
            gis,
            full,
            arcgis.features.FeatureSet([]),
        ),
    )
    fetch_stubs.feeds(
        FeedStub(
            name=SAMPLE_FEED_NAME,
            url=SAMPLE_FEED_URL,
            last_edit_timestamp=first_last_edit_timestamp,
        ),
    )
    assert invoke_fetch(runner).exit_code == 0
    fetch_stubs.feeds(
        FeedStub(
            name=SAMPLE_FEED_NAME,
            url=SAMPLE_FEED_URL,
            last_edit_timestamp=second_last_edit_timestamp,
        ),
    )
    assert invoke_fetch(runner).exit_code == 0
    assert geo_package_store.has(
        snapshot_path(
            serial_number=0,
            last_edit_timestamp=first_last_edit_timestamp,
        ),
    )
    assert not geo_package_store.has(
        snapshot_path(
            serial_number=1,
            last_edit_timestamp=second_last_edit_timestamp,
        ),
    )


@pytest.mark.usefixtures("fetch_setup")
def test_fetch_reuses_serial_number_for_unchanged_last_edit_timestamp(
    runner: click.testing.CliRunner,
    feature_set_with_geometry: arcgis.features.FeatureSet,
    geo_package_store: GeoPackageStore,
    fetch_stubs: FetchStubs,
) -> None:
    last_edit_timestamp = 1
    fetch_stubs.feature_layers(
        lambda url, gis: FeatureLayerStub(url, gis, feature_set_with_geometry),
    )
    fetch_stubs.feeds(
        FeedStub(
            name=SAMPLE_FEED_NAME,
            url=SAMPLE_FEED_URL,
            last_edit_timestamp=last_edit_timestamp,
        ),
    )
    assert invoke_fetch(runner).exit_code == 0
    assert invoke_fetch(runner).exit_code == 0
    assert geo_package_store.has(
        snapshot_path(serial_number=0, last_edit_timestamp=last_edit_timestamp),
    )
    assert not geo_package_store.has(
        snapshot_path(serial_number=1, last_edit_timestamp=last_edit_timestamp),
    )


@pytest.mark.usefixtures("fetch_setup")
def test_fetch_fails_fast_when_last_edit_timestamp_cannot_be_observed(
    runner: click.testing.CliRunner,
    geo_package_store: GeoPackageStore,
    fetch_stubs: FetchStubs,
) -> None:
    fetch_stubs.feeds(
        FeedStub(name=SAMPLE_FEED_NAME, url=SAMPLE_FEED_URL, last_edit_timestamp=None),
    )
    result = invoke_fetch(runner)
    assert result.exit_code == 1
    assert (
        f"Failed to fetch {SAMPLE_FEED_NAME}: no last-edit timestamp could be observed"
        in result.output
    )
    assert not geo_package_store.has(snapshot_path())


@pytest.mark.usefixtures("fetch_setup")
def test_fetch_observes_last_edit_timestamp_before_downloading(
    runner: click.testing.CliRunner,
    feature_set_with_geometry: arcgis.features.FeatureSet,
    fetch_stubs: FetchStubs,
) -> None:
    events: list[str] = []
    feed = FeedStub(
        name=SAMPLE_FEED_NAME,
        url=SAMPLE_FEED_URL,
        last_edit_timestamp=SAMPLE_LAST_EDIT_TIMESTAMP,
        events=events,
    )
    fetch_stubs.feeds(feed)
    fetch_stubs.feature_layers(
        lambda url, gis: RecordingFeatureLayerStub(
            url,
            gis,
            feature_set_with_geometry,
            events,
        ),
    )
    result = invoke_fetch(runner)
    assert result.exit_code == 0
    assert events == ["timestamp", "download"]


@pytest.mark.usefixtures("fetch_setup")
def test_fetch_skips_download_when_last_edit_timestamp_already_present(
    runner: click.testing.CliRunner,
    feature_set_with_geometry: arcgis.features.FeatureSet,
    fetch_stubs: FetchStubs,
) -> None:
    events: list[str] = []
    feed = FeedStub(
        name=SAMPLE_FEED_NAME,
        url=SAMPLE_FEED_URL,
        last_edit_timestamp=SAMPLE_LAST_EDIT_TIMESTAMP,
        events=events,
    )
    fetch_stubs.feeds(feed)
    fetch_stubs.feature_layers(
        lambda url, gis: RecordingFeatureLayerStub(
            url,
            gis,
            feature_set_with_geometry,
            events,
        ),
    )
    # The first fetch downloads and writes the snapshot.
    assert invoke_fetch(runner).exit_code == 0
    assert events == ["timestamp", "download"]
    events.clear()
    # The second fetch sees the same last-edit timestamp in the REST call and skips.
    with structlog.testing.capture_logs() as captured:
        result = invoke_fetch(runner)
    assert result.exit_code == 0
    assert events == ["timestamp"]
    (skip_event,) = [
        event
        for event in captured
        if event["event"] == "Skipping fetch; data already present"
    ]
    assert skip_event["feed"] == SAMPLE_FEED_NAME
    assert skip_event["last_edit_timestamp"] == SAMPLE_LAST_EDIT_TIMESTAMP
    assert skip_event["path"] == snapshot_path()


@pytest.mark.usefixtures("fetch_setup")
def test_fetch_full_downloads_when_last_edit_timestamp_already_present(
    runner: click.testing.CliRunner,
    geo_package_store: GeoPackageStore,
    fetch_stubs: FetchStubs,
) -> None:
    first = wgs84_feature_set([
        (1, "a", 1.0, 2.0),
        (2, "b", 3.0, 4.0),
    ])
    second = wgs84_feature_set([
        (1, "a-changed", 1.0, 2.0),
        (2, "b", 3.0, 4.0),
    ])
    events: list[str] = []
    feed = FeedStub(
        name=SAMPLE_FEED_NAME,
        url=SAMPLE_FEED_URL,
        last_edit_timestamp=SAMPLE_LAST_EDIT_TIMESTAMP,
        events=events,
    )
    fetch_stubs.feeds(feed)
    layer_stub = SequenceFeatureLayerStub(
        url=SAMPLE_FEED_URL,
        gis=object(),
        feature_sets=[first, second],
        events=events,
    )
    fetch_stubs.feature_layers(lambda _url, _gis: layer_stub)
    # The first fetch downloads and writes the snapshot.
    assert invoke_fetch(runner).exit_code == 0
    assert events == ["timestamp", "download"]
    events.clear()
    # A full fetch downloads even though the last-edit timestamp is unchanged, and
    # writes a fresh snapshot holding only the changed feature.
    result = invoke_fetch(runner, "--full")
    assert result.exit_code == 0
    assert events == ["timestamp", "download"]
    first_path = snapshot_path(
        serial_number=0,
        last_edit_timestamp=SAMPLE_LAST_EDIT_TIMESTAMP,
    )
    second_path = snapshot_path(
        serial_number=1,
        last_edit_timestamp=SAMPLE_LAST_EDIT_TIMESTAMP,
    )
    assert geo_package_store.has(first_path)
    assert geo_package_store.has(second_path)
    assert list(
        geo_package_store.layer(second_path, SAMPLE_FEED_NAME)["name"],
    ) == ["a-changed"]


@pytest.mark.usefixtures("fetch_setup")
def test_fetch_full_writes_no_new_file_when_nothing_changed(
    runner: click.testing.CliRunner,
    geo_package_store: GeoPackageStore,
    fetch_stubs: FetchStubs,
) -> None:
    full = wgs84_feature_set([
        (1, "a", 1.0, 2.0),
        (2, "b", 3.0, 4.0),
    ])
    layer_stub = SequenceFeatureLayerStub(
        url=SAMPLE_FEED_URL,
        gis=object(),
        feature_sets=[full, full],
    )
    fetch_stubs.feature_layers(lambda _url, _gis: layer_stub)
    fetch_stubs.feeds(
        FeedStub(
            name=SAMPLE_FEED_NAME,
            url=SAMPLE_FEED_URL,
            last_edit_timestamp=SAMPLE_LAST_EDIT_TIMESTAMP,
        ),
    )
    assert invoke_fetch(runner).exit_code == 0
    result = invoke_fetch(runner, "--full")
    assert result.exit_code == 0
    assert geo_package_store.has(
        snapshot_path(
            serial_number=0,
            last_edit_timestamp=SAMPLE_LAST_EDIT_TIMESTAMP,
        ),
    )
    assert not geo_package_store.has(
        snapshot_path(
            serial_number=1,
            last_edit_timestamp=SAMPLE_LAST_EDIT_TIMESTAMP,
        ),
    )


@pytest.mark.usefixtures("fetch_setup")
def test_fetch_reindexes_fire_sources_after_successful_fetch(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
    feature_set_with_geometry: arcgis.features.FeatureSet,
    fetch_stubs: FetchStubs,
) -> None:
    fetch_stubs.feature_layers(
        lambda url, gis: FeatureLayerStub(url, gis, feature_set_with_geometry),
    )
    indexed: list[pathlib.Path] = []
    monkeypatch.setattr(
        peri_scribe.fire_index,
        "index_fire_sources",
        indexed.append,
    )
    result = invoke_fetch(runner)
    assert result.exit_code == 0
    assert indexed == [BASE_DIRECTORY / "data" / "2026"]


@pytest.mark.usefixtures("fetch_setup")
def test_fetch_reindexes_after_a_feed_fails(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
    feature_set_with_geometry: arcgis.features.FeatureSet,
    geo_package_store: GeoPackageStore,
    fetch_stubs: FetchStubs,
) -> None:
    failing = FeedStub(
        name="Failing_0",
        url="https://example.test/failing",
        last_edit_timestamp=SAMPLE_LAST_EDIT_TIMESTAMP,
    )
    working = FeedStub(
        name="Working_0",
        url="https://example.test/working",
        last_edit_timestamp=SAMPLE_LAST_EDIT_TIMESTAMP,
    )
    fetch_stubs.feeds(failing, working)

    def layer_factory(url: str, gis: object) -> FeatureLayerStub:
        if url == failing.url:
            return FeatureLayerStub(
                url,
                gis,
                arcgis.features.FeatureSet([]),
                query_error=RuntimeError("boom"),
            )
        return FeatureLayerStub(url, gis, feature_set_with_geometry)

    fetch_stubs.feature_layers(layer_factory)
    indexed: list[pathlib.Path] = []
    monkeypatch.setattr(
        peri_scribe.fire_index,
        "index_fire_sources",
        indexed.append,
    )
    result = invoke_fetch(runner)
    assert result.exit_code == 1
    assert indexed == [BASE_DIRECTORY / "data" / "2026"]
    assert geo_package_store.has(snapshot_path(feed_name=working.name))
    assert not geo_package_store.has(snapshot_path(feed_name=failing.name))
    assert f"Failed to fetch {failing.name}: boom" in result.output


@pytest.mark.usefixtures("fetch_setup")
def test_fetch_does_not_reindex_when_no_feed_succeeds(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
    fetch_stubs: FetchStubs,
) -> None:
    fetch_stubs.feature_layers(
        lambda url, gis: FeatureLayerStub(
            url,
            gis,
            arcgis.features.FeatureSet([]),
            query_error=RuntimeError("boom"),
        ),
    )
    indexed: list[pathlib.Path] = []
    monkeypatch.setattr(
        peri_scribe.fire_index,
        "index_fire_sources",
        indexed.append,
    )
    result = invoke_fetch(runner)
    assert result.exit_code == 1
    assert indexed == []
    assert f"Failed to fetch {SAMPLE_FEED_NAME}: boom" in result.output
