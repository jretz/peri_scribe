"""CLI and integration tests for peri_scribe.main."""

import dataclasses
import pathlib
import typing
from typing import TYPE_CHECKING

import arcgis.features
import geopandas
import pandas as pd
import pyproj
import pytest
import structlog

import peri_scribe.exceptions
import peri_scribe.feed_types
import peri_scribe.geo_data
import peri_scribe.main
import peri_scribe.models
import peri_scribe.operations
import peri_scribe.output
import peri_scribe.retry
from tests.conftest import (
    CLICK_USAGE_ERROR_EXIT_CODE,
    SAMPLE_FEED_NAME,
    WGS84_WKID,
    sample_feed_config,
)


if TYPE_CHECKING:
    import click.testing


# Error messages matching the ArcGIS REST API 429 rate-limit response format.
RATE_LIMIT_RETRY_AFTER_SECONDS = 60
RATE_LIMIT_ERROR_BODY = (
    "{'error': {'code': 429, 'message': 'Unable to perform query. "
    "Too many requests.', 'details': ['API calls quota exceeded "
    "(120975 request units)! maximum allowed request units (115200) "
    f"per Minute. Retry after {RATE_LIMIT_RETRY_AFTER_SECONDS} sec.']}}"
)
LOOSE_429_ERROR_BODY = "{'error': {'code': 429, 'message': 'Too many requests.'}}"


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

    def query(self) -> arcgis.features.FeatureSet:
        if self.query_error is not None:
            raise self.query_error
        return self.feature_set


@dataclasses.dataclass(frozen=True, kw_only=True)
class WatermarkFeedStub:
    """Minimal feed stand-in with a fixed current watermark."""

    name: str
    url: str
    watermark: str

    @property
    def current_watermark(self) -> str | None:
        return self.watermark


@pytest.fixture
def fetch_setup(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
    tmp_path: pathlib.Path,
) -> None:
    """Point the fetch command's ArcGIS boundary at stubs writing into tmp_path."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        peri_scribe.output,
        "configure_logging",
        lambda log_level: log_level,
    )
    monkeypatch.setattr(
        peri_scribe.models,
        "FEEDS",
        peri_scribe.models.build_feeds([sample_feed_config()]),
    )
    monkeypatch.setattr(peri_scribe.operations.arcgis.gis, "GIS", object)


@pytest.fixture
def list_fires_setup(monkeypatch: pytest.MonkeyPatch) -> None:
    """Silence log configuration so list-fires logs can be captured."""
    monkeypatch.setattr(
        peri_scribe.output,
        "configure_logging",
        lambda log_level: log_level,
    )


def test_list_fires_requires_at_least_one_geo_package(
    runner: click.testing.CliRunner,
) -> None:
    result = runner.invoke(peri_scribe.main.cli, ["list-fires"])
    assert result.exit_code == CLICK_USAGE_ERROR_EXIT_CODE
    assert "Missing argument 'GEO_PACKAGE_PATHS...'" in result.output


@pytest.mark.usefixtures("list_fires_setup")
def test_list_fires_logs_fire_names_and_statuses(
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
    with structlog.testing.capture_logs() as captured:
        result = runner.invoke(
            peri_scribe.main.cli,
            ["list-fires", "fires_one.gpkg", "fires_two.gpkg"],
        )
    assert result.exit_code == 0
    assert [(event["name"], event["status"]) for event in captured] == [
        ("Park Fire", "active"),
        ("ALTA", "inactive"),
    ]


@pytest.mark.usefixtures("list_fires_setup")
def test_list_fires_propagates_unconfigured_layer_error(
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
    result = runner.invoke(peri_scribe.main.cli, ["list-fires", "fires.gpkg"])
    assert result.exit_code == 1
    assert isinstance(result.exception, peri_scribe.exceptions.UnknownLayerError)


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
    tmp_path: pathlib.Path,
) -> None:
    monkeypatch.setattr(
        peri_scribe.operations.arcgis.features,
        "FeatureLayer",
        lambda url, gis: FeatureLayerStub(url, gis, feature_set_with_geometry),
    )
    result = runner.invoke(peri_scribe.main.cli, ["fetch"])
    output_path = tmp_path / peri_scribe.models.OUTPUT_FILENAME
    assert result.exit_code == 0
    assert output_path.exists()
    written = geopandas.read_file(output_path, layer=SAMPLE_FEED_NAME)
    assert list(written["name"]) == ["a", "b"]
    assert written.crs == pyproj.CRS.from_epsg(WGS84_WKID)


@pytest.mark.usefixtures("fetch_setup")
def test_fetch_fails_fast_when_query_fails(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
    tmp_path: pathlib.Path,
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
    assert not (tmp_path / peri_scribe.models.OUTPUT_FILENAME).exists()


@pytest.mark.usefixtures("fetch_setup")
def test_fetch_fails_fast_when_feed_returns_no_features(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
    tmp_path: pathlib.Path,
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
        f"Feed {SAMPLE_FEED_NAME} returned no features; "
        f"{peri_scribe.models.OUTPUT_FILENAME} was not modified"
    ) in result.output
    assert not (tmp_path / peri_scribe.models.OUTPUT_FILENAME).exists()


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
            watermark='{"count":1,"etag":"one","mtime":"2026-08-16T07:28:00Z"}',
        ),
        WatermarkFeedStub(
            name="Two",
            url="https://example.test/two",
            watermark='{"count":2,"etag":"two","mtime":"2026-08-16T07:29:00Z"}',
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
    tmp_path: pathlib.Path,
) -> None:
    sleep_calls: list[float] = []
    monkeypatch.setattr(peri_scribe.geo_data.time, "sleep", sleep_calls.append)
    rate_limit_error = ValueError(RATE_LIMIT_ERROR_BODY)
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
    output_path = tmp_path / peri_scribe.models.OUTPUT_FILENAME
    assert result.exit_code == 0
    assert output_path.exists()
    assert sleep_calls == [60.0]
    written = geopandas.read_file(output_path, layer=SAMPLE_FEED_NAME)
    assert list(written["name"]) == ["a", "b"]


@pytest.mark.usefixtures("fetch_setup")
def test_fetch_exhausts_retries_and_exits(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
    tmp_path: pathlib.Path,
) -> None:
    sleep_calls: list[float] = []
    monkeypatch.setattr(peri_scribe.geo_data.time, "sleep", sleep_calls.append)
    rate_limit_error = ValueError(RATE_LIMIT_ERROR_BODY)
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
        f"Failed to fetch {SAMPLE_FEED_NAME}: {RATE_LIMIT_ERROR_BODY}" in result.output
    )
    assert sleep_calls == [60.0] * max_retries
    assert not (tmp_path / peri_scribe.models.OUTPUT_FILENAME).exists()
