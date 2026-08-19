"""CLI and integration tests for peri_scribe.main."""

import dataclasses
import datetime
import pathlib
import time
import typing
from typing import TYPE_CHECKING

import arcgis.features
import pyproj
import pytest
import structlog
import time_machine

import peri_scribe.administrative_boundaries
import peri_scribe.exceptions
import peri_scribe.fetching
import peri_scribe.fire_index
import peri_scribe.main
import peri_scribe.models
import peri_scribe.output
import peri_scribe.retry
import peri_scribe.snapshots
from tests.conftest import (
    CLICK_USAGE_ERROR_EXIT_CODE,
    RATE_LIMIT_ERROR_PAYLOAD,
    SAMPLE_FEED_NAME,
    SAMPLE_FEED_URL,
    WGS84_WKID,
    FeatureLayerStub,
    FeatureLayerStubBase,
    GeoPackageStore,
    wgs84_feature_set,
)


if TYPE_CHECKING:
    import click.testing


SAMPLE_WATERMARK = "lastEdit=2"

# The base directory fetch resolves from ``pathlib.Path.cwd()``, which is mocked to
# this value so snapshots never touch the real filesystem.
BASE_DIRECTORY = pathlib.Path("/fetch")

# A FeatureLayer factory, as installed for the fetch command's layer construction.
LayerFactory = typing.Callable[[str, object], object]


class MultiQueryLayerStub(FeatureLayerStubBase):
    """FeatureLayer stand-in that returns/raises successive results per call."""

    def __init__(
        self,
        url: str,
        gis: object,
        query_outcomes: list[arcgis.features.FeatureSet | Exception],
    ) -> None:
        super().__init__(url, gis)
        self.query_outcomes = list(query_outcomes)
        self.call_count = 0

    def query(self) -> arcgis.features.FeatureSet:
        outcome = self.query_outcomes[self.call_count]
        self.call_count += 1
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class DeltaFeatureLayerStub(FeatureLayerStubBase):
    """FeatureLayer stand-in serving a full set, then an incremental delta."""

    def __init__(
        self,
        url: str,
        gis: object,
        full: arcgis.features.FeatureSet,
        delta: arcgis.features.FeatureSet,
    ) -> None:
        super().__init__(url, gis)
        self.full = full
        self.delta = delta

    def query(
        self,
        **parameters: object,
    ) -> arcgis.features.FeatureSet | dict[str, object]:
        if parameters.get("return_ids_only"):
            object_ids = [
                feature.attributes["OBJECTID"] for feature in self.delta.features
            ]
            return {"objectIdFieldName": "OBJECTID", "objectIds": object_ids}
        if parameters.get("object_ids"):
            return self.delta
        return self.full


@dataclasses.dataclass(frozen=True, kw_only=True)
class FeedStub:
    """Minimal feed stand-in with a fixed current watermark."""

    name: str
    url: str
    watermark: str | None
    modified_column: str = "ModifiedOnDateTime_dt"
    events: list[str] = dataclasses.field(default_factory=list)

    @property
    def current_watermark(self) -> str | None:
        self.events.append("watermark")
        return self.watermark


class RecordingFeatureLayerStub(FeatureLayerStubBase):
    """FeatureLayer stand-in that records when its data is downloaded."""

    def __init__(
        self,
        url: str,
        gis: object,
        feature_set: arcgis.features.FeatureSet,
        events: list[str],
    ) -> None:
        super().__init__(url, gis)
        self.feature_set = feature_set
        self.events = events

    def query(self) -> arcgis.features.FeatureSet:
        self.events.append("download")
        return self.feature_set


@pytest.fixture
def fetch_setup(
    monkeypatch: pytest.MonkeyPatch,
    geo_package_store: GeoPackageStore,
) -> typing.Iterator[None]:
    """Point the fetch command's boundaries at in-memory stubs and fix the date."""
    monkeypatch.setattr(
        pathlib.Path,
        "cwd",
        staticmethod(lambda: BASE_DIRECTORY),
    )
    monkeypatch.setattr(
        peri_scribe.output,
        "configure_logging",
        lambda log_level: log_level,
    )
    monkeypatch.setattr(
        peri_scribe.models,
        "FEEDS",
        [
            FeedStub(
                name=SAMPLE_FEED_NAME,
                url=SAMPLE_FEED_URL,
                watermark=SAMPLE_WATERMARK,
            ),
        ],
    )
    monkeypatch.setattr(peri_scribe.fetching.arcgis.gis, "GIS", object)
    monkeypatch.setattr(
        peri_scribe.fire_index,
        "index_fire_sources",
        lambda _year_directory: None,
    )
    with time_machine.travel(
        datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
        tick=False,
    ):
        yield


def snapshot_path(
    *,
    feed_name: str = SAMPLE_FEED_NAME,
    serial_number: int = 0,
    watermark: str = SAMPLE_WATERMARK,
) -> pathlib.Path:
    """Return the snapshot path fetch writes for a feed and watermark.

    Returns:
        The snapshot path, assuming the 2026 test year, no prior snapshots, and a
        first serial number of 0.
    """
    return peri_scribe.snapshots.source_geopackage_path(
        BASE_DIRECTORY,
        2026,
        feed_name,
        serial_number,
        watermark,
    )


@pytest.fixture
def list_fires_setup(monkeypatch: pytest.MonkeyPatch) -> None:
    """Silence log configuration so list-fires logs can be captured."""
    monkeypatch.setattr(
        peri_scribe.output,
        "configure_logging",
        lambda log_level: log_level,
    )


def invoke_fetch(
    runner: click.testing.CliRunner,
) -> click.testing.Result:
    """Invoke the fetch command in the test runner.

    Returns:
        The command result.
    """
    return runner.invoke(peri_scribe.main.cli, ["fetch"])


@dataclasses.dataclass(frozen=True, kw_only=True)
class FetchStubs:
    """Feed and FeatureLayer installers for fetch tests."""

    feeds: typing.Callable[..., None]
    feature_layers: typing.Callable[[LayerFactory], None]


@pytest.fixture
def fetch_stubs(
    monkeypatch: pytest.MonkeyPatch,
) -> FetchStubs:
    """Install feed and FeatureLayer stubs for the fetch command.

    Returns:
        The installers for feeds and FeatureLayer factories.
    """

    def stub_feeds(*feeds: FeedStub) -> None:
        monkeypatch.setattr(peri_scribe.models, "FEEDS", list(feeds))

    def stub_feature_layers(factory: LayerFactory) -> None:
        monkeypatch.setattr(
            peri_scribe.fetching.arcgis.features,
            "FeatureLayer",
            factory,
        )

    return FetchStubs(
        feeds=stub_feeds,
        feature_layers=stub_feature_layers,
    )


@pytest.fixture
def current_year(
    monkeypatch: pytest.MonkeyPatch,
) -> typing.Iterator[None]:
    """Fix the working directory and freeze the current year at 2026."""
    monkeypatch.setattr(
        pathlib.Path,
        "cwd",
        staticmethod(lambda: BASE_DIRECTORY),
    )
    with time_machine.travel(
        datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
        tick=False,
    ):
        yield


@pytest.mark.usefixtures("list_fires_setup")
def test_list_fires_defaults_to_current_year_directory(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
    current_year: typing.Iterator[None],
) -> None:
    indexed: list[pathlib.Path] = []

    def load_fire_index(
        year_directory: pathlib.Path,
    ) -> peri_scribe.models.FireIndex:
        indexed.append(year_directory)
        return peri_scribe.models.FireIndex.model_validate({
            "version": "2026-08-17",
            "fires": [],
        })

    monkeypatch.setattr(
        peri_scribe.fire_index,
        "load_fire_index",
        load_fire_index,
    )
    result = runner.invoke(peri_scribe.main.cli, ["list-fires"])
    assert result.exit_code == 0
    assert indexed == [BASE_DIRECTORY / "data" / "2026"]


def test_list_fires_help_names_current_year_default(
    runner: click.testing.CliRunner,
) -> None:
    result = runner.invoke(peri_scribe.main.cli, ["list-fires", "--help"])
    assert result.exit_code == 0
    assert (
        f"{peri_scribe.output.DATA_DIRECTORY}/{datetime.date.today().year}"
    ) in result.output
    assert "data/<current year>" not in result.output


@pytest.mark.usefixtures("list_fires_setup")
def test_list_fires_logs_fire_names_and_statuses(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
) -> None:
    index = peri_scribe.models.FireIndex.model_validate({
        "version": "2026-08-17",
        "fires": [
            {"name": "Park Fire", "status": "active", "paths": []},
            {"name": "ALTA", "status": "inactive", "paths": []},
        ],
    })
    monkeypatch.setattr(
        peri_scribe.fire_index,
        "load_fire_index",
        lambda _year_directory: index,
    )
    with structlog.testing.capture_logs() as captured:
        result = runner.invoke(
            peri_scribe.main.cli,
            ["list-fires", "."],
        )
    assert result.exit_code == 0
    assert [(event["name"], event["status"]) for event in captured] == [
        ("Park Fire", "active"),
        ("ALTA", "inactive"),
    ]


@pytest.mark.usefixtures("list_fires_setup")
def test_list_fires_propagates_index_build_error(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
) -> None:
    def fail(_year_directory: pathlib.Path) -> typing.Never:
        layer_name = "Mystery_Layer_0"
        raise peri_scribe.exceptions.UnknownLayerError(
            layer_name,
            pathlib.Path("fires.gpkg"),
        )

    monkeypatch.setattr(
        peri_scribe.fire_index,
        "load_fire_index",
        fail,
    )
    result = runner.invoke(peri_scribe.main.cli, ["list-fires", "."])
    assert result.exit_code == 1
    assert isinstance(result.exception, peri_scribe.exceptions.UnknownLayerError)


def test_list_fires_rejects_missing_directory(
    runner: click.testing.CliRunner,
) -> None:
    result = runner.invoke(peri_scribe.main.cli, ["list-fires", "no-such-directory"])
    assert result.exit_code == CLICK_USAGE_ERROR_EXIT_CODE
    assert "does not exist" in result.output


def test_cli_help(runner: click.testing.CliRunner) -> None:
    result = runner.invoke(peri_scribe.main.cli, ["--help"])
    assert result.exit_code == 0
    assert "systematic gathering and symbolization of fire geography" in result.output


def test_cli_invalid_log_level(runner: click.testing.CliRunner) -> None:
    result = runner.invoke(peri_scribe.main.cli, ["--log-level", "verbose"])
    assert result.exit_code == CLICK_USAGE_ERROR_EXIT_CODE
    assert "Invalid value for '--log-level'" in result.output


def test_cli_requires_subcommand(runner: click.testing.CliRunner) -> None:
    result = runner.invoke(peri_scribe.main.cli, [])
    assert result.exit_code == CLICK_USAGE_ERROR_EXIT_CODE
    assert "Commands:" in result.output
    assert "fetch" in result.output


def test_cli_configures_logging_from_log_level(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
) -> None:
    configured_levels: list[str] = []
    monkeypatch.setattr(
        peri_scribe.output,
        "configure_logging",
        configured_levels.append,
    )
    monkeypatch.setattr(peri_scribe.models, "FEEDS", [])
    result = runner.invoke(
        peri_scribe.main.cli,
        ["--log-level", "DEBUG", "current-watermarks"],
    )
    assert result.exit_code == 0
    assert configured_levels == ["debug"]


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


def test_current_watermarks_logs_each_feed_watermark(
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
            watermark="lastEdit=1",
        ),
        FeedStub(
            name="Two",
            url="https://example.test/two",
            watermark="lastEdit=2",
        ),
    ]
    monkeypatch.setattr(peri_scribe.models, "FEEDS", feeds)
    with structlog.testing.capture_logs() as captured:
        result = runner.invoke(peri_scribe.main.cli, ["current-watermarks"])
    assert result.exit_code == 0
    assert len(captured) == len(feeds)
    for index, (event, feed) in enumerate(
        zip(captured, feeds, strict=True),
        start=1,
    ):
        assert event["event"] == f"Feed {index}"
        assert event["name"] == feed.name
        assert event["url"] == feed.url
        assert event["watermark"] == feed.watermark


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
def test_fetch_writes_one_file_per_source_named_by_watermark(
    runner: click.testing.CliRunner,
    feature_set_with_geometry: arcgis.features.FeatureSet,
    geo_package_store: GeoPackageStore,
    fetch_stubs: FetchStubs,
) -> None:
    first_watermark = "lastEdit=1"
    second_watermark = "lastEdit=2"
    first = FeedStub(
        name="First_Source_0",
        url="https://example.test/first",
        watermark=first_watermark,
    )
    second = FeedStub(
        name="Second_Source_0",
        url="https://example.test/second",
        watermark=second_watermark,
    )
    fetch_stubs.feeds(first, second)
    fetch_stubs.feature_layers(
        lambda url, gis: FeatureLayerStub(url, gis, feature_set_with_geometry),
    )
    result = invoke_fetch(runner)
    assert result.exit_code == 0
    first_path = snapshot_path(
        feed_name=first.name,
        watermark=first_watermark,
    )
    second_path = snapshot_path(
        feed_name=second.name,
        watermark=second_watermark,
    )
    assert geo_package_store.has(first_path)
    assert geo_package_store.has(second_path)
    assert first_path.parent == (
        BASE_DIRECTORY / "data" / "2026" / "sources" / "First_Source_0"
    )
    assert second_path.parent == (
        BASE_DIRECTORY / "data" / "2026" / "sources" / "Second_Source_0"
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
def test_fetch_increments_serial_number_for_new_watermark(
    runner: click.testing.CliRunner,
    geo_package_store: GeoPackageStore,
    fetch_stubs: FetchStubs,
) -> None:
    first_watermark = "lastEdit=1"
    second_watermark = "lastEdit=2"
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
            watermark=first_watermark,
        ),
    )
    assert invoke_fetch(runner).exit_code == 0
    fetch_stubs.feeds(
        FeedStub(
            name=SAMPLE_FEED_NAME,
            url=SAMPLE_FEED_URL,
            watermark=second_watermark,
        ),
    )
    assert invoke_fetch(runner).exit_code == 0
    first_path = snapshot_path(
        serial_number=0,
        watermark=first_watermark,
    )
    second_path = snapshot_path(
        serial_number=1,
        watermark=second_watermark,
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
    first_watermark = "lastEdit=1"
    second_watermark = "lastEdit=2"
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
            watermark=first_watermark,
        ),
    )
    assert invoke_fetch(runner).exit_code == 0
    fetch_stubs.feeds(
        FeedStub(
            name=SAMPLE_FEED_NAME,
            url=SAMPLE_FEED_URL,
            watermark=second_watermark,
        ),
    )
    assert invoke_fetch(runner).exit_code == 0
    assert geo_package_store.has(
        snapshot_path(
            serial_number=0,
            watermark=first_watermark,
        ),
    )
    assert not geo_package_store.has(
        snapshot_path(
            serial_number=1,
            watermark=second_watermark,
        ),
    )


@pytest.mark.usefixtures("fetch_setup")
def test_fetch_reuses_serial_number_for_unchanged_watermark(
    runner: click.testing.CliRunner,
    feature_set_with_geometry: arcgis.features.FeatureSet,
    geo_package_store: GeoPackageStore,
    fetch_stubs: FetchStubs,
) -> None:
    watermark = "lastEdit=1"
    fetch_stubs.feature_layers(
        lambda url, gis: FeatureLayerStub(url, gis, feature_set_with_geometry),
    )
    fetch_stubs.feeds(
        FeedStub(
            name=SAMPLE_FEED_NAME,
            url=SAMPLE_FEED_URL,
            watermark=watermark,
        ),
    )
    assert invoke_fetch(runner).exit_code == 0
    assert invoke_fetch(runner).exit_code == 0
    assert geo_package_store.has(
        snapshot_path(serial_number=0, watermark=watermark),
    )
    assert not geo_package_store.has(
        snapshot_path(serial_number=1, watermark=watermark),
    )


@pytest.mark.usefixtures("fetch_setup")
def test_fetch_fails_fast_when_watermark_cannot_be_observed(
    runner: click.testing.CliRunner,
    geo_package_store: GeoPackageStore,
    fetch_stubs: FetchStubs,
) -> None:
    fetch_stubs.feeds(
        FeedStub(name=SAMPLE_FEED_NAME, url=SAMPLE_FEED_URL, watermark=None),
    )
    result = invoke_fetch(runner)
    assert result.exit_code == 1
    assert (
        f"Failed to fetch {SAMPLE_FEED_NAME}: no watermark could be observed"
        in result.output
    )
    assert not geo_package_store.has(snapshot_path())


@pytest.mark.usefixtures("fetch_setup")
def test_fetch_observes_watermark_before_downloading(
    runner: click.testing.CliRunner,
    feature_set_with_geometry: arcgis.features.FeatureSet,
    fetch_stubs: FetchStubs,
) -> None:
    events: list[str] = []
    feed = FeedStub(
        name=SAMPLE_FEED_NAME,
        url=SAMPLE_FEED_URL,
        watermark=SAMPLE_WATERMARK,
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
    assert events == ["watermark", "download"]


@pytest.mark.usefixtures("fetch_setup")
def test_fetch_skips_download_when_watermark_already_present(
    runner: click.testing.CliRunner,
    feature_set_with_geometry: arcgis.features.FeatureSet,
    fetch_stubs: FetchStubs,
) -> None:
    events: list[str] = []
    feed = FeedStub(
        name=SAMPLE_FEED_NAME,
        url=SAMPLE_FEED_URL,
        watermark=SAMPLE_WATERMARK,
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
    assert events == ["watermark", "download"]
    events.clear()
    # The second fetch sees the same watermark in the REST call and skips.
    with structlog.testing.capture_logs() as captured:
        result = invoke_fetch(runner)
    assert result.exit_code == 0
    assert events == ["watermark"]
    (skip_event,) = [
        event
        for event in captured
        if event["event"] == "Skipping fetch; data already present"
    ]
    assert skip_event["feed"] == SAMPLE_FEED_NAME
    assert skip_event["watermark"] == SAMPLE_WATERMARK
    assert skip_event["path"] == snapshot_path()


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
        watermark=SAMPLE_WATERMARK,
    )
    working = FeedStub(
        name="Working_0",
        url="https://example.test/working",
        watermark=SAMPLE_WATERMARK,
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


def test_index_fire_sources_defaults_to_current_year_directory(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
    current_year: typing.Iterator[None],
) -> None:
    indexed: list[pathlib.Path] = []
    monkeypatch.setattr(
        peri_scribe.fire_index,
        "index_fire_sources",
        indexed.append,
    )
    result = runner.invoke(peri_scribe.main.cli, ["index-fire-sources"])
    assert result.exit_code == 0
    assert indexed == [BASE_DIRECTORY / "data" / "2026"]


def test_index_fire_sources_help_names_current_year_default(
    runner: click.testing.CliRunner,
) -> None:
    result = runner.invoke(
        peri_scribe.main.cli,
        ["index-fire-sources", "--help"],
    )
    assert result.exit_code == 0
    assert (
        f"{peri_scribe.output.DATA_DIRECTORY}/{datetime.date.today().year}"
    ) in result.output
    assert "data/<current year>" not in result.output


def test_index_fire_sources_rejects_missing_directory(
    runner: click.testing.CliRunner,
) -> None:
    result = runner.invoke(
        peri_scribe.main.cli,
        ["index-fire-sources", "no-such-directory"],
    )
    assert result.exit_code == CLICK_USAGE_ERROR_EXIT_CODE
    assert "does not exist" in result.output


def test_index_fire_sources_builds_index(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
) -> None:
    monkeypatch.setattr(
        peri_scribe.output,
        "configure_logging",
        lambda log_level: log_level,
    )
    indexed: list[pathlib.Path] = []
    monkeypatch.setattr(
        peri_scribe.fire_index,
        "index_fire_sources",
        indexed.append,
    )
    result = runner.invoke(
        peri_scribe.main.cli,
        ["index-fire-sources", "data/2026"],
    )
    assert result.exit_code == 0
    assert indexed == [pathlib.Path("data/2026")]


def test_ensure_administrative_boundaries_calls_module(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
) -> None:
    called: list[pathlib.Path | None] = []

    def ensure_administrative_boundaries(
        base_directory: pathlib.Path | None = None,
    ) -> pathlib.Path:
        called.append(base_directory)
        return pathlib.Path("/boundaries.gpkg")

    monkeypatch.setattr(
        peri_scribe.administrative_boundaries,
        "ensure_administrative_boundaries",
        ensure_administrative_boundaries,
    )
    result = runner.invoke(
        peri_scribe.main.cli,
        ["ensure-admin-boundaries"],
    )
    assert result.exit_code == 0
    assert called == [None]


def test_ensure_administrative_boundaries_propagates_error(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
) -> None:
    def fail() -> typing.Never:
        message = "boom"
        raise peri_scribe.exceptions.AdministrativeBoundariesError(message)

    monkeypatch.setattr(
        peri_scribe.administrative_boundaries,
        "ensure_administrative_boundaries",
        fail,
    )
    result = runner.invoke(
        peri_scribe.main.cli,
        ["ensure-admin-boundaries"],
    )
    assert result.exit_code == 1
    assert isinstance(
        result.exception,
        peri_scribe.exceptions.AdministrativeBoundariesError,
    )


def test_cli_help_lists_ensure_administrative_boundaries(
    runner: click.testing.CliRunner,
) -> None:
    result = runner.invoke(peri_scribe.main.cli, ["--help"])
    assert result.exit_code == 0
    assert "ensure-admin-boundaries" in result.output
