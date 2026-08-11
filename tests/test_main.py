"""CLI and integration tests for peri_scribe.main."""

import pathlib
from typing import TYPE_CHECKING

import arcgis.features
import geopandas
import pyproj
import pytest
import structlog

import peri_scribe.geo_data
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
        self._url = url
        self._gis = gis
        self._query_outcomes = list(query_outcomes)
        self._call_count = 0
        self._properties: dict[str, object] = {
            "spatialReference": {"wkid": WGS84_WKID},
        }

    @property
    def properties(self) -> dict[str, object]:
        return self._properties

    def query(self) -> arcgis.features.FeatureSet:
        outcome = self._query_outcomes[self._call_count]
        self._call_count += 1
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
        self._url = url
        self._gis = gis
        self._feature_set = feature_set
        self._query_error = query_error
        self._properties: dict[str, object] = {
            "spatialReference": {"wkid": WGS84_WKID},
        }

    @property
    def properties(self) -> dict[str, object]:
        return self._properties

    def query(self) -> arcgis.features.FeatureSet:
        if self._query_error is not None:
            raise self._query_error
        return self._feature_set


@pytest.fixture
def _fetch_setup(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
    tmp_path: pathlib.Path,
) -> None:
    """Point the fetch command's ArcGIS boundary at stubs writing into tmp_path."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        peri_scribe.output,
        "configure_logging",
        lambda _log_level: None,
    )
    monkeypatch.setattr(
        peri_scribe.models,
        "FEEDS",
        [peri_scribe.models.ArcGISFeed(url=SAMPLE_FEED_URL)],
    )
    monkeypatch.setattr(peri_scribe.operations.arcgis.gis, "GIS", object)


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


@pytest.mark.usefixtures("_fetch_setup")
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


@pytest.mark.usefixtures("_fetch_setup")
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


@pytest.mark.usefixtures("_fetch_setup")
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
        lambda _log_level: None,
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


@pytest.mark.usefixtures("_fetch_setup")
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


@pytest.mark.usefixtures("_fetch_setup")
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
