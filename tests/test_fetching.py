"""Tests for peri_scribe.fetching."""

from __future__ import annotations

import datetime
import pathlib

import geopandas
import pandas as pd
import pyproj
import pytest
import shapely.geometry

import peri_scribe.changes
import peri_scribe.exceptions
import peri_scribe.feed_types
import peri_scribe.feeds
import peri_scribe.fetching
import peri_scribe.geo_data
import peri_scribe.models
import peri_scribe.output
import peri_scribe.snapshots
from tests.factories import change_feed


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
            "/base/data/2026/sources-complete",
        )
        return frames[feed.name]

    monkeypatch.setattr(peri_scribe.fetching, "fetch_feed", fetch_feed)
    paths = peri_scribe.fetching.fetch_all_feeds_complete(
        pathlib.Path("/base"),
        year=2026,
    )
    assert paths == (
        pathlib.Path("/base/data/2026/sources-complete/Fires0_0.gpkg"),
        pathlib.Path("/base/data/2026/sources-complete/Fires1_0.gpkg"),
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
        pathlib.Path("/base/data/2026/sources-complete/Fires1_0.gpkg"),
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
    assert paths == (
        pathlib.Path(f"/fetch/data/{year}/sources-complete/Fires0_0.gpkg"),
    )
