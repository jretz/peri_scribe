"""Tests for peri_scribe.fetching."""

from __future__ import annotations

import dataclasses
import datetime
import pathlib
import time
import typing

import arcgis.features
import geopandas
import pandas as pd
import pyproj
import pytest
import shapely.geometry
import structlog

import peri_scribe.changes
import peri_scribe.exceptions
import peri_scribe.feed_types
import peri_scribe.feeds
import peri_scribe.fetching
import peri_scribe.fire_index
import peri_scribe.geo_data
import peri_scribe.models
import peri_scribe.output
import peri_scribe.retry
import peri_scribe.snapshots
from tests.conftest import (
    RATE_LIMIT_ERROR_PAYLOAD,
    SAMPLE_FEED_NAME,
    SAMPLE_FEED_URL,
    snapshot_path,
)
from tests.factories import (
    WGS84_WKID,
    FeatureLayerStub,
    FeatureLayerStubBase,
    GeoPackageStore,
    change_feed,
    wgs84_feature_set,
)
from tests.main_stubs import BASE_DIRECTORY, SAMPLE_LAST_EDIT_TIMESTAMP


def test_fetch_feed_dataframe_raises_without_change_columns() -> None:
    feed = change_feed(change_columns=())
    with pytest.raises(ValueError, match="no change columns"):
        peri_scribe.fetching.fetch_feed_dataframe(
            feed,
            object(),  # ty: ignore
            [peri_scribe.snapshots.SourceFile(serial_number=0, last_edit_timestamp=0)],
            pathlib.Path("/sources"),
        )


def test_fetch_feed_dataframe_returns_none_without_changed_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    feed = change_feed()
    monkeypatch.setattr(
        peri_scribe.changes,
        "existing_features",
        lambda _directory, _feed: None,
    )
    monkeypatch.setattr(
        peri_scribe.geo_data,
        "query_object_ids_with_retry",
        lambda *_arguments, **_keywords: [],
    )
    result = peri_scribe.fetching.fetch_feed_dataframe(
        feed,
        object(),  # ty: ignore
        [peri_scribe.snapshots.SourceFile(serial_number=0, last_edit_timestamp=0)],
        pathlib.Path("/sources"),
    )
    assert result is None


def test_fetch_feed_dataframe_returns_none_when_dedupe_removes_all(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    feed = change_feed()
    monkeypatch.setattr(
        peri_scribe.changes,
        "existing_features",
        lambda _directory, _feed: None,
    )
    monkeypatch.setattr(
        peri_scribe.geo_data,
        "query_object_ids_with_retry",
        lambda *_arguments, **_keywords: [1],
    )
    monkeypatch.setattr(
        peri_scribe.geo_data,
        "query_with_retry",
        lambda *_arguments, **_keywords: "feature_set",
    )
    empty = geopandas.GeoDataFrame(
        {"OBJECTID": pd.Series([], dtype="int64"), "name": []},
        geometry=[],
        crs=pyproj.CRS.from_epsg(4326),
    )
    monkeypatch.setattr(
        peri_scribe.geo_data,
        "dataframe_for_layer",
        lambda *_arguments, **_keywords: empty,
    )
    result = peri_scribe.fetching.fetch_feed_dataframe(
        feed,
        object(),  # ty: ignore
        [peri_scribe.snapshots.SourceFile(serial_number=0, last_edit_timestamp=0)],
        pathlib.Path("/sources"),
    )
    assert result is None


def test_fetch_feed_dataframe_queries_null_modified_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    feed = change_feed()
    captured: list[str] = []
    monkeypatch.setattr(
        peri_scribe.changes,
        "existing_features",
        lambda _directory, _feed: None,
    )

    def capture_where(
        *_arguments: object,
        **_keywords: object,
    ) -> list[int]:
        captured.append(str(_keywords["where"]))
        return []

    monkeypatch.setattr(
        peri_scribe.geo_data,
        "query_object_ids_with_retry",
        capture_where,
    )
    result = peri_scribe.fetching.fetch_feed_dataframe(
        feed,
        object(),  # ty: ignore
        [peri_scribe.snapshots.SourceFile(serial_number=0, last_edit_timestamp=0)],
        pathlib.Path("/sources"),
    )
    assert result is None
    assert "IS NULL" in captured[0]
    assert captured[1] == "1=1"


def test_fetch_feed_dataframe_fetches_ids_present_but_not_stored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    feed = change_feed()
    existing = geopandas.GeoDataFrame(
        {"OBJECTID": [1, 2]},
        geometry=[shapely.geometry.Point(0.0, 0.0) for _ in (1, 2)],
        crs=pyproj.CRS.from_epsg(4326),
    )
    monkeypatch.setattr(
        peri_scribe.changes,
        "existing_features",
        lambda _directory, _feed: existing,
    )
    # First call (timestamp query) finds no changed rows; second call (full layer)
    # reports OBJECTID 3 as present in the layer but never stored.
    monkeypatch.setattr(
        peri_scribe.geo_data,
        "query_object_ids_with_retry",
        lambda *_arguments, **_keywords: [] if _keywords["where"] != "1=1" else [3],
    )
    fetched: dict[str, object] = {}
    monkeypatch.setattr(
        peri_scribe.geo_data,
        "query_with_retry",
        lambda *_arguments, **_keywords: fetched.update(_keywords) or "feature_set",
    )
    sentinel = geopandas.GeoDataFrame(
        {"OBJECTID": [3], "name": ["c"]},
        geometry=[shapely.geometry.Point(2.0, 2.0)],
        crs=pyproj.CRS.from_epsg(4326),
    )
    monkeypatch.setattr(
        peri_scribe.geo_data,
        "dataframe_for_layer",
        lambda *_arguments, **_keywords: sentinel,
    )
    result = peri_scribe.fetching.fetch_feed_dataframe(
        feed,
        object(),  # ty: ignore
        [peri_scribe.snapshots.SourceFile(serial_number=0, last_edit_timestamp=0)],
        pathlib.Path("/sources"),
    )
    assert fetched["parameters"] == {"object_ids": "3"}
    assert result is not None
    assert list(result["OBJECTID"]) == [3]


def test_fetch_feed_dataframe_fetches_stored_active_rows_now_inactive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    feed = change_feed()
    existing = geopandas.GeoDataFrame(
        {"OBJECTID": [1, 2, 3], "status": ["Active", "Active", "Inactive"]},
        geometry=[shapely.geometry.Point(x, 0.0) for x in (0.0, 1.0, 2.0)],
        crs=pyproj.CRS.from_epsg(4326),
    )
    monkeypatch.setattr(
        peri_scribe.changes,
        "existing_features",
        lambda _directory, _feed: existing,
    )
    wheres: list[str] = []

    def query_ids(*_arguments: object, **_keywords: object) -> list[int]:
        where = str(_keywords["where"])
        wheres.append(where)
        if where == "1=1":
            return [1, 2, 3]
        if "status IN" in where:
            return [2]
        return []

    monkeypatch.setattr(
        peri_scribe.geo_data,
        "query_object_ids_with_retry",
        query_ids,
    )
    fetched: dict[str, object] = {}
    monkeypatch.setattr(
        peri_scribe.geo_data,
        "query_with_retry",
        lambda *_arguments, **_keywords: fetched.update(_keywords) or "feature_set",
    )
    flipped = geopandas.GeoDataFrame(
        {"OBJECTID": [2], "status": ["Inactive"]},
        geometry=[shapely.geometry.Point(1.0, 0.0)],
        crs=pyproj.CRS.from_epsg(4326),
    )
    monkeypatch.setattr(
        peri_scribe.geo_data,
        "dataframe_for_layer",
        lambda *_arguments, **_keywords: flipped,
    )
    result = peri_scribe.fetching.fetch_feed_dataframe(
        feed,
        object(),  # ty: ignore
        [peri_scribe.snapshots.SourceFile(serial_number=0, last_edit_timestamp=0)],
        pathlib.Path("/sources"),
    )
    assert result is not None
    assert list(result["OBJECTID"]) == [2]
    assert fetched["parameters"] == {"object_ids": "2"}
    assert any(
        "status IN ('Inactive')" in where and "OBJECTID IN (1, 2)" in where
        for where in wheres
    )


def test_fetch_feed_dataframe_returns_none_when_flip_candidates_are_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    feed = change_feed()
    existing = geopandas.GeoDataFrame(
        {"OBJECTID": [1, 2], "status": ["Active", "Inactive"]},
        geometry=[shapely.geometry.Point(x, 0.0) for x in (0.0, 1.0)],
        crs=pyproj.CRS.from_epsg(4326),
    )
    monkeypatch.setattr(
        peri_scribe.changes,
        "existing_features",
        lambda _directory, _feed: existing,
    )
    monkeypatch.setattr(
        peri_scribe.geo_data,
        "query_object_ids_with_retry",
        lambda *_arguments, **_keywords: [1, 2] if _keywords["where"] == "1=1" else [],
    )
    result = peri_scribe.fetching.fetch_feed_dataframe(
        feed,
        object(),  # ty: ignore
        [peri_scribe.snapshots.SourceFile(serial_number=0, last_edit_timestamp=0)],
        pathlib.Path("/sources"),
    )
    assert result is None


def test_fetch_feed_dataframe_skips_flip_query_without_stored_inactive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    feed = change_feed()
    existing = geopandas.GeoDataFrame(
        {"OBJECTID": [1, 2], "status": ["Active", "Active"]},
        geometry=[shapely.geometry.Point(x, 0.0) for x in (0.0, 1.0)],
        crs=pyproj.CRS.from_epsg(4326),
    )
    monkeypatch.setattr(
        peri_scribe.changes,
        "existing_features",
        lambda _directory, _feed: existing,
    )
    wheres: list[str] = []
    monkeypatch.setattr(
        peri_scribe.geo_data,
        "query_object_ids_with_retry",
        lambda *_arguments, **_keywords: (
            wheres.append(str(_keywords["where"]))
            or ([1, 2] if _keywords["where"] == "1=1" else [])
        ),
    )
    result = peri_scribe.fetching.fetch_feed_dataframe(
        feed,
        object(),  # ty: ignore
        [peri_scribe.snapshots.SourceFile(serial_number=0, last_edit_timestamp=0)],
        pathlib.Path("/sources"),
    )
    assert result is None
    assert not any("status IN" in where for where in wheres)


def test_fetch_feed_dataframe_fetches_full_when_directory_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    feed = change_feed()
    sentinel = object()
    monkeypatch.setattr(
        peri_scribe.geo_data,
        "query_with_retry",
        lambda *_arguments, **_keywords: "feature_set",
    )
    monkeypatch.setattr(
        peri_scribe.geo_data,
        "dataframe_for_layer",
        lambda *_arguments, **_keywords: sentinel,
    )
    result = peri_scribe.fetching.fetch_feed_dataframe(
        feed,
        object(),  # ty: ignore
        [],
        pathlib.Path("/sources"),
    )
    assert result is sentinel


def test_fetch_feed_dataframe_full_fetches_whole_layer_and_dedupes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    feed = change_feed(change_columns=())
    query_keywords: list[dict[str, object]] = []
    feature_set = object()
    monkeypatch.setattr(
        peri_scribe.geo_data,
        "query_with_retry",
        lambda *_arguments, **_keywords: (
            query_keywords.append(_keywords) or feature_set
        ),
    )
    fetched = object()
    monkeypatch.setattr(
        peri_scribe.geo_data,
        "dataframe_for_layer",
        lambda *_arguments, **_keywords: fetched,
    )
    existing = object()
    monkeypatch.setattr(
        peri_scribe.changes,
        "existing_features",
        lambda _directory, _feed: existing,
    )
    dedupe_calls: list[tuple[object, object]] = []
    deduped = geopandas.GeoDataFrame(
        {"OBJECTID": pd.Series([1], dtype="int64"), "name": ["a"]},
        geometry=[shapely.geometry.Point(0.0, 0.0)],
        crs=pyproj.CRS.from_epsg(4326),
    )
    monkeypatch.setattr(
        peri_scribe.changes,
        "drop_features_already_present",
        lambda new, existing_dataframe: (
            dedupe_calls.append((new, existing_dataframe)) or deduped
        ),
    )
    result = peri_scribe.fetching.fetch_feed_dataframe(
        feed,
        object(),  # ty: ignore
        [peri_scribe.snapshots.SourceFile(serial_number=0, last_edit_timestamp=0)],
        pathlib.Path("/sources"),
        full=True,
    )
    assert result is deduped
    assert query_keywords == [{}]
    assert dedupe_calls == [(fetched, existing)]


def test_fetch_feed_dataframe_full_returns_none_when_dedupe_removes_all(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    feed = change_feed()
    monkeypatch.setattr(
        peri_scribe.geo_data,
        "query_with_retry",
        lambda *_arguments, **_keywords: "feature_set",
    )
    empty = geopandas.GeoDataFrame(
        {"OBJECTID": pd.Series([], dtype="int64"), "name": []},
        geometry=[],
        crs=pyproj.CRS.from_epsg(4326),
    )
    monkeypatch.setattr(
        peri_scribe.geo_data,
        "dataframe_for_layer",
        lambda *_arguments, **_keywords: empty,
    )
    monkeypatch.setattr(
        peri_scribe.changes,
        "existing_features",
        lambda _directory, _feed: None,
    )
    result = peri_scribe.fetching.fetch_feed_dataframe(
        feed,
        object(),  # ty: ignore
        [peri_scribe.snapshots.SourceFile(serial_number=0, last_edit_timestamp=0)],
        pathlib.Path("/sources"),
        full=True,
    )
    assert result is None


def complete_fetch_feed(index: int) -> peri_scribe.feed_types.ArcGISFeed:
    """Return a feed with a name unique to *index*.

    Args:
        index: The number that distinguishes the feed's name.

    Returns:
        The feed.
    """
    return peri_scribe.feed_types.ArcGISFeed(
        url=(f"https://example.test/ArcGIS/rest/services/Fires{index}/FeatureServer/0"),
        fire_name_column="name",
        status_column="status",
    )


def stub_complete_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the complete fetch's file and network boundaries at in-memory stubs.

    Args:
        monkeypatch: The monkeypatch fixture.
    """
    monkeypatch.setattr(peri_scribe.fetching.arcgis.gis, "GIS", object)
    monkeypatch.setattr(
        pathlib.Path,
        "mkdir",
        lambda *_arguments, **_keywords: None,
    )
    monkeypatch.setattr(
        peri_scribe.output,
        "write_geopackage",
        lambda _path, _layers: None,
    )


def test_fetch_all_feeds_complete_writes_each_feed_in_full(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    feeds = [complete_fetch_feed(0), complete_fetch_feed(1)]
    monkeypatch.setattr(peri_scribe.feeds, "FEEDS", feeds)
    stub_complete_fetch(monkeypatch)
    written: list[tuple[pathlib.Path, list[peri_scribe.models.LayerData]]] = []
    monkeypatch.setattr(
        peri_scribe.output,
        "write_geopackage",
        lambda path, layers: written.append((path, layers)),
    )
    frames = {feed.name: object() for feed in feeds}

    def fetch_feed(
        feed: peri_scribe.feed_types.Feed,
        gis: object,
        existing_source_files: list[peri_scribe.snapshots.SourceFile],
        source_directory: pathlib.Path,
    ) -> object:
        assert existing_source_files == []
        assert source_directory == pathlib.Path(
            "/base/data/2026/validation",
        )
        return frames[feed.name]

    monkeypatch.setattr(peri_scribe.fetching, "fetch_feed", fetch_feed)
    paths = peri_scribe.fetching.fetch_all_feeds_complete(
        pathlib.Path("/base"),
        year=2026,
    )
    assert paths == (
        pathlib.Path("/base/data/2026/validation/Fires0_0.gpkg"),
        pathlib.Path("/base/data/2026/validation/Fires1_0.gpkg"),
    )
    assert [path for path, _layers in written] == list(paths)
    assert [
        (layer_data.name, layer_data.dataframe)
        for _path, layers in written
        for layer_data in layers
    ] == list(frames.items())


def test_fetch_all_feeds_complete_reports_failures_and_continues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    feeds = [
        complete_fetch_feed(0),
        complete_fetch_feed(1),
        complete_fetch_feed(2),
    ]
    monkeypatch.setattr(peri_scribe.feeds, "FEEDS", feeds)
    stub_complete_fetch(monkeypatch)
    written: list[pathlib.Path] = []
    monkeypatch.setattr(
        peri_scribe.output,
        "write_geopackage",
        lambda path, _layers: written.append(path),
    )

    def fetch_feed(
        feed: peri_scribe.feed_types.Feed,
        gis: object,
        existing_source_files: list[peri_scribe.snapshots.SourceFile],
        source_directory: pathlib.Path,
    ) -> object:
        if feed.name == "Fires0_0":
            message = "Failed to fetch Fires0_0: boom"
            raise peri_scribe.exceptions.FeedFetchError(message)
        if feed.name == "Fires2_0":
            return None
        return object()

    monkeypatch.setattr(peri_scribe.fetching, "fetch_feed", fetch_feed)
    with pytest.raises(SystemExit) as raised:
        peri_scribe.fetching.fetch_all_feeds_complete(
            pathlib.Path("/base"),
            year=2026,
        )
    assert str(raised.value) == (
        "Failed to fetch Fires0_0: boom\n"
        "Failed to fetch Fires2_0: fetch produced no data"
    )
    assert written == [
        pathlib.Path("/base/data/2026/validation/Fires1_0.gpkg"),
    ]


def test_fetch_all_feeds_complete_defaults_to_working_directory_and_year(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(peri_scribe.feeds, "FEEDS", [complete_fetch_feed(0)])
    stub_complete_fetch(monkeypatch)
    monkeypatch.setattr(
        pathlib.Path,
        "cwd",
        staticmethod(lambda: pathlib.Path("/fetch")),
    )
    monkeypatch.setattr(
        peri_scribe.fetching,
        "fetch_feed",
        lambda *_arguments, **_keywords: object(),
    )
    year = datetime.date.today().year
    paths = peri_scribe.fetching.fetch_all_feeds_complete()
    assert paths == (pathlib.Path(f"/fetch/data/{year}/validation/Fires0_0.gpkg"),)


@dataclasses.dataclass(frozen=True, kw_only=True)
class FeedStub:
    """Minimal feed stand-in with a fixed current last-edit timestamp."""

    name: str
    url: str
    last_edit_timestamp: int | None
    status_column: str = "status"
    change_columns: tuple[str, ...] = ("ModifiedOnDateTime_dt",)
    events: list[str] = dataclasses.field(default_factory=list)

    @property
    def current_last_edit_timestamp(self) -> int | None:
        self.events.append("timestamp")
        return self.last_edit_timestamp


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


class SequenceFeatureLayerStub(FeatureLayerStubBase):
    """FeatureLayer stand-in serving successive feature sets per query."""

    def __init__(
        self,
        url: str,
        gis: object,
        feature_sets: list[arcgis.features.FeatureSet],
        events: list[str] | None = None,
    ) -> None:
        super().__init__(url, gis)
        self.feature_sets = list(feature_sets)
        self.call_count = 0
        self.events = [] if events is None else events

    def query(
        self,
        **_parameters: object,
    ) -> arcgis.features.FeatureSet:
        self.events.append("download")
        feature_set = self.feature_sets[
            min(self.call_count, len(self.feature_sets) - 1)
        ]
        self.call_count += 1
        return feature_set


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
def fetch_all_feeds_stubs(
    monkeypatch: pytest.MonkeyPatch,
) -> typing.Callable[
    [list[FeedStub], typing.Callable[[str, object], object]],
    None,
]:
    """Install feed, GIS, and FeatureLayer stubs for fetch-all-feeds tests.

    Returns:
        A callable that installs the stubs for one test.
    """

    def install(
        feeds: list[FeedStub],
        layer_factory: typing.Callable[[str, object], object],
    ) -> None:
        monkeypatch.setattr(peri_scribe.feeds, "FEEDS", feeds)
        monkeypatch.setattr(peri_scribe.fetching.arcgis.gis, "GIS", object)
        monkeypatch.setattr(
            peri_scribe.fetching.arcgis.features,
            "FeatureLayer",
            layer_factory,
        )
        monkeypatch.setattr(
            peri_scribe.fire_index,
            "index_fire_sources",
            lambda _year_directory: None,
        )

    return install


def sample_feed_stub() -> FeedStub:
    """Return the sample feed stub for fetch-all-feeds tests.

    Returns:
        The sample feed stub.
    """
    return FeedStub(
        name=SAMPLE_FEED_NAME,
        url=SAMPLE_FEED_URL,
        last_edit_timestamp=SAMPLE_LAST_EDIT_TIMESTAMP,
    )


def test_fetch_all_feeds_writes_geo_package(
    feature_set_with_geometry: arcgis.features.FeatureSet,
    fetch_all_feeds_stubs: typing.Callable[..., None],
    geo_package_store: GeoPackageStore,
) -> None:
    fetch_all_feeds_stubs(
        [sample_feed_stub()],
        lambda url, gis: FeatureLayerStub(url, gis, feature_set_with_geometry),
    )
    result = peri_scribe.fetching.fetch_all_feeds(BASE_DIRECTORY, year=2026)
    assert result.changed is True
    output_path = snapshot_path()
    assert geo_package_store.has(output_path)
    written = geo_package_store.layer(output_path, SAMPLE_FEED_NAME)
    assert list(written["name"]) == ["a", "b"]
    assert written.crs == pyproj.CRS.from_epsg(WGS84_WKID)


def test_fetch_all_feeds_reports_query_failure(
    fetch_all_feeds_stubs: typing.Callable[..., None],
    geo_package_store: GeoPackageStore,
) -> None:
    fetch_all_feeds_stubs(
        [sample_feed_stub()],
        lambda url, gis: FeatureLayerStub(
            url,
            gis,
            arcgis.features.FeatureSet([]),
            query_error=RuntimeError("boom"),
        ),
    )
    with pytest.raises(
        SystemExit,
        match=f"Failed to fetch {SAMPLE_FEED_NAME}: boom",
    ):
        peri_scribe.fetching.fetch_all_feeds(BASE_DIRECTORY, year=2026)
    assert not geo_package_store.has(snapshot_path())


def test_fetch_all_feeds_reports_empty_layer(
    fetch_all_feeds_stubs: typing.Callable[..., None],
    geo_package_store: GeoPackageStore,
) -> None:
    fetch_all_feeds_stubs(
        [sample_feed_stub()],
        lambda url, gis: FeatureLayerStub(url, gis, arcgis.features.FeatureSet([])),
    )
    with pytest.raises(
        SystemExit,
        match=(
            f"Failed to fetch {SAMPLE_FEED_NAME}: Feed {SAMPLE_FEED_NAME} "
            "returned no features; no output was written"
        ),
    ):
        peri_scribe.fetching.fetch_all_feeds(BASE_DIRECTORY, year=2026)
    assert not geo_package_store.has(snapshot_path())


def test_fetch_all_feeds_retries_on_rate_limit(
    monkeypatch: pytest.MonkeyPatch,
    feature_set_with_geometry: arcgis.features.FeatureSet,
    fetch_all_feeds_stubs: typing.Callable[..., None],
    geo_package_store: GeoPackageStore,
) -> None:
    sleep_calls: list[float] = []
    monkeypatch.setattr(time, "sleep", sleep_calls.append)
    rate_limit_error = ValueError(RATE_LIMIT_ERROR_PAYLOAD)
    outcomes: list[arcgis.features.FeatureSet | Exception] = [
        rate_limit_error,
        feature_set_with_geometry,
    ]
    fetch_all_feeds_stubs(
        [sample_feed_stub()],
        lambda url, gis: MultiQueryLayerStub(url, gis, outcomes),
    )
    result = peri_scribe.fetching.fetch_all_feeds(BASE_DIRECTORY, year=2026)
    assert result.changed is True
    output_path = snapshot_path()
    assert geo_package_store.has(output_path)
    assert sleep_calls == [60.0]
    written = geo_package_store.layer(output_path, SAMPLE_FEED_NAME)
    assert list(written["name"]) == ["a", "b"]


def test_fetch_all_feeds_exhausts_retries(
    monkeypatch: pytest.MonkeyPatch,
    fetch_all_feeds_stubs: typing.Callable[..., None],
    geo_package_store: GeoPackageStore,
) -> None:
    sleep_calls: list[float] = []
    monkeypatch.setattr(time, "sleep", sleep_calls.append)
    rate_limit_error = ValueError(RATE_LIMIT_ERROR_PAYLOAD)
    max_retries = peri_scribe.retry.DEFAULT_MAX_RETRIES
    outcomes: list[arcgis.features.FeatureSet | Exception] = [rate_limit_error] * (
        max_retries + 2
    )
    fetch_all_feeds_stubs(
        [sample_feed_stub()],
        lambda url, gis: MultiQueryLayerStub(url, gis, outcomes),
    )
    with pytest.raises(
        SystemExit,
        match=f"Failed to fetch {SAMPLE_FEED_NAME}: ",
    ):
        peri_scribe.fetching.fetch_all_feeds(BASE_DIRECTORY, year=2026)
    assert sleep_calls == [60.0] * max_retries
    assert not geo_package_store.has(snapshot_path())


def test_fetch_all_feeds_writes_one_file_per_source(
    feature_set_with_geometry: arcgis.features.FeatureSet,
    fetch_all_feeds_stubs: typing.Callable[..., None],
    geo_package_store: GeoPackageStore,
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
    fetch_all_feeds_stubs(
        [first, second],
        lambda url, gis: FeatureLayerStub(url, gis, feature_set_with_geometry),
    )
    result = peri_scribe.fetching.fetch_all_feeds(BASE_DIRECTORY, year=2026)
    assert result.changed is True
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
    assert list(geo_package_store.layer(first_path, "First_Source_0")["name"]) == [
        "a",
        "b",
    ]
    assert list(geo_package_store.layer(second_path, "Second_Source_0")["name"]) == [
        "a",
        "b",
    ]


def test_fetch_all_feeds_increments_serial_number_for_new_timestamp(
    fetch_all_feeds_stubs: typing.Callable[..., None],
    geo_package_store: GeoPackageStore,
) -> None:
    first_last_edit_timestamp = 1
    second_last_edit_timestamp = 2
    full = wgs84_feature_set([
        (1, "a", 1.0, 2.0),
        (2, "b", 3.0, 4.0),
    ])
    delta = wgs84_feature_set([(3, "c", 5.0, 6.0)])
    fetch_all_feeds_stubs(
        [
            FeedStub(
                name=SAMPLE_FEED_NAME,
                url=SAMPLE_FEED_URL,
                last_edit_timestamp=first_last_edit_timestamp,
            ),
        ],
        lambda url, gis: DeltaFeatureLayerStub(url, gis, full, delta),
    )
    assert (
        peri_scribe.fetching.fetch_all_feeds(BASE_DIRECTORY, year=2026).changed is True
    )
    fetch_all_feeds_stubs(
        [
            FeedStub(
                name=SAMPLE_FEED_NAME,
                url=SAMPLE_FEED_URL,
                last_edit_timestamp=second_last_edit_timestamp,
            ),
        ],
        lambda url, gis: DeltaFeatureLayerStub(url, gis, full, delta),
    )
    assert (
        peri_scribe.fetching.fetch_all_feeds(BASE_DIRECTORY, year=2026).changed is True
    )
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
    assert list(geo_package_store.layer(first_path, SAMPLE_FEED_NAME)["name"]) == [
        "a",
        "b",
    ]
    assert list(geo_package_store.layer(second_path, SAMPLE_FEED_NAME)["name"]) == [
        "c",
    ]


def test_fetch_all_feeds_writes_no_new_file_when_nothing_changed(
    fetch_all_feeds_stubs: typing.Callable[..., None],
    geo_package_store: GeoPackageStore,
) -> None:
    first_last_edit_timestamp = 1
    second_last_edit_timestamp = 2
    full = wgs84_feature_set([
        (1, "a", 1.0, 2.0),
        (2, "b", 3.0, 4.0),
    ])
    fetch_all_feeds_stubs(
        [
            FeedStub(
                name=SAMPLE_FEED_NAME,
                url=SAMPLE_FEED_URL,
                last_edit_timestamp=first_last_edit_timestamp,
            ),
        ],
        lambda url, gis: DeltaFeatureLayerStub(
            url,
            gis,
            full,
            arcgis.features.FeatureSet([]),
        ),
    )
    assert (
        peri_scribe.fetching.fetch_all_feeds(BASE_DIRECTORY, year=2026).changed is True
    )
    fetch_all_feeds_stubs(
        [
            FeedStub(
                name=SAMPLE_FEED_NAME,
                url=SAMPLE_FEED_URL,
                last_edit_timestamp=second_last_edit_timestamp,
            ),
        ],
        lambda url, gis: DeltaFeatureLayerStub(
            url,
            gis,
            full,
            arcgis.features.FeatureSet([]),
        ),
    )
    second_result = peri_scribe.fetching.fetch_all_feeds(BASE_DIRECTORY, year=2026)
    assert second_result.changed is False
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


def test_fetch_all_feeds_reuses_serial_number_for_unchanged_timestamp(
    feature_set_with_geometry: arcgis.features.FeatureSet,
    fetch_all_feeds_stubs: typing.Callable[..., None],
    geo_package_store: GeoPackageStore,
) -> None:
    last_edit_timestamp = 1
    fetch_all_feeds_stubs(
        [
            FeedStub(
                name=SAMPLE_FEED_NAME,
                url=SAMPLE_FEED_URL,
                last_edit_timestamp=last_edit_timestamp,
            ),
        ],
        lambda url, gis: FeatureLayerStub(url, gis, feature_set_with_geometry),
    )
    assert (
        peri_scribe.fetching.fetch_all_feeds(BASE_DIRECTORY, year=2026).changed is True
    )
    second_result = peri_scribe.fetching.fetch_all_feeds(BASE_DIRECTORY, year=2026)
    assert second_result.changed is False
    assert geo_package_store.has(
        snapshot_path(serial_number=0, last_edit_timestamp=last_edit_timestamp),
    )
    assert not geo_package_store.has(
        snapshot_path(serial_number=1, last_edit_timestamp=last_edit_timestamp),
    )


def test_fetch_all_feeds_fails_when_last_edit_timestamp_unavailable(
    fetch_all_feeds_stubs: typing.Callable[..., None],
    geo_package_store: GeoPackageStore,
) -> None:
    fetch_all_feeds_stubs(
        [
            FeedStub(
                name=SAMPLE_FEED_NAME,
                url=SAMPLE_FEED_URL,
                last_edit_timestamp=None,
            ),
        ],
        lambda _url, _gis: object(),
    )
    with pytest.raises(
        SystemExit,
        match="no last-edit timestamp could be observed",
    ):
        peri_scribe.fetching.fetch_all_feeds(BASE_DIRECTORY, year=2026)
    assert not geo_package_store.has(snapshot_path())


def test_fetch_all_feeds_observes_timestamp_before_downloading(
    feature_set_with_geometry: arcgis.features.FeatureSet,
    fetch_all_feeds_stubs: typing.Callable[..., None],
    geo_package_store: GeoPackageStore,
) -> None:
    events: list[str] = []
    feed = FeedStub(
        name=SAMPLE_FEED_NAME,
        url=SAMPLE_FEED_URL,
        last_edit_timestamp=SAMPLE_LAST_EDIT_TIMESTAMP,
        events=events,
    )
    fetch_all_feeds_stubs(
        [feed],
        lambda url, gis: RecordingFeatureLayerStub(
            url,
            gis,
            feature_set_with_geometry,
            events,
        ),
    )
    peri_scribe.fetching.fetch_all_feeds(BASE_DIRECTORY, year=2026)
    assert events == ["timestamp", "download"]


def test_fetch_all_feeds_skips_download_when_timestamp_present(
    feature_set_with_geometry: arcgis.features.FeatureSet,
    fetch_all_feeds_stubs: typing.Callable[..., None],
    geo_package_store: GeoPackageStore,
) -> None:
    events: list[str] = []
    feed = FeedStub(
        name=SAMPLE_FEED_NAME,
        url=SAMPLE_FEED_URL,
        last_edit_timestamp=SAMPLE_LAST_EDIT_TIMESTAMP,
        events=events,
    )
    fetch_all_feeds_stubs(
        [feed],
        lambda url, gis: RecordingFeatureLayerStub(
            url,
            gis,
            feature_set_with_geometry,
            events,
        ),
    )
    # The first fetch downloads and writes the snapshot.
    assert (
        peri_scribe.fetching.fetch_all_feeds(BASE_DIRECTORY, year=2026).changed is True
    )
    assert events == ["timestamp", "download"]
    events.clear()
    # The second fetch sees the same last-edit timestamp and skips the download.
    with structlog.testing.capture_logs() as captured:
        result = peri_scribe.fetching.fetch_all_feeds(BASE_DIRECTORY, year=2026)
    assert result.changed is False
    assert events == ["timestamp"]
    (skip_event,) = [
        event
        for event in captured
        if event["event"] == "Skipping fetch; data already present"
    ]
    assert skip_event["feed"] == SAMPLE_FEED_NAME
    assert skip_event["last_edit_timestamp"] == SAMPLE_LAST_EDIT_TIMESTAMP
    assert skip_event["path"] == snapshot_path()


def test_fetch_all_feeds_full_downloads_when_timestamp_present(
    fetch_all_feeds_stubs: typing.Callable[..., None],
    geo_package_store: GeoPackageStore,
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
    layer_stub = SequenceFeatureLayerStub(
        url=SAMPLE_FEED_URL,
        gis=object(),
        feature_sets=[first, second],
        events=events,
    )
    fetch_all_feeds_stubs([feed], lambda _url, _gis: layer_stub)
    # The first fetch downloads and writes the snapshot.
    assert (
        peri_scribe.fetching.fetch_all_feeds(BASE_DIRECTORY, year=2026).changed is True
    )
    assert events == ["timestamp", "download"]
    events.clear()
    # A full fetch downloads even though the timestamp is unchanged, and writes a
    # fresh snapshot holding only the changed feature.
    result = peri_scribe.fetching.fetch_all_feeds(
        BASE_DIRECTORY,
        year=2026,
        full=True,
    )
    assert result.changed is True
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
    assert list(geo_package_store.layer(second_path, SAMPLE_FEED_NAME)["name"]) == [
        "a-changed",
    ]


def test_fetch_all_feeds_full_writes_no_new_file_when_nothing_changed(
    fetch_all_feeds_stubs: typing.Callable[..., None],
    geo_package_store: GeoPackageStore,
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
    fetch_all_feeds_stubs([sample_feed_stub()], lambda _url, _gis: layer_stub)
    assert (
        peri_scribe.fetching.fetch_all_feeds(BASE_DIRECTORY, year=2026).changed is True
    )
    full_result = peri_scribe.fetching.fetch_all_feeds(
        BASE_DIRECTORY,
        year=2026,
        full=True,
    )
    assert full_result.changed is False
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


def test_fetch_all_feeds_writes_current_state_file(
    feature_set_with_geometry: arcgis.features.FeatureSet,
    fetch_all_feeds_stubs: typing.Callable[..., None],
    geo_package_store: GeoPackageStore,
) -> None:
    fetch_all_feeds_stubs(
        [sample_feed_stub()],
        lambda url, gis: FeatureLayerStub(url, gis, feature_set_with_geometry),
    )
    peri_scribe.fetching.fetch_all_feeds(BASE_DIRECTORY, year=2026)
    state_path = peri_scribe.snapshots.current_state_path(
        peri_scribe.snapshots.source_directory_path(
            BASE_DIRECTORY,
            2026,
            SAMPLE_FEED_NAME,
        ),
        0,
    )
    assert geo_package_store.has(state_path)
    written = geo_package_store.layer(state_path, SAMPLE_FEED_NAME)
    assert list(written["name"]) == ["a", "b"]


def test_fetch_all_feeds_continues_when_state_update_fails(
    monkeypatch: pytest.MonkeyPatch,
    feature_set_with_geometry: arcgis.features.FeatureSet,
    fetch_all_feeds_stubs: typing.Callable[..., None],
    geo_package_store: GeoPackageStore,
) -> None:
    fetch_all_feeds_stubs(
        [sample_feed_stub()],
        lambda url, gis: FeatureLayerStub(url, gis, feature_set_with_geometry),
    )

    def failing_state_update(
        *_arguments: object,
        **_keywords: object,
    ) -> None:
        message = "state write failed"
        raise RuntimeError(message)

    monkeypatch.setattr(
        peri_scribe.changes,
        "write_current_state",
        failing_state_update,
    )
    result = peri_scribe.fetching.fetch_all_feeds(BASE_DIRECTORY, year=2026)
    assert result.changed is True
    assert geo_package_store.has(snapshot_path())


def test_fetch_all_feeds_reindexes_after_successful_fetch(
    monkeypatch: pytest.MonkeyPatch,
    feature_set_with_geometry: arcgis.features.FeatureSet,
    fetch_all_feeds_stubs: typing.Callable[..., None],
    geo_package_store: GeoPackageStore,
) -> None:
    fetch_all_feeds_stubs(
        [sample_feed_stub()],
        lambda url, gis: FeatureLayerStub(url, gis, feature_set_with_geometry),
    )
    indexed: list[pathlib.Path] = []
    monkeypatch.setattr(
        peri_scribe.fire_index,
        "index_fire_sources",
        indexed.append,
    )
    result = peri_scribe.fetching.fetch_all_feeds(BASE_DIRECTORY, year=2026)
    assert result.changed is True
    assert indexed == [BASE_DIRECTORY / "data" / "2026"]


def test_fetch_all_feeds_reindexes_after_a_feed_fails(
    monkeypatch: pytest.MonkeyPatch,
    feature_set_with_geometry: arcgis.features.FeatureSet,
    fetch_all_feeds_stubs: typing.Callable[..., None],
    geo_package_store: GeoPackageStore,
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

    def layer_factory(url: str, gis: object) -> FeatureLayerStub:
        if url == failing.url:
            return FeatureLayerStub(
                url,
                gis,
                arcgis.features.FeatureSet([]),
                query_error=RuntimeError("boom"),
            )
        return FeatureLayerStub(url, gis, feature_set_with_geometry)

    fetch_all_feeds_stubs([failing, working], layer_factory)
    indexed: list[pathlib.Path] = []
    monkeypatch.setattr(
        peri_scribe.fire_index,
        "index_fire_sources",
        indexed.append,
    )
    with pytest.raises(SystemExit, match=f"Failed to fetch {failing.name}: boom"):
        peri_scribe.fetching.fetch_all_feeds(BASE_DIRECTORY, year=2026)
    assert indexed == [BASE_DIRECTORY / "data" / "2026"]
    assert geo_package_store.has(snapshot_path(feed_name=working.name))
    assert not geo_package_store.has(snapshot_path(feed_name=failing.name))


def test_fetch_all_feeds_does_not_reindex_when_no_feed_succeeds(
    monkeypatch: pytest.MonkeyPatch,
    fetch_all_feeds_stubs: typing.Callable[..., None],
) -> None:
    fetch_all_feeds_stubs(
        [sample_feed_stub()],
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
    with pytest.raises(SystemExit, match="Failed to fetch"):
        peri_scribe.fetching.fetch_all_feeds(BASE_DIRECTORY, year=2026)
    assert indexed == []


def test_fetch_all_feeds_defaults_to_working_directory_and_year(
    monkeypatch: pytest.MonkeyPatch,
    feature_set_with_geometry: arcgis.features.FeatureSet,
    fetch_all_feeds_stubs: typing.Callable[..., None],
    geo_package_store: GeoPackageStore,
) -> None:
    monkeypatch.setattr(
        pathlib.Path,
        "cwd",
        staticmethod(lambda: BASE_DIRECTORY),
    )
    fetch_all_feeds_stubs(
        [sample_feed_stub()],
        lambda url, gis: FeatureLayerStub(url, gis, feature_set_with_geometry),
    )
    result = peri_scribe.fetching.fetch_all_feeds()
    assert result.changed is True
    year = datetime.date.today().year
    output_path = peri_scribe.snapshots.source_geopackage_path(
        BASE_DIRECTORY,
        year,
        SAMPLE_FEED_NAME,
        peri_scribe.snapshots.SourceFile(
            serial_number=0,
            last_edit_timestamp=SAMPLE_LAST_EDIT_TIMESTAMP,
        ),
    )
    assert geo_package_store.has(output_path)
