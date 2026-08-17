"""CLI and integration tests for peri_scribe.main."""

import dataclasses
import datetime
import http
import pathlib
import time
import typing
from typing import TYPE_CHECKING

import arcgis.features
import pandas as pd
import pyproj
import pytest
import structlog
import time_machine

import peri_scribe.exceptions
import peri_scribe.feed_types
import peri_scribe.main
import peri_scribe.models
import peri_scribe.operations
import peri_scribe.output
import peri_scribe.retry
from tests.conftest import (
    CLICK_USAGE_ERROR_EXIT_CODE,
    SAMPLE_FEED_NAME,
    SAMPLE_FEED_URL,
    WGS84_WKID,
    GeoPackageStore,
)


if TYPE_CHECKING:
    import click.testing


# Error messages matching the ArcGIS REST API 429 rate-limit response format.
RATE_LIMIT_RETRY_AFTER_SECONDS = 60
RATE_LIMIT_ERROR_PAYLOAD = {
    "error": {
        "code": http.HTTPStatus.TOO_MANY_REQUESTS,
        "message": "Unable to perform query. Too many requests.",
        "details": [
            (
                "API calls quota exceeded (120975 request units)! maximum allowed "
                "request units (115200) per Minute. "
                f"Retry after {RATE_LIMIT_RETRY_AFTER_SECONDS} sec."
            ),
        ],
    },
}
LOOSE_429_ERROR_PAYLOAD = {
    "error": {
        "code": http.HTTPStatus.TOO_MANY_REQUESTS,
        "message": "Too many requests.",
    },
}

SAMPLE_WATERMARK = "lastEdit=2"

# The base directory fetch resolves from ``pathlib.Path.cwd()``, which is mocked to
# this value so snapshots never touch the real filesystem.
BASE_DIRECTORY = pathlib.Path("/fetch")


class MultiQueryLayerStub:
    """FeatureLayer stand-in that returns/raises successive results per call."""

    def __init__(
        self,
        url: str,
        gis: object,
        query_outcomes: list[arcgis.features.FeatureSet | Exception],
    ) -> None:
        self.url = url
        self.gis = gis
        self.query_outcomes = list(query_outcomes)
        self.call_count = 0
        self.layer_properties: dict[str, object] = {
            "spatialReference": {"wkid": WGS84_WKID},
        }

    @property
    def properties(self) -> dict[str, object]:
        return self.layer_properties

    def query(self) -> arcgis.features.FeatureSet:
        outcome = self.query_outcomes[self.call_count]
        self.call_count += 1
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FeatureLayerStub:
    """Minimal stand-in for an ArcGIS FeatureLayer with a fixed query result."""

    def __init__(
        self,
        url: str,
        gis: object,
        feature_set: arcgis.features.FeatureSet,
        query_error: Exception | None = None,
    ) -> None:
        self.url = url
        self.gis = gis
        self.feature_set = feature_set
        self.query_error = query_error
        self.layer_properties: dict[str, object] = {
            "spatialReference": {"wkid": WGS84_WKID},
        }

    @property
    def properties(self) -> dict[str, object]:
        return self.layer_properties

    def query(
        self,
        **parameters: object,
    ) -> arcgis.features.FeatureSet | dict[str, object]:
        if self.query_error is not None:
            raise self.query_error
        if parameters.get("return_ids_only"):
            return {"objectIdFieldName": "OBJECTID", "objectIds": [1, 2]}
        return self.feature_set


class DeltaFeatureLayerStub:
    """FeatureLayer stand-in serving a full set, then an incremental delta."""

    def __init__(
        self,
        url: str,
        gis: object,
        full: arcgis.features.FeatureSet,
        delta: arcgis.features.FeatureSet,
    ) -> None:
        self.url = url
        self.gis = gis
        self.full = full
        self.delta = delta
        self.layer_properties: dict[str, object] = {
            "spatialReference": {"wkid": WGS84_WKID},
        }

    @property
    def properties(self) -> dict[str, object]:
        return self.layer_properties

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
class WatermarkFeedStub:
    """Minimal feed stand-in with a fixed current watermark."""

    name: str
    url: str
    watermark: str
    modified_column: str = "ModifiedOnDateTime_dt"

    @property
    def current_watermark(self) -> str | None:
        return self.watermark


@dataclasses.dataclass(frozen=True, kw_only=True)
class FetchFeedStub:
    """Feed stand-in with a fixed watermark for fetch command tests."""

    name: str
    url: str
    watermark: str | None
    modified_column: str = "ModifiedOnDateTime_dt"

    @property
    def current_watermark(self) -> str | None:
        return self.watermark


class RecordingFeedStub:
    """Feed stand-in that records when its watermark is observed."""

    def __init__(
        self,
        name: str,
        url: str,
        watermark: str,
        events: list[str],
    ) -> None:
        self.name = name
        self.url = url
        self.watermark = watermark
        self.modified_column = "ModifiedOnDateTime_dt"
        self.events = events

    @property
    def current_watermark(self) -> str | None:
        self.events.append("watermark")
        return self.watermark


class RecordingFeatureLayerStub:
    """FeatureLayer stand-in that records when its data is downloaded."""

    def __init__(
        self,
        url: str,
        gis: object,
        feature_set: arcgis.features.FeatureSet,
        events: list[str],
    ) -> None:
        self.url = url
        self.gis = gis
        self.feature_set = feature_set
        self.events = events
        self.layer_properties: dict[str, object] = {
            "spatialReference": {"wkid": WGS84_WKID},
        }

    @property
    def properties(self) -> dict[str, object]:
        return self.layer_properties

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
            FetchFeedStub(
                name=SAMPLE_FEED_NAME,
                url=SAMPLE_FEED_URL,
                watermark=SAMPLE_WATERMARK,
            ),
        ],
    )
    monkeypatch.setattr(peri_scribe.operations.arcgis.gis, "GIS", object)
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
    return peri_scribe.operations.source_geopackage_path(
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


def test_list_fires_requires_directory(
    runner: click.testing.CliRunner,
) -> None:
    result = runner.invoke(peri_scribe.main.cli, ["list-fires"])
    assert result.exit_code == CLICK_USAGE_ERROR_EXIT_CODE
    assert "Missing argument 'DIRECTORY'." in result.output


@pytest.mark.usefixtures("list_fires_setup")
def test_list_fires_logs_fire_names_and_statuses(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
    configured_feeds: list[peri_scribe.feed_types.Feed],
    stub_geo_package: typing.Callable[[pd.DataFrame, dict[str, pd.DataFrame]], None],
) -> None:
    stub_geo_package(
        pd.DataFrame({"name": ["Fires_One_0"], "geometry_type": ["Polygon"]}),
        {
            "Fires_One_0": pd.DataFrame({
                "incident_name": ["Park Fire", "ALTA"],
                "displayStatus": ["Active", "Inactive"],
            }),
        },
    )
    directory = pathlib.Path("/data")
    snapshots = [
        directory / "sources" / "Fires_One_0" / "000000,lastEdit=one.gpkg",
        directory / "sources" / "Fires_One_0" / "000001,lastEdit=two.gpkg",
    ]
    monkeypatch.setattr(
        peri_scribe.operations,
        "geo_package_files",
        lambda _directory: snapshots,
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
def test_list_fires_propagates_unconfigured_layer_error(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
    configured_feeds: list[peri_scribe.feed_types.Feed],
    stub_geo_package: typing.Callable[[pd.DataFrame, dict[str, pd.DataFrame]], None],
) -> None:
    stub_geo_package(
        pd.DataFrame({"name": ["Mystery_Layer_0"], "geometry_type": ["Polygon"]}),
        {
            "Mystery_Layer_0": pd.DataFrame({
                "incident_name": ["Park Fire"],
                "displayStatus": ["Active"],
            }),
        },
    )
    monkeypatch.setattr(
        peri_scribe.operations,
        "geo_package_files",
        lambda _directory: [pathlib.Path("fires.gpkg")],
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
    result = runner.invoke(
        peri_scribe.main.cli,
        ["--log-level", "DEBUG", "feed-config"],
    )
    assert result.exit_code == 0
    assert configured_levels == ["debug"]


@pytest.mark.usefixtures("fetch_setup")
def test_fetch_writes_geo_package(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
    feature_set_with_geometry: arcgis.features.FeatureSet,
    geo_package_store: GeoPackageStore,
) -> None:
    monkeypatch.setattr(
        peri_scribe.operations.arcgis.features,
        "FeatureLayer",
        lambda url, gis: FeatureLayerStub(url, gis, feature_set_with_geometry),
    )
    result = runner.invoke(peri_scribe.main.cli, ["fetch"])
    output_path = snapshot_path()
    assert result.exit_code == 0
    assert geo_package_store.has(output_path)
    written = geo_package_store.layer(output_path, SAMPLE_FEED_NAME)
    assert list(written["name"]) == ["a", "b"]
    assert written.crs == pyproj.CRS.from_epsg(WGS84_WKID)


@pytest.mark.usefixtures("fetch_setup")
def test_fetch_fails_fast_when_query_fails(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
    geo_package_store: GeoPackageStore,
) -> None:
    monkeypatch.setattr(
        peri_scribe.operations.arcgis.features,
        "FeatureLayer",
        lambda url, gis: FeatureLayerStub(
            url,
            gis,
            arcgis.features.FeatureSet([]),
            query_error=RuntimeError("boom"),
        ),
    )
    result = runner.invoke(peri_scribe.main.cli, ["fetch"])
    assert result.exit_code == 1
    assert f"Failed to fetch {SAMPLE_FEED_NAME}: boom" in result.output
    assert not geo_package_store.has(snapshot_path())


@pytest.mark.usefixtures("fetch_setup")
def test_fetch_fails_fast_when_feed_returns_no_features(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
    geo_package_store: GeoPackageStore,
) -> None:
    monkeypatch.setattr(
        peri_scribe.operations.arcgis.features,
        "FeatureLayer",
        lambda url, gis: FeatureLayerStub(
            url,
            gis,
            arcgis.features.FeatureSet([]),
        ),
    )
    result = runner.invoke(peri_scribe.main.cli, ["fetch"])
    assert result.exit_code == 1
    assert (
        f"Failed to fetch {SAMPLE_FEED_NAME}: "
        f"Feed {SAMPLE_FEED_NAME} returned no features; no output was written"
    ) in result.output
    assert not geo_package_store.has(snapshot_path())


def test_feed_config_logs_each_configured_feed(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
) -> None:
    monkeypatch.setattr(
        peri_scribe.output,
        "configure_logging",
        lambda log_level: log_level,
    )
    with structlog.testing.capture_logs() as captured:
        result = runner.invoke(peri_scribe.main.cli, ["feed-config"])
    assert result.exit_code == 0
    assert len(captured) == len(peri_scribe.models.FEEDS)
    for index, (event, feed) in enumerate(
        zip(captured, peri_scribe.models.FEEDS, strict=True),
    ):
        assert event["event"] == f"Feed {index + 1}"
        assert event["name"] == feed.name
        assert event["url"] == feed.url


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
        WatermarkFeedStub(
            name="One",
            url="https://example.test/one",
            watermark="lastEdit=1",
        ),
        WatermarkFeedStub(
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
) -> None:
    sleep_calls: list[float] = []
    monkeypatch.setattr(time, "sleep", sleep_calls.append)
    rate_limit_error = ValueError(RATE_LIMIT_ERROR_PAYLOAD)
    outcomes: list[arcgis.features.FeatureSet | Exception] = [
        rate_limit_error,
        feature_set_with_geometry,
    ]
    monkeypatch.setattr(
        peri_scribe.operations.arcgis.features,
        "FeatureLayer",
        lambda url, gis: MultiQueryLayerStub(url, gis, outcomes),
    )
    result = runner.invoke(peri_scribe.main.cli, ["fetch"])
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
) -> None:
    sleep_calls: list[float] = []
    monkeypatch.setattr(time, "sleep", sleep_calls.append)
    rate_limit_error = ValueError(RATE_LIMIT_ERROR_PAYLOAD)
    max_retries = peri_scribe.retry.DEFAULT_MAX_RETRIES
    outcomes: list[arcgis.features.FeatureSet | Exception] = [rate_limit_error] * (
        max_retries + 2
    )
    monkeypatch.setattr(
        peri_scribe.operations.arcgis.features,
        "FeatureLayer",
        lambda url, gis: MultiQueryLayerStub(url, gis, outcomes),
    )
    result = runner.invoke(peri_scribe.main.cli, ["fetch"])
    assert result.exit_code == 1
    assert (
        f"Failed to fetch {SAMPLE_FEED_NAME}: {RATE_LIMIT_ERROR_PAYLOAD}"
        in result.output
    )
    assert sleep_calls == [60.0] * max_retries
    assert not geo_package_store.has(snapshot_path())


@pytest.mark.usefixtures("fetch_setup")
def test_fetch_writes_one_file_per_source_named_by_watermark(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
    feature_set_with_geometry: arcgis.features.FeatureSet,
    geo_package_store: GeoPackageStore,
) -> None:
    first_watermark = "lastEdit=1"
    second_watermark = "lastEdit=2"
    first = FetchFeedStub(
        name="First_Source_0",
        url="https://example.test/first",
        watermark=first_watermark,
    )
    second = FetchFeedStub(
        name="Second_Source_0",
        url="https://example.test/second",
        watermark=second_watermark,
    )
    monkeypatch.setattr(peri_scribe.models, "FEEDS", [first, second])
    monkeypatch.setattr(
        peri_scribe.operations.arcgis.features,
        "FeatureLayer",
        lambda url, gis: FeatureLayerStub(url, gis, feature_set_with_geometry),
    )
    result = runner.invoke(peri_scribe.main.cli, ["fetch"])
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
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
    geo_package_store: GeoPackageStore,
) -> None:
    first_watermark = "lastEdit=1"
    second_watermark = "lastEdit=2"
    full = arcgis.features.FeatureSet([
        arcgis.features.Feature(
            geometry={"x": 1.0, "y": 2.0, "spatialReference": {"wkid": WGS84_WKID}},
            attributes={"OBJECTID": 1, "name": "a"},
        ),
        arcgis.features.Feature(
            geometry={"x": 3.0, "y": 4.0, "spatialReference": {"wkid": WGS84_WKID}},
            attributes={"OBJECTID": 2, "name": "b"},
        ),
    ])
    delta = arcgis.features.FeatureSet([
        arcgis.features.Feature(
            geometry={"x": 5.0, "y": 6.0, "spatialReference": {"wkid": WGS84_WKID}},
            attributes={"OBJECTID": 3, "name": "c"},
        ),
    ])
    monkeypatch.setattr(
        peri_scribe.operations.arcgis.features,
        "FeatureLayer",
        lambda url, gis: DeltaFeatureLayerStub(url, gis, full, delta),
    )
    monkeypatch.setattr(
        peri_scribe.models,
        "FEEDS",
        [
            FetchFeedStub(
                name=SAMPLE_FEED_NAME,
                url=SAMPLE_FEED_URL,
                watermark=first_watermark,
            ),
        ],
    )
    assert runner.invoke(peri_scribe.main.cli, ["fetch"]).exit_code == 0
    monkeypatch.setattr(
        peri_scribe.models,
        "FEEDS",
        [
            FetchFeedStub(
                name=SAMPLE_FEED_NAME,
                url=SAMPLE_FEED_URL,
                watermark=second_watermark,
            ),
        ],
    )
    assert runner.invoke(peri_scribe.main.cli, ["fetch"]).exit_code == 0
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
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
    geo_package_store: GeoPackageStore,
) -> None:
    first_watermark = "lastEdit=1"
    second_watermark = "lastEdit=2"
    full = arcgis.features.FeatureSet([
        arcgis.features.Feature(
            geometry={"x": 1.0, "y": 2.0, "spatialReference": {"wkid": WGS84_WKID}},
            attributes={"OBJECTID": 1, "name": "a"},
        ),
        arcgis.features.Feature(
            geometry={"x": 3.0, "y": 4.0, "spatialReference": {"wkid": WGS84_WKID}},
            attributes={"OBJECTID": 2, "name": "b"},
        ),
    ])
    monkeypatch.setattr(
        peri_scribe.operations.arcgis.features,
        "FeatureLayer",
        lambda url, gis: DeltaFeatureLayerStub(
            url,
            gis,
            full,
            arcgis.features.FeatureSet([]),
        ),
    )
    monkeypatch.setattr(
        peri_scribe.models,
        "FEEDS",
        [
            FetchFeedStub(
                name=SAMPLE_FEED_NAME,
                url=SAMPLE_FEED_URL,
                watermark=first_watermark,
            ),
        ],
    )
    assert runner.invoke(peri_scribe.main.cli, ["fetch"]).exit_code == 0
    monkeypatch.setattr(
        peri_scribe.models,
        "FEEDS",
        [
            FetchFeedStub(
                name=SAMPLE_FEED_NAME,
                url=SAMPLE_FEED_URL,
                watermark=second_watermark,
            ),
        ],
    )
    assert runner.invoke(peri_scribe.main.cli, ["fetch"]).exit_code == 0
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
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
    feature_set_with_geometry: arcgis.features.FeatureSet,
    geo_package_store: GeoPackageStore,
) -> None:
    watermark = "lastEdit=1"
    monkeypatch.setattr(
        peri_scribe.operations.arcgis.features,
        "FeatureLayer",
        lambda url, gis: FeatureLayerStub(url, gis, feature_set_with_geometry),
    )
    monkeypatch.setattr(
        peri_scribe.models,
        "FEEDS",
        [
            FetchFeedStub(
                name=SAMPLE_FEED_NAME,
                url=SAMPLE_FEED_URL,
                watermark=watermark,
            ),
        ],
    )
    assert runner.invoke(peri_scribe.main.cli, ["fetch"]).exit_code == 0
    assert runner.invoke(peri_scribe.main.cli, ["fetch"]).exit_code == 0
    assert geo_package_store.has(
        snapshot_path(serial_number=0, watermark=watermark),
    )
    assert not geo_package_store.has(
        snapshot_path(serial_number=1, watermark=watermark),
    )


@pytest.mark.usefixtures("fetch_setup")
def test_fetch_fails_fast_when_watermark_cannot_be_observed(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
    geo_package_store: GeoPackageStore,
) -> None:
    monkeypatch.setattr(
        peri_scribe.models,
        "FEEDS",
        [FetchFeedStub(name=SAMPLE_FEED_NAME, url=SAMPLE_FEED_URL, watermark=None)],
    )
    result = runner.invoke(peri_scribe.main.cli, ["fetch"])
    assert result.exit_code == 1
    assert (
        f"Failed to fetch {SAMPLE_FEED_NAME}: no watermark could be observed"
        in result.output
    )
    assert not geo_package_store.has(snapshot_path())


@pytest.mark.usefixtures("fetch_setup")
def test_fetch_observes_watermark_before_downloading(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
    feature_set_with_geometry: arcgis.features.FeatureSet,
) -> None:
    events: list[str] = []
    feed = RecordingFeedStub(
        name=SAMPLE_FEED_NAME,
        url=SAMPLE_FEED_URL,
        watermark=SAMPLE_WATERMARK,
        events=events,
    )
    monkeypatch.setattr(peri_scribe.models, "FEEDS", [feed])
    monkeypatch.setattr(
        peri_scribe.operations.arcgis.features,
        "FeatureLayer",
        lambda url, gis: RecordingFeatureLayerStub(
            url,
            gis,
            feature_set_with_geometry,
            events,
        ),
    )
    result = runner.invoke(peri_scribe.main.cli, ["fetch"])
    assert result.exit_code == 0
    assert events == ["watermark", "download"]


@pytest.mark.usefixtures("fetch_setup")
def test_fetch_skips_download_when_watermark_already_present(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
    feature_set_with_geometry: arcgis.features.FeatureSet,
) -> None:
    events: list[str] = []
    feed = RecordingFeedStub(
        name=SAMPLE_FEED_NAME,
        url=SAMPLE_FEED_URL,
        watermark=SAMPLE_WATERMARK,
        events=events,
    )
    monkeypatch.setattr(peri_scribe.models, "FEEDS", [feed])
    monkeypatch.setattr(
        peri_scribe.operations.arcgis.features,
        "FeatureLayer",
        lambda url, gis: RecordingFeatureLayerStub(
            url,
            gis,
            feature_set_with_geometry,
            events,
        ),
    )
    # The first fetch downloads and writes the snapshot.
    assert runner.invoke(peri_scribe.main.cli, ["fetch"]).exit_code == 0
    assert events == ["watermark", "download"]
    events.clear()
    # The second fetch sees the same watermark in the REST call and skips.
    with structlog.testing.capture_logs() as captured:
        result = runner.invoke(peri_scribe.main.cli, ["fetch"])
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
