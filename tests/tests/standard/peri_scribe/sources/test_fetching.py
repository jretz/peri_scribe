"""Tests for peri_scribe.sources.fetching."""

from __future__ import annotations

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

import peri_scribe.fires.index
import peri_scribe.geo.data
import peri_scribe.logging
import peri_scribe.models
import peri_scribe.output
import peri_scribe.retry
import peri_scribe.sources.feed_state
import peri_scribe.sources.feeds
import peri_scribe.sources.fetching
import peri_scribe.sources.snapshots
import tests.helpers.doubles.arcgis
import tests.helpers.doubles.peri_scribe.snapshot_storage
import tests.helpers.doubles.peri_scribe.sources.fetching
import tests.helpers.factories.arcgis
import tests.helpers.factories.geography
import tests.helpers.factories.peri_scribe.retry
import tests.helpers.factories.peri_scribe.sources.feed_types
import tests.helpers.factories.peri_scribe.sources.fetching
import tests.helpers.factories.peri_scribe.sources.snapshots


def test_fetch_feed_dataframe_raises_without_change_columns() -> None:
    feed = tests.helpers.factories.peri_scribe.sources.feed_types.change_feed(
        change_columns=(),
    )
    with pytest.raises(ValueError, match="no change columns"):
        peri_scribe.sources.fetching.fetch_feed_dataframe(
            feed,
            typing.cast("arcgis.features.FeatureLayer", object()),
            [
                peri_scribe.sources.snapshots.SourceFile(
                    serial_number=0,
                    last_edit_timestamp=0,
                ),
            ],
            pathlib.Path("/sources"),
        )


def test_fetch_feed_dataframe_returns_none_without_changed_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    feed = tests.helpers.factories.peri_scribe.sources.feed_types.change_feed()
    monkeypatch.setattr(
        peri_scribe.sources.feed_state,
        "existing_features",
        lambda _directory, _feed: None,
    )
    monkeypatch.setattr(
        peri_scribe.geo.data,
        "query_object_ids_with_retry",
        lambda *_args, **_kwargs: [],
    )
    result = peri_scribe.sources.fetching.fetch_feed_dataframe(
        feed,
        typing.cast("arcgis.features.FeatureLayer", object()),
        [
            peri_scribe.sources.snapshots.SourceFile(
                serial_number=0,
                last_edit_timestamp=0,
            ),
        ],
        pathlib.Path("/sources"),
    )
    assert result is None


def test_fetch_feed_dataframe_returns_none_when_dedupe_removes_all(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    feed = tests.helpers.factories.peri_scribe.sources.feed_types.change_feed()
    monkeypatch.setattr(
        peri_scribe.sources.feed_state,
        "existing_features",
        lambda _directory, _feed: None,
    )
    monkeypatch.setattr(
        peri_scribe.geo.data,
        "query_object_ids_with_retry",
        lambda *_args, **_kwargs: [1],
    )
    monkeypatch.setattr(
        peri_scribe.geo.data,
        "query_with_retry",
        lambda *_args, **_kwargs: "feature_set",
    )
    empty = geopandas.GeoDataFrame(
        {"OBJECTID": pd.Series([], dtype="int64"), "name": []},
        geometry=[],
        crs=pyproj.CRS.from_epsg(4326),
    )
    monkeypatch.setattr(
        peri_scribe.geo.data,
        "dataframe_for_layer",
        lambda *_args, **_kwargs: empty,
    )
    result = peri_scribe.sources.fetching.fetch_feed_dataframe(
        feed,
        typing.cast("arcgis.features.FeatureLayer", object()),
        [
            peri_scribe.sources.snapshots.SourceFile(
                serial_number=0,
                last_edit_timestamp=0,
            ),
        ],
        pathlib.Path("/sources"),
    )
    assert result is None


def test_fetch_feed_dataframe_queries_null_modified_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    feed = tests.helpers.factories.peri_scribe.sources.feed_types.change_feed()
    captured: list[str] = []
    monkeypatch.setattr(
        peri_scribe.sources.feed_state,
        "existing_features",
        lambda _directory, _feed: None,
    )

    capture_where = (
        tests.helpers.doubles.peri_scribe.sources.fetching
    ).make_missing_date_filter_recorder(
        captured=captured,
    )

    monkeypatch.setattr(
        peri_scribe.geo.data,
        "query_object_ids_with_retry",
        capture_where,
    )
    result = peri_scribe.sources.fetching.fetch_feed_dataframe(
        feed,
        typing.cast("arcgis.features.FeatureLayer", object()),
        [
            peri_scribe.sources.snapshots.SourceFile(
                serial_number=0,
                last_edit_timestamp=0,
            ),
        ],
        pathlib.Path("/sources"),
    )
    assert result is None
    assert "IS NULL" in captured[0]
    assert captured[1] == "1=1"


def test_fetch_feed_dataframe_fetches_ids_present_but_not_stored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    feed = tests.helpers.factories.peri_scribe.sources.feed_types.change_feed()
    existing = geopandas.GeoDataFrame(
        {"OBJECTID": [1, 2]},
        geometry=[shapely.geometry.Point(0.0, 0.0) for _ in (1, 2)],
        crs=pyproj.CRS.from_epsg(4326),
    )
    monkeypatch.setattr(
        peri_scribe.sources.feed_state,
        "existing_features",
        lambda _directory, _feed: existing,
    )
    # First call (timestamp query) finds no changed rows; second call (full layer)
    # reports OBJECTID 3 as present in the layer but never stored.
    monkeypatch.setattr(
        peri_scribe.geo.data,
        "query_object_ids_with_retry",
        lambda *_args, **kwargs: [] if kwargs["where"] != "1=1" else [3],
    )
    fetched: dict[str, object] = {}
    monkeypatch.setattr(
        peri_scribe.geo.data,
        "query_with_retry",
        lambda *_args, **kwargs: fetched.update(kwargs) or "feature_set",
    )
    sentinel = geopandas.GeoDataFrame(
        {"OBJECTID": [3], "name": ["c"]},
        geometry=[shapely.geometry.Point(2.0, 2.0)],
        crs=pyproj.CRS.from_epsg(4326),
    )
    monkeypatch.setattr(
        peri_scribe.geo.data,
        "dataframe_for_layer",
        lambda *_args, **_kwargs: sentinel,
    )
    result = peri_scribe.sources.fetching.fetch_feed_dataframe(
        feed,
        typing.cast("arcgis.features.FeatureLayer", object()),
        [
            peri_scribe.sources.snapshots.SourceFile(
                serial_number=0,
                last_edit_timestamp=0,
            ),
        ],
        pathlib.Path("/sources"),
    )
    assert fetched["parameters"] == {"object_ids": "3"}
    assert result is not None
    assert list(result["OBJECTID"]) == [3]


def test_fetch_feed_dataframe_fetches_stored_active_rows_now_inactive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    feed = tests.helpers.factories.peri_scribe.sources.feed_types.change_feed()
    existing = geopandas.GeoDataFrame(
        {"OBJECTID": [1, 2, 3], "status": ["Active", "Active", "Inactive"]},
        geometry=[shapely.geometry.Point(x, 0.0) for x in (0.0, 1.0, 2.0)],
        crs=pyproj.CRS.from_epsg(4326),
    )
    monkeypatch.setattr(
        peri_scribe.sources.feed_state,
        "existing_features",
        lambda _directory, _feed: existing,
    )
    wheres: list[str] = []

    query_ids = (
        tests.helpers.doubles.peri_scribe.sources.fetching.make_active_object_id_query(
            wheres=wheres,
        )
    )

    monkeypatch.setattr(peri_scribe.geo.data, "query_object_ids_with_retry", query_ids)
    fetched: dict[str, object] = {}
    monkeypatch.setattr(
        peri_scribe.geo.data,
        "query_with_retry",
        lambda *_args, **kwargs: fetched.update(kwargs) or "feature_set",
    )
    flipped = geopandas.GeoDataFrame(
        {"OBJECTID": [2], "status": ["Inactive"]},
        geometry=[shapely.geometry.Point(1.0, 0.0)],
        crs=pyproj.CRS.from_epsg(4326),
    )
    monkeypatch.setattr(
        peri_scribe.geo.data,
        "dataframe_for_layer",
        lambda *_args, **_kwargs: flipped,
    )
    result = peri_scribe.sources.fetching.fetch_feed_dataframe(
        feed,
        typing.cast("arcgis.features.FeatureLayer", object()),
        [
            peri_scribe.sources.snapshots.SourceFile(
                serial_number=0,
                last_edit_timestamp=0,
            ),
        ],
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
    feed = tests.helpers.factories.peri_scribe.sources.feed_types.change_feed()
    existing = geopandas.GeoDataFrame(
        {"OBJECTID": [1, 2], "status": ["Active", "Inactive"]},
        geometry=[shapely.geometry.Point(x, 0.0) for x in (0.0, 1.0)],
        crs=pyproj.CRS.from_epsg(4326),
    )
    monkeypatch.setattr(
        peri_scribe.sources.feed_state,
        "existing_features",
        lambda _directory, _feed: existing,
    )
    monkeypatch.setattr(
        peri_scribe.geo.data,
        "query_object_ids_with_retry",
        lambda *_args, **kwargs: [1, 2] if kwargs["where"] == "1=1" else [],
    )
    result = peri_scribe.sources.fetching.fetch_feed_dataframe(
        feed,
        typing.cast("arcgis.features.FeatureLayer", object()),
        [
            peri_scribe.sources.snapshots.SourceFile(
                serial_number=0,
                last_edit_timestamp=0,
            ),
        ],
        pathlib.Path("/sources"),
    )
    assert result is None


def test_fetch_feed_dataframe_skips_flip_query_without_stored_inactive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    feed = tests.helpers.factories.peri_scribe.sources.feed_types.change_feed()
    existing = geopandas.GeoDataFrame(
        {"OBJECTID": [1, 2], "status": ["Active", "Active"]},
        geometry=[shapely.geometry.Point(x, 0.0) for x in (0.0, 1.0)],
        crs=pyproj.CRS.from_epsg(4326),
    )
    monkeypatch.setattr(
        peri_scribe.sources.feed_state,
        "existing_features",
        lambda _directory, _feed: existing,
    )
    wheres: list[str] = []
    monkeypatch.setattr(
        peri_scribe.geo.data,
        "query_object_ids_with_retry",
        lambda *_args, **kwargs: (
            wheres.append(str(kwargs["where"]))
            or ([1, 2] if kwargs["where"] == "1=1" else [])
        ),
    )
    result = peri_scribe.sources.fetching.fetch_feed_dataframe(
        feed,
        typing.cast("arcgis.features.FeatureLayer", object()),
        [
            peri_scribe.sources.snapshots.SourceFile(
                serial_number=0,
                last_edit_timestamp=0,
            ),
        ],
        pathlib.Path("/sources"),
    )
    assert result is None
    assert not any("status IN" in where for where in wheres)


def test_fetch_feed_dataframe_fetches_full_when_directory_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    feed = tests.helpers.factories.peri_scribe.sources.feed_types.change_feed()
    sentinel = object()
    monkeypatch.setattr(
        peri_scribe.geo.data,
        "query_with_retry",
        lambda *_args, **_kwargs: "feature_set",
    )
    monkeypatch.setattr(
        peri_scribe.geo.data,
        "dataframe_for_layer",
        lambda *_args, **_kwargs: sentinel,
    )
    result = peri_scribe.sources.fetching.fetch_feed_dataframe(
        feed,
        typing.cast("arcgis.features.FeatureLayer", object()),
        [],
        pathlib.Path("/sources"),
    )
    assert result is sentinel


def test_fetch_all_feeds_complete_writes_each_feed_in_full(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    feeds = [
        tests.helpers.factories.peri_scribe.sources.fetching.complete_fetch_feed(0),
        tests.helpers.factories.peri_scribe.sources.fetching.complete_fetch_feed(1),
    ]
    monkeypatch.setattr(peri_scribe.sources.feeds, "FEEDS", feeds)
    tests.helpers.doubles.peri_scribe.sources.fetching.stub_complete_fetch(monkeypatch)
    written: list[tuple[pathlib.Path, list[peri_scribe.models.LayerData]]] = []
    monkeypatch.setattr(
        peri_scribe.output,
        "write_geopackage",
        lambda path, layers: written.append((path, layers)),
    )
    frames = {feed.name: object() for feed in feeds}

    fetch_feed = (
        tests.helpers.doubles.peri_scribe.sources.fetching.make_complete_feed_reader(
            frames=frames,
        )
    )

    monkeypatch.setattr(peri_scribe.sources.fetching, "fetch_feed", fetch_feed)
    paths = peri_scribe.sources.fetching.fetch_all_feeds_complete(
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
        tests.helpers.factories.peri_scribe.sources.fetching.complete_fetch_feed(0),
        tests.helpers.factories.peri_scribe.sources.fetching.complete_fetch_feed(1),
        tests.helpers.factories.peri_scribe.sources.fetching.complete_fetch_feed(2),
    ]
    monkeypatch.setattr(peri_scribe.sources.feeds, "FEEDS", feeds)
    tests.helpers.doubles.peri_scribe.sources.fetching.stub_complete_fetch(monkeypatch)
    written: list[pathlib.Path] = []
    monkeypatch.setattr(
        peri_scribe.output,
        "write_geopackage",
        lambda path, _layers: written.append(path),
    )

    fetch_feed = tests.helpers.doubles.peri_scribe.sources.fetching.mixed_feed_outcome

    monkeypatch.setattr(peri_scribe.sources.fetching, "fetch_feed", fetch_feed)
    with pytest.raises(SystemExit) as raised:
        peri_scribe.sources.fetching.fetch_all_feeds_complete(
            pathlib.Path("/base"),
            year=2026,
        )
    assert str(raised.value) == (
        "Failed to fetch Fires0_0: boom\n"
        "Failed to fetch Fires2_0: fetch produced no data"
    )
    assert written == [pathlib.Path("/base/data/2026/validation/Fires1_0.gpkg")]


def test_fetch_all_feeds_complete_defaults_to_working_directory_and_year(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        peri_scribe.sources.feeds,
        "FEEDS",
        [tests.helpers.factories.peri_scribe.sources.fetching.complete_fetch_feed(0)],
    )
    tests.helpers.doubles.peri_scribe.sources.fetching.stub_complete_fetch(monkeypatch)
    monkeypatch.setattr(
        pathlib.Path,
        "cwd",
        staticmethod(lambda: pathlib.Path("/fetch")),
    )
    monkeypatch.setattr(
        peri_scribe.sources.fetching,
        "fetch_feed",
        lambda *_args, **_kwargs: object(),
    )
    year = datetime.date.today().year
    paths = peri_scribe.sources.fetching.fetch_all_feeds_complete()
    assert paths == (pathlib.Path(f"/fetch/data/{year}/validation/Fires0_0.gpkg"),)


def test_fetch_all_feeds_writes_geo_package(
    feature_set_with_geometry: arcgis.features.FeatureSet,
    fetch_all_feeds_stubs: typing.Callable[..., None],
    geo_package_store: (
        tests.helpers.doubles.peri_scribe.snapshot_storage.GeoPackageStore
    ),
) -> None:
    fetch_all_feeds_stubs(
        [tests.helpers.doubles.peri_scribe.sources.fetching.sample_feed_stub()],
        lambda url, gis: tests.helpers.doubles.arcgis.FeatureLayerStub(
            url,
            gis,
            feature_set_with_geometry,
        ),
    )
    result = peri_scribe.sources.fetching.fetch_all_feeds(
        tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY,
        year=2026,
    )
    assert result.changed is True
    output_path = tests.helpers.factories.peri_scribe.sources.snapshots.snapshot_path()
    assert geo_package_store.has(output_path)
    written = geo_package_store.layer(
        output_path,
        tests.helpers.factories.peri_scribe.sources.feed_types.SAMPLE_FEED_NAME,
    )
    assert list(written["name"]) == ["a", "b"]
    assert written.crs == pyproj.CRS.from_epsg(
        tests.helpers.factories.geography.WGS84_WKID,
    )


def test_fetch_all_feeds_reports_query_failure(
    fetch_all_feeds_stubs: typing.Callable[..., None],
    geo_package_store: (
        tests.helpers.doubles.peri_scribe.snapshot_storage.GeoPackageStore
    ),
) -> None:
    feed_name = tests.helpers.factories.peri_scribe.sources.feed_types.SAMPLE_FEED_NAME
    fetch_all_feeds_stubs(
        [tests.helpers.doubles.peri_scribe.sources.fetching.sample_feed_stub()],
        lambda url, gis: tests.helpers.doubles.arcgis.FeatureLayerStub(
            url,
            gis,
            arcgis.features.FeatureSet([]),
            query_error=RuntimeError("boom"),
        ),
    )
    with pytest.raises(
        SystemExit,
        match=f"Failed to fetch {feed_name}: boom",
    ):
        peri_scribe.sources.fetching.fetch_all_feeds(
            tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY,
            year=2026,
        )
    assert not geo_package_store.has(
        tests.helpers.factories.peri_scribe.sources.snapshots.snapshot_path(),
    )


def test_fetch_all_feeds_reports_empty_layer(
    fetch_all_feeds_stubs: typing.Callable[..., None],
    geo_package_store: (
        tests.helpers.doubles.peri_scribe.snapshot_storage.GeoPackageStore
    ),
) -> None:
    feed_name = tests.helpers.factories.peri_scribe.sources.feed_types.SAMPLE_FEED_NAME
    fetch_all_feeds_stubs(
        [tests.helpers.doubles.peri_scribe.sources.fetching.sample_feed_stub()],
        lambda url, gis: tests.helpers.doubles.arcgis.FeatureLayerStub(
            url,
            gis,
            arcgis.features.FeatureSet([]),
        ),
    )
    with pytest.raises(
        SystemExit,
        match=(
            f"Failed to fetch {feed_name}: "
            f"Feed {feed_name} "
            "returned no features; no output was written"
        ),
    ):
        peri_scribe.sources.fetching.fetch_all_feeds(
            tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY,
            year=2026,
        )
    assert not geo_package_store.has(
        tests.helpers.factories.peri_scribe.sources.snapshots.snapshot_path(),
    )


def test_fetch_all_feeds_retries_on_rate_limit(
    monkeypatch: pytest.MonkeyPatch,
    feature_set_with_geometry: arcgis.features.FeatureSet,
    fetch_all_feeds_stubs: typing.Callable[..., None],
    geo_package_store: (
        tests.helpers.doubles.peri_scribe.snapshot_storage.GeoPackageStore
    ),
) -> None:
    sleep_calls: list[float] = []
    monkeypatch.setattr(time, "sleep", sleep_calls.append)
    rate_limit_error = ValueError(
        tests.helpers.factories.peri_scribe.retry.RATE_LIMIT_ERROR_PAYLOAD,
    )
    outcomes: list[arcgis.features.FeatureSet | Exception] = [
        rate_limit_error,
        feature_set_with_geometry,
    ]
    fetch_all_feeds_stubs(
        [tests.helpers.doubles.peri_scribe.sources.fetching.sample_feed_stub()],
        lambda url, gis: (
            tests.helpers.doubles.peri_scribe.sources.fetching.MultiQueryLayerStub(
                url,
                gis,
                outcomes,
            )
        ),
    )
    result = peri_scribe.sources.fetching.fetch_all_feeds(
        tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY,
        year=2026,
    )
    assert result.changed is True
    output_path = tests.helpers.factories.peri_scribe.sources.snapshots.snapshot_path()
    assert geo_package_store.has(output_path)
    assert sleep_calls == [60.0]
    written = geo_package_store.layer(
        output_path,
        tests.helpers.factories.peri_scribe.sources.feed_types.SAMPLE_FEED_NAME,
    )
    assert list(written["name"]) == ["a", "b"]


def test_fetch_all_feeds_exhausts_retries(
    monkeypatch: pytest.MonkeyPatch,
    fetch_all_feeds_stubs: typing.Callable[..., None],
    geo_package_store: (
        tests.helpers.doubles.peri_scribe.snapshot_storage.GeoPackageStore
    ),
) -> None:
    feed_name = tests.helpers.factories.peri_scribe.sources.feed_types.SAMPLE_FEED_NAME
    sleep_calls: list[float] = []
    monkeypatch.setattr(time, "sleep", sleep_calls.append)
    rate_limit_error = ValueError(
        tests.helpers.factories.peri_scribe.retry.RATE_LIMIT_ERROR_PAYLOAD,
    )
    maximum_retries = peri_scribe.retry.DEFAULT_MAXIMUM_RETRIES
    outcomes: list[arcgis.features.FeatureSet | Exception] = [rate_limit_error] * (
        maximum_retries + 2
    )
    fetch_all_feeds_stubs(
        [tests.helpers.doubles.peri_scribe.sources.fetching.sample_feed_stub()],
        lambda url, gis: (
            tests.helpers.doubles.peri_scribe.sources.fetching.MultiQueryLayerStub(
                url,
                gis,
                outcomes,
            )
        ),
    )
    with pytest.raises(
        SystemExit,
        match=f"Failed to fetch {feed_name}: ",
    ):
        peri_scribe.sources.fetching.fetch_all_feeds(
            tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY,
            year=2026,
        )
    assert sleep_calls == [60.0] * maximum_retries
    assert not geo_package_store.has(
        tests.helpers.factories.peri_scribe.sources.snapshots.snapshot_path(),
    )


def test_fetch_all_feeds_writes_one_file_per_source(
    feature_set_with_geometry: arcgis.features.FeatureSet,
    fetch_all_feeds_stubs: typing.Callable[..., None],
    geo_package_store: (
        tests.helpers.doubles.peri_scribe.snapshot_storage.GeoPackageStore
    ),
) -> None:
    first_last_edit_timestamp = 1
    second_last_edit_timestamp = 2
    first = tests.helpers.doubles.peri_scribe.sources.fetching.FeedStub(
        name="First_Source_0",
        url="https://example.test/first",
        last_edit_timestamp=first_last_edit_timestamp,
    )
    second = tests.helpers.doubles.peri_scribe.sources.fetching.FeedStub(
        name="Second_Source_0",
        url="https://example.test/second",
        last_edit_timestamp=second_last_edit_timestamp,
    )
    fetch_all_feeds_stubs(
        [first, second],
        lambda url, gis: tests.helpers.doubles.arcgis.FeatureLayerStub(
            url,
            gis,
            feature_set_with_geometry,
        ),
    )
    result = peri_scribe.sources.fetching.fetch_all_feeds(
        tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY,
        year=2026,
    )
    assert result.changed is True
    first_path = tests.helpers.factories.peri_scribe.sources.snapshots.snapshot_path(
        feed_name=first.name,
        last_edit_timestamp=first_last_edit_timestamp,
    )
    second_path = tests.helpers.factories.peri_scribe.sources.snapshots.snapshot_path(
        feed_name=second.name,
        last_edit_timestamp=second_last_edit_timestamp,
    )
    assert geo_package_store.has(first_path)
    assert geo_package_store.has(second_path)
    assert first_path.parent == (
        tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY
        / "data"
        / "2026"
        / "sources"
        / "First_Source_0"
        / "000___"
    )
    assert second_path.parent == (
        tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY
        / "data"
        / "2026"
        / "sources"
        / "Second_Source_0"
        / "000___"
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
    geo_package_store: (
        tests.helpers.doubles.peri_scribe.snapshot_storage.GeoPackageStore
    ),
) -> None:
    first_last_edit_timestamp = 1
    second_last_edit_timestamp = 2
    full = tests.helpers.factories.arcgis.wgs84_feature_set([
        (1, "a", 1.0, 2.0),
        (2, "b", 3.0, 4.0),
    ])
    delta = tests.helpers.factories.arcgis.wgs84_feature_set([(3, "c", 5.0, 6.0)])
    fetch_all_feeds_stubs(
        [
            tests.helpers.doubles.peri_scribe.sources.fetching.FeedStub(
                name=tests.helpers.factories.peri_scribe.sources.feed_types.SAMPLE_FEED_NAME,
                url=tests.helpers.factories.peri_scribe.sources.feed_types.SAMPLE_FEED_URL,
                last_edit_timestamp=first_last_edit_timestamp,
            ),
        ],
        lambda url, gis: (
            tests.helpers.doubles.peri_scribe.sources.fetching.DeltaFeatureLayerStub(
                url,
                gis,
                full,
                delta,
            )
        ),
    )
    assert (
        peri_scribe.sources.fetching.fetch_all_feeds(
            tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY,
            year=2026,
        ).changed
        is True
    )
    fetch_all_feeds_stubs(
        [
            tests.helpers.doubles.peri_scribe.sources.fetching.FeedStub(
                name=tests.helpers.factories.peri_scribe.sources.feed_types.SAMPLE_FEED_NAME,
                url=tests.helpers.factories.peri_scribe.sources.feed_types.SAMPLE_FEED_URL,
                last_edit_timestamp=second_last_edit_timestamp,
            ),
        ],
        lambda url, gis: (
            tests.helpers.doubles.peri_scribe.sources.fetching.DeltaFeatureLayerStub(
                url,
                gis,
                full,
                delta,
            )
        ),
    )
    assert (
        peri_scribe.sources.fetching.fetch_all_feeds(
            tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY,
            year=2026,
        ).changed
        is True
    )
    first_path = tests.helpers.factories.peri_scribe.sources.snapshots.snapshot_path(
        last_edit_timestamp=first_last_edit_timestamp,
    )
    second_path = tests.helpers.factories.peri_scribe.sources.snapshots.snapshot_path(
        serial_number=1,
        last_edit_timestamp=second_last_edit_timestamp,
    )
    assert geo_package_store.has(first_path)
    assert geo_package_store.has(second_path)
    assert list(
        geo_package_store.layer(
            first_path,
            tests.helpers.factories.peri_scribe.sources.feed_types.SAMPLE_FEED_NAME,
        )["name"],
    ) == [
        "a",
        "b",
    ]
    assert list(
        geo_package_store.layer(
            second_path,
            tests.helpers.factories.peri_scribe.sources.feed_types.SAMPLE_FEED_NAME,
        )["name"],
    ) == ["c"]


def test_fetch_all_feeds_writes_no_new_file_when_nothing_changed(
    fetch_all_feeds_stubs: typing.Callable[..., None],
    geo_package_store: (
        tests.helpers.doubles.peri_scribe.snapshot_storage.GeoPackageStore
    ),
) -> None:
    first_last_edit_timestamp = 1
    second_last_edit_timestamp = 2
    full = tests.helpers.factories.arcgis.wgs84_feature_set([
        (1, "a", 1.0, 2.0),
        (2, "b", 3.0, 4.0),
    ])
    fetch_all_feeds_stubs(
        [
            tests.helpers.doubles.peri_scribe.sources.fetching.FeedStub(
                name=tests.helpers.factories.peri_scribe.sources.feed_types.SAMPLE_FEED_NAME,
                url=tests.helpers.factories.peri_scribe.sources.feed_types.SAMPLE_FEED_URL,
                last_edit_timestamp=first_last_edit_timestamp,
            ),
        ],
        lambda url, gis: (
            tests.helpers.doubles.peri_scribe.sources.fetching.DeltaFeatureLayerStub(
                url,
                gis,
                full,
                arcgis.features.FeatureSet([]),
            )
        ),
    )
    assert (
        peri_scribe.sources.fetching.fetch_all_feeds(
            tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY,
            year=2026,
        ).changed
        is True
    )
    fetch_all_feeds_stubs(
        [
            tests.helpers.doubles.peri_scribe.sources.fetching.FeedStub(
                name=tests.helpers.factories.peri_scribe.sources.feed_types.SAMPLE_FEED_NAME,
                url=tests.helpers.factories.peri_scribe.sources.feed_types.SAMPLE_FEED_URL,
                last_edit_timestamp=second_last_edit_timestamp,
            ),
        ],
        lambda url, gis: (
            tests.helpers.doubles.peri_scribe.sources.fetching.DeltaFeatureLayerStub(
                url,
                gis,
                full,
                arcgis.features.FeatureSet([]),
            )
        ),
    )
    second_result = peri_scribe.sources.fetching.fetch_all_feeds(
        tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY,
        year=2026,
    )
    assert second_result.changed is False
    assert geo_package_store.has(
        tests.helpers.factories.peri_scribe.sources.snapshots.snapshot_path(
            last_edit_timestamp=first_last_edit_timestamp,
        ),
    )
    assert not geo_package_store.has(
        tests.helpers.factories.peri_scribe.sources.snapshots.snapshot_path(
            serial_number=1,
            last_edit_timestamp=second_last_edit_timestamp,
        ),
    )


def test_fetch_all_feeds_reuses_serial_number_for_unchanged_timestamp(
    feature_set_with_geometry: arcgis.features.FeatureSet,
    fetch_all_feeds_stubs: typing.Callable[..., None],
    geo_package_store: (
        tests.helpers.doubles.peri_scribe.snapshot_storage.GeoPackageStore
    ),
) -> None:
    last_edit_timestamp = 1
    fetch_all_feeds_stubs(
        [
            tests.helpers.doubles.peri_scribe.sources.fetching.FeedStub(
                name=tests.helpers.factories.peri_scribe.sources.feed_types.SAMPLE_FEED_NAME,
                url=tests.helpers.factories.peri_scribe.sources.feed_types.SAMPLE_FEED_URL,
                last_edit_timestamp=last_edit_timestamp,
            ),
        ],
        lambda url, gis: tests.helpers.doubles.arcgis.FeatureLayerStub(
            url,
            gis,
            feature_set_with_geometry,
        ),
    )
    assert (
        peri_scribe.sources.fetching.fetch_all_feeds(
            tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY,
            year=2026,
        ).changed
        is True
    )
    second_result = peri_scribe.sources.fetching.fetch_all_feeds(
        tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY,
        year=2026,
    )
    assert second_result.changed is False
    assert geo_package_store.has(
        tests.helpers.factories.peri_scribe.sources.snapshots.snapshot_path(
            last_edit_timestamp=last_edit_timestamp,
        ),
    )
    assert not geo_package_store.has(
        tests.helpers.factories.peri_scribe.sources.snapshots.snapshot_path(
            serial_number=1,
            last_edit_timestamp=last_edit_timestamp,
        ),
    )


def test_fetch_all_feeds_fails_when_last_edit_timestamp_unavailable(
    fetch_all_feeds_stubs: typing.Callable[..., None],
    geo_package_store: (
        tests.helpers.doubles.peri_scribe.snapshot_storage.GeoPackageStore
    ),
) -> None:
    fetch_all_feeds_stubs(
        [
            tests.helpers.doubles.peri_scribe.sources.fetching.FeedStub(
                name=tests.helpers.factories.peri_scribe.sources.feed_types.SAMPLE_FEED_NAME,
                url=tests.helpers.factories.peri_scribe.sources.feed_types.SAMPLE_FEED_URL,
                last_edit_timestamp=None,
            ),
        ],
        lambda _url, _gis: object(),
    )
    with pytest.raises(SystemExit, match="no last-edit timestamp could be observed"):
        peri_scribe.sources.fetching.fetch_all_feeds(
            tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY,
            year=2026,
        )
    assert not geo_package_store.has(
        tests.helpers.factories.peri_scribe.sources.snapshots.snapshot_path(),
    )


def test_fetch_all_feeds_observes_timestamp_before_downloading(
    feature_set_with_geometry: arcgis.features.FeatureSet,
    fetch_all_feeds_stubs: typing.Callable[..., None],
    geo_package_store: (
        tests.helpers.doubles.peri_scribe.snapshot_storage.GeoPackageStore
    ),
) -> None:
    events: list[str] = []
    feed = tests.helpers.doubles.peri_scribe.sources.fetching.FeedStub(
        name=tests.helpers.factories.peri_scribe.sources.feed_types.SAMPLE_FEED_NAME,
        url=tests.helpers.factories.peri_scribe.sources.feed_types.SAMPLE_FEED_URL,
        last_edit_timestamp=tests.helpers.factories.peri_scribe.sources.snapshots.SAMPLE_LAST_EDIT_TIMESTAMP,
        events=events,
    )
    fetch_all_feeds_stubs(
        [feed],
        lambda url, gis: (
            tests.helpers.doubles.peri_scribe.sources.fetching.RecordingFeatureLayerStub(
                url,
                gis,
                feature_set_with_geometry,
                events,
            )
        ),
    )
    peri_scribe.sources.fetching.fetch_all_feeds(
        tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY,
        year=2026,
    )
    assert events == ["timestamp", "download"]


def test_fetch_all_feeds_skips_download_when_timestamp_present(
    feature_set_with_geometry: arcgis.features.FeatureSet,
    fetch_all_feeds_stubs: typing.Callable[..., None],
    geo_package_store: (
        tests.helpers.doubles.peri_scribe.snapshot_storage.GeoPackageStore
    ),
) -> None:
    events: list[str] = []
    feed = tests.helpers.doubles.peri_scribe.sources.fetching.FeedStub(
        name=tests.helpers.factories.peri_scribe.sources.feed_types.SAMPLE_FEED_NAME,
        url=tests.helpers.factories.peri_scribe.sources.feed_types.SAMPLE_FEED_URL,
        last_edit_timestamp=tests.helpers.factories.peri_scribe.sources.snapshots.SAMPLE_LAST_EDIT_TIMESTAMP,
        events=events,
    )
    fetch_all_feeds_stubs(
        [feed],
        lambda url, gis: (
            tests.helpers.doubles.peri_scribe.sources.fetching.RecordingFeatureLayerStub(
                url,
                gis,
                feature_set_with_geometry,
                events,
            )
        ),
    )
    # The first fetch downloads and writes the snapshot.
    assert (
        peri_scribe.sources.fetching.fetch_all_feeds(
            tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY,
            year=2026,
        ).changed
        is True
    )
    assert events == ["timestamp", "download"]
    events.clear()
    # The second fetch sees the same last-edit timestamp and skips the download.
    with structlog.testing.capture_logs(
        processors=[peri_scribe.logging.serialize_log_values],
    ) as captured:
        result = peri_scribe.sources.fetching.fetch_all_feeds(
            tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY,
            year=2026,
        )
    assert result.changed is False
    assert events == ["timestamp"]
    (skip_event,) = [
        event
        for event in captured
        if event["event"] == "Skipping fetch; data already present"
    ]
    assert (
        skip_event["feed"]
        == tests.helpers.factories.peri_scribe.sources.feed_types.SAMPLE_FEED_NAME
    )
    assert (
        skip_event["last_edit_timestamp"]
        == (
            tests.helpers.factories.peri_scribe.sources.snapshots
        ).SAMPLE_LAST_EDIT_TIMESTAMP
    )
    assert skip_event["path"] == str(
        tests.helpers.factories.peri_scribe.sources.snapshots.snapshot_path(),
    )


def test_fetch_all_feeds_full_downloads_when_timestamp_present(
    fetch_all_feeds_stubs: typing.Callable[..., None],
    geo_package_store: (
        tests.helpers.doubles.peri_scribe.snapshot_storage.GeoPackageStore
    ),
) -> None:
    first = tests.helpers.factories.arcgis.wgs84_feature_set([
        (1, "a", 1.0, 2.0),
        (2, "b", 3.0, 4.0),
    ])
    second = tests.helpers.factories.arcgis.wgs84_feature_set([
        (1, "a-changed", 1.0, 2.0),
        (2, "b", 3.0, 4.0),
    ])
    events: list[str] = []
    feed = tests.helpers.doubles.peri_scribe.sources.fetching.FeedStub(
        name=tests.helpers.factories.peri_scribe.sources.feed_types.SAMPLE_FEED_NAME,
        url=tests.helpers.factories.peri_scribe.sources.feed_types.SAMPLE_FEED_URL,
        last_edit_timestamp=tests.helpers.factories.peri_scribe.sources.snapshots.SAMPLE_LAST_EDIT_TIMESTAMP,
        events=events,
    )
    layer_stub = (
        tests.helpers.doubles.peri_scribe.sources.fetching.SequenceFeatureLayerStub(
            url=tests.helpers.factories.peri_scribe.sources.feed_types.SAMPLE_FEED_URL,
            gis=object(),
            feature_sets=[first, second],
            events=events,
        )
    )
    fetch_all_feeds_stubs([feed], lambda _url, _gis: layer_stub)
    # The first fetch downloads and writes the snapshot.
    assert (
        peri_scribe.sources.fetching.fetch_all_feeds(
            tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY,
            year=2026,
        ).changed
        is True
    )
    assert events == ["timestamp", "download"]
    events.clear()
    # A full fetch downloads even though the timestamp is unchanged, and writes a fresh
    # snapshot holding only the changed feature.
    result = peri_scribe.sources.fetching.fetch_all_feeds(
        tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY,
        year=2026,
        full=True,
    )
    assert result.changed is True
    assert events == ["timestamp", "download"]
    first_path = tests.helpers.factories.peri_scribe.sources.snapshots.snapshot_path(
        last_edit_timestamp=tests.helpers.factories.peri_scribe.sources.snapshots.SAMPLE_LAST_EDIT_TIMESTAMP,
    )
    second_path = tests.helpers.factories.peri_scribe.sources.snapshots.snapshot_path(
        serial_number=1,
        last_edit_timestamp=tests.helpers.factories.peri_scribe.sources.snapshots.SAMPLE_LAST_EDIT_TIMESTAMP,
    )
    assert geo_package_store.has(first_path)
    assert geo_package_store.has(second_path)
    assert list(
        geo_package_store.layer(
            second_path,
            tests.helpers.factories.peri_scribe.sources.feed_types.SAMPLE_FEED_NAME,
        )["name"],
    ) == [
        "a-changed",
    ]


def test_fetch_all_feeds_full_writes_no_new_file_when_nothing_changed(
    fetch_all_feeds_stubs: typing.Callable[..., None],
    geo_package_store: (
        tests.helpers.doubles.peri_scribe.snapshot_storage.GeoPackageStore
    ),
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    full = tests.helpers.factories.arcgis.wgs84_feature_set([
        (1, "a", 1.0, 2.0),
        (2, "b", 3.0, 4.0),
    ])
    layer_stub = (
        tests.helpers.doubles.peri_scribe.sources.fetching.SequenceFeatureLayerStub(
            url=tests.helpers.factories.peri_scribe.sources.feed_types.SAMPLE_FEED_URL,
            gis=object(),
            feature_sets=[full, full],
        )
    )
    fetch_all_feeds_stubs(
        [tests.helpers.doubles.peri_scribe.sources.fetching.sample_feed_stub()],
        lambda _url, _gis: layer_stub,
    )
    assert (
        peri_scribe.sources.fetching.fetch_all_feeds(
            tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY,
            year=2026,
        ).changed
        is True
    )
    index_calls: list[pathlib.Path] = []
    monkeypatch.setattr(
        peri_scribe.fires.index,
        "index_fire_sources",
        index_calls.append,
    )
    full_result = peri_scribe.sources.fetching.fetch_all_feeds(
        tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY,
        year=2026,
        full=True,
    )
    assert full_result.changed is False
    assert index_calls == [
        tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY
        / "data"
        / "2026",
    ]
    assert geo_package_store.has(
        tests.helpers.factories.peri_scribe.sources.snapshots.snapshot_path(
            last_edit_timestamp=tests.helpers.factories.peri_scribe.sources.snapshots.SAMPLE_LAST_EDIT_TIMESTAMP,
        ),
    )
    assert not geo_package_store.has(
        tests.helpers.factories.peri_scribe.sources.snapshots.snapshot_path(
            serial_number=1,
            last_edit_timestamp=tests.helpers.factories.peri_scribe.sources.snapshots.SAMPLE_LAST_EDIT_TIMESTAMP,
        ),
    )


def test_fetch_all_feeds_writes_current_state_file(
    feature_set_with_geometry: arcgis.features.FeatureSet,
    fetch_all_feeds_stubs: typing.Callable[..., None],
    geo_package_store: (
        tests.helpers.doubles.peri_scribe.snapshot_storage.GeoPackageStore
    ),
) -> None:
    fetch_all_feeds_stubs(
        [tests.helpers.doubles.peri_scribe.sources.fetching.sample_feed_stub()],
        lambda url, gis: tests.helpers.doubles.arcgis.FeatureLayerStub(
            url,
            gis,
            feature_set_with_geometry,
        ),
    )
    peri_scribe.sources.fetching.fetch_all_feeds(
        tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY,
        year=2026,
    )
    state_path = peri_scribe.sources.snapshots.current_state_path(
        peri_scribe.sources.snapshots.source_directory_path(
            tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY,
            2026,
            tests.helpers.factories.peri_scribe.sources.feed_types.SAMPLE_FEED_NAME,
        ),
        0,
    )
    assert geo_package_store.has(state_path)
    written = geo_package_store.layer(
        state_path,
        tests.helpers.factories.peri_scribe.sources.feed_types.SAMPLE_FEED_NAME,
    )
    assert list(written["name"]) == ["a", "b"]


def test_fetch_all_feeds_continues_when_state_update_fails(
    monkeypatch: pytest.MonkeyPatch,
    feature_set_with_geometry: arcgis.features.FeatureSet,
    fetch_all_feeds_stubs: typing.Callable[..., None],
    geo_package_store: (
        tests.helpers.doubles.peri_scribe.snapshot_storage.GeoPackageStore
    ),
) -> None:
    fetch_all_feeds_stubs(
        [tests.helpers.doubles.peri_scribe.sources.fetching.sample_feed_stub()],
        lambda url, gis: tests.helpers.doubles.arcgis.FeatureLayerStub(
            url,
            gis,
            feature_set_with_geometry,
        ),
    )

    failing_state_update = (
        tests.helpers.doubles.peri_scribe.sources.fetching.fail_state_update
    )

    monkeypatch.setattr(
        peri_scribe.sources.feed_state,
        "write_current_state",
        failing_state_update,
    )
    result = peri_scribe.sources.fetching.fetch_all_feeds(
        tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY,
        year=2026,
    )
    assert result.changed is True
    assert geo_package_store.has(
        tests.helpers.factories.peri_scribe.sources.snapshots.snapshot_path(),
    )


def test_fetch_all_feeds_reindexes_after_successful_fetch(
    monkeypatch: pytest.MonkeyPatch,
    feature_set_with_geometry: arcgis.features.FeatureSet,
    fetch_all_feeds_stubs: typing.Callable[..., None],
    geo_package_store: (
        tests.helpers.doubles.peri_scribe.snapshot_storage.GeoPackageStore
    ),
) -> None:
    fetch_all_feeds_stubs(
        [tests.helpers.doubles.peri_scribe.sources.fetching.sample_feed_stub()],
        lambda url, gis: tests.helpers.doubles.arcgis.FeatureLayerStub(
            url,
            gis,
            feature_set_with_geometry,
        ),
    )
    indexed: list[pathlib.Path] = []
    monkeypatch.setattr(peri_scribe.fires.index, "index_fire_sources", indexed.append)
    result = peri_scribe.sources.fetching.fetch_all_feeds(
        tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY,
        year=2026,
    )
    assert result.changed is True
    assert indexed == [
        tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY
        / "data"
        / "2026",
    ]


def test_fetch_all_feeds_reindexes_after_a_feed_fails(
    monkeypatch: pytest.MonkeyPatch,
    feature_set_with_geometry: arcgis.features.FeatureSet,
    fetch_all_feeds_stubs: typing.Callable[..., None],
    geo_package_store: (
        tests.helpers.doubles.peri_scribe.snapshot_storage.GeoPackageStore
    ),
) -> None:
    failing = tests.helpers.doubles.peri_scribe.sources.fetching.FeedStub(
        name="Failing_0",
        url="https://example.test/failing",
        last_edit_timestamp=tests.helpers.factories.peri_scribe.sources.snapshots.SAMPLE_LAST_EDIT_TIMESTAMP,
    )
    working = tests.helpers.doubles.peri_scribe.sources.fetching.FeedStub(
        name="Working_0",
        url="https://example.test/working",
        last_edit_timestamp=tests.helpers.factories.peri_scribe.sources.snapshots.SAMPLE_LAST_EDIT_TIMESTAMP,
    )

    layer_factory = (
        tests.helpers.doubles.peri_scribe.sources.fetching
    ).make_failing_feed_layer_factory(
        failing=failing,
        feature_set_with_geometry=feature_set_with_geometry,
    )

    fetch_all_feeds_stubs([failing, working], layer_factory)
    indexed: list[pathlib.Path] = []
    monkeypatch.setattr(peri_scribe.fires.index, "index_fire_sources", indexed.append)
    with pytest.raises(SystemExit, match=f"Failed to fetch {failing.name}: boom"):
        peri_scribe.sources.fetching.fetch_all_feeds(
            tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY,
            year=2026,
        )
    assert indexed == [
        tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY
        / "data"
        / "2026",
    ]
    assert geo_package_store.has(
        tests.helpers.factories.peri_scribe.sources.snapshots.snapshot_path(
            feed_name=working.name,
        ),
    )
    assert not geo_package_store.has(
        tests.helpers.factories.peri_scribe.sources.snapshots.snapshot_path(
            feed_name=failing.name,
        ),
    )


def test_fetch_all_feeds_does_not_reindex_when_no_feed_succeeds(
    monkeypatch: pytest.MonkeyPatch,
    fetch_all_feeds_stubs: typing.Callable[..., None],
) -> None:
    fetch_all_feeds_stubs(
        [tests.helpers.doubles.peri_scribe.sources.fetching.sample_feed_stub()],
        lambda url, gis: tests.helpers.doubles.arcgis.FeatureLayerStub(
            url,
            gis,
            arcgis.features.FeatureSet([]),
            query_error=RuntimeError("boom"),
        ),
    )
    indexed: list[pathlib.Path] = []
    monkeypatch.setattr(peri_scribe.fires.index, "index_fire_sources", indexed.append)
    with pytest.raises(SystemExit, match="Failed to fetch"):
        peri_scribe.sources.fetching.fetch_all_feeds(
            tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY,
            year=2026,
        )
    assert indexed == []


def test_fetch_all_feeds_defaults_to_working_directory_and_year(
    monkeypatch: pytest.MonkeyPatch,
    feature_set_with_geometry: arcgis.features.FeatureSet,
    fetch_all_feeds_stubs: typing.Callable[..., None],
    geo_package_store: (
        tests.helpers.doubles.peri_scribe.snapshot_storage.GeoPackageStore
    ),
) -> None:
    monkeypatch.setattr(
        pathlib.Path,
        "cwd",
        staticmethod(
            lambda: (
                tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY
            ),
        ),
    )
    fetch_all_feeds_stubs(
        [tests.helpers.doubles.peri_scribe.sources.fetching.sample_feed_stub()],
        lambda url, gis: tests.helpers.doubles.arcgis.FeatureLayerStub(
            url,
            gis,
            feature_set_with_geometry,
        ),
    )
    result = peri_scribe.sources.fetching.fetch_all_feeds()
    assert result.changed is True
    year = datetime.date.today().year
    output_path = peri_scribe.sources.snapshots.source_geopackage_path(
        tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY,
        year,
        tests.helpers.factories.peri_scribe.sources.feed_types.SAMPLE_FEED_NAME,
        peri_scribe.sources.snapshots.SourceFile(
            serial_number=0,
            last_edit_timestamp=tests.helpers.factories.peri_scribe.sources.snapshots.SAMPLE_LAST_EDIT_TIMESTAMP,
        ),
    )
    assert geo_package_store.has(output_path)


def test_fetch_can_defer_index_without_losing_snapshot_or_current_state(
    monkeypatch: pytest.MonkeyPatch,
    feature_set_with_geometry: arcgis.features.FeatureSet,
    fetch_all_feeds_stubs: typing.Callable[..., None],
    geo_package_store: (
        tests.helpers.doubles.peri_scribe.snapshot_storage.GeoPackageStore
    ),
) -> None:
    fetch_all_feeds_stubs(
        [tests.helpers.doubles.peri_scribe.sources.fetching.sample_feed_stub()],
        lambda url, gis: tests.helpers.doubles.arcgis.FeatureLayerStub(
            url,
            gis,
            feature_set_with_geometry,
        ),
    )
    indexed: list[pathlib.Path] = []
    monkeypatch.setattr(peri_scribe.fires.index, "index_fire_sources", indexed.append)
    result = peri_scribe.sources.fetching.fetch_all_feeds(
        tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY,
        year=2026,
        build_index=False,
    )
    assert result.changed
    assert geo_package_store.has(
        tests.helpers.factories.peri_scribe.sources.snapshots.snapshot_path(),
    )
    state_path = peri_scribe.sources.snapshots.current_state_path(
        peri_scribe.sources.snapshots.source_directory_path(
            tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY,
            2026,
            tests.helpers.factories.peri_scribe.sources.feed_types.SAMPLE_FEED_NAME,
        ),
        0,
    )
    assert geo_package_store.has(state_path)
    assert list(
        geo_package_store.layer(
            state_path,
            tests.helpers.factories.peri_scribe.sources.feed_types.SAMPLE_FEED_NAME,
        )["name"],
    ) == [
        "a",
        "b",
    ]
    assert indexed == []


@pytest.mark.parametrize(
    ("rows", "expected_identifier", "expected_name", "expected_coordinates"),
    [
        ([(1, "stored", 0.0, 0.0), (2, "new", 2.0, 3.0)], 2, "new", (2.0, 3.0)),
        ([(1, "edited", 0.0, 0.0)], 1, "edited", (0.0, 0.0)),
        ([(1, "stored", 1.0, 2.0)], 1, "stored", (1.0, 2.0)),
    ],
)
def test_fetch_feed_dataframe_full_returns_new_or_changed_features(
    full_fetch: typing.Callable[
        [list[tuple[int, str, float, float]]],
        geopandas.GeoDataFrame | None,
    ],
    rows: list[tuple[int, str, float, float]],
    expected_identifier: int,
    expected_name: str,
    expected_coordinates: tuple[float, float],
) -> None:
    result = full_fetch(rows)
    assert result is not None
    assert list(zip(result["OBJECTID"], result["name"], strict=True)) == [
        (expected_identifier, expected_name),
    ]
    assert result.geometry.iloc[0].equals(shapely.Point(expected_coordinates))


def test_fetch_feed_dataframe_full_returns_none_for_unchanged_features(
    full_fetch: typing.Callable[
        [list[tuple[int, str, float, float]]],
        geopandas.GeoDataFrame | None,
    ],
) -> None:
    assert full_fetch([(1, "stored", 0.0, 0.0)]) is None
