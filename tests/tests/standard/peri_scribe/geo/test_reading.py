"""Tests for peri_scribe.geo.package."""

from __future__ import annotations

import os
import pathlib
import sqlite3

import geopandas
import pytest
import shapely.geometry

import peri_scribe.geo.database
import peri_scribe.geo.package
import peri_scribe.geo.reading
import peri_scribe.sources.feed_types
import peri_scribe.sources.snapshots
import tests.helpers.doubles.peri_scribe.geo.package
import tests.helpers.doubles.peri_scribe.geo.reading
import tests.helpers.factories.geography
import tests.helpers.factories.peri_scribe.geo.package
import tests.helpers.factories.peri_scribe.geo.reading
import tests.helpers.factories.peri_scribe.sources.feed_types
import tests.helpers.peri_scribe.geo.package


def test_read_layer_reads_named_layer(monkeypatch: pytest.MonkeyPatch) -> None:
    frame = tests.helpers.factories.geography.geo_frame(
        {"fire_name": ["Bug"]},
        [shapely.geometry.Point(0, 0)],
    )
    calls: list[tuple[pathlib.Path, str]] = []

    read_file = (
        tests.helpers.doubles.peri_scribe.geo.reading.make_recording_layer_reader(
            calls=calls,
            frame=frame,
        )
    )

    monkeypatch.setattr(peri_scribe.geo.package.geopandas, "read_file", read_file)
    path = pathlib.Path("/derived/full.gpkg")
    assert peri_scribe.geo.reading.read_layer(path, "perimeter_history") is frame
    assert calls == [(path, "perimeter_history")]


def test_read_layer_chunks_yields_bounded_chunks(tmp_path: pathlib.Path) -> None:
    dataframe = tests.helpers.factories.geography.geo_frame(
        {"a": [1, 2, 3, 4, 5]},
        [shapely.geometry.Point(index, 0) for index in range(5)],
    )
    path = tmp_path / "layer.gpkg"
    dataframe.to_file(path, layer="features")

    chunks = list(
        peri_scribe.geo.reading.read_layer_chunks(path, "features", chunk_size=2),
    )

    assert [len(chunk) for chunk in chunks] == [2, 2, 1]
    assert [chunk.iloc[0]["a"] for chunk in chunks] == [1, 3, 5]


def test_read_layer_chunks_limits_rows_when_feature_ids_have_gaps(
    tmp_path: pathlib.Path,
) -> None:
    path = tmp_path / "layer.gpkg"
    tests.helpers.factories.peri_scribe.geo.reading.write_sparse_layer(path, [1, 3, 4])
    chunks = list(peri_scribe.geo.reading.read_layer_chunks(path, "features", 2))
    assert [chunk["value"].tolist() for chunk in chunks] == [[1, 3], [4]]


def test_read_layer_chunks_reads_default_layer_without_name(
    tmp_path: pathlib.Path,
) -> None:
    dataframe = tests.helpers.factories.geography.geo_frame(
        {"a": [1, 2, 3]},
        [shapely.geometry.Point(index, 0) for index in range(3)],
    )
    path = tmp_path / "layer.gpkg"
    dataframe.to_file(path, layer="features")

    chunks = list(peri_scribe.geo.reading.read_layer_chunks(path, None, chunk_size=2))

    assert [len(chunk) for chunk in chunks] == [2, 1]


def test_read_layer_chunks_yields_nothing_for_empty_layer(
    tmp_path: pathlib.Path,
) -> None:
    dataframe = geopandas.GeoDataFrame(geometry=[], crs="EPSG:4326")
    path = tmp_path / "layer.gpkg"
    dataframe.to_file(path, layer="features")

    chunks = list(
        peri_scribe.geo.reading.read_layer_chunks(path, "features", chunk_size=2),
    )

    assert chunks == []


def test_read_layer_dataframe_reads_feed_layer(
    monkeypatch: pytest.MonkeyPatch,
    feed: peri_scribe.sources.feed_types.Feed,
) -> None:
    sentinel = object()
    calls: list[tuple[pathlib.Path, str]] = []
    monkeypatch.setattr(
        peri_scribe.geo.package.geopandas,
        "read_file",
        lambda path, layer: calls.append((path, layer)) or sentinel,
    )
    path = pathlib.Path("/fires.gpkg")
    assert peri_scribe.geo.reading.read_layer_dataframe(path, feed) is sentinel
    assert calls == [
        (path, tests.helpers.factories.peri_scribe.sources.feed_types.SAMPLE_FEED_NAME),
    ]


def test_read_geopackage_cached_writes_and_reuses_cache(
    tmp_path: pathlib.Path,
    configured_feeds: list[peri_scribe.sources.feed_types.Feed],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    feed = configured_feeds[0]
    path = tests.helpers.factories.peri_scribe.geo.package.write_cache_snapshot(
        tmp_path,
        feed,
        [("Park Fire", "Active")],
    )
    contents = peri_scribe.geo.reading.read_geopackage_cached(path)
    assert [row.record.name for row in contents.rows] == ["Park Fire"]
    assert tests.helpers.peri_scribe.geo.package.record_cache_database_path(
        path,
    ).is_file()
    # A second read must come from the cache, not from the GeoPackage.
    monkeypatch.setattr(
        peri_scribe.geo.package,
        "read_geopackage",
        lambda _path: pytest.fail("read_geopackage should not be called"),
    )
    again = peri_scribe.geo.reading.read_geopackage_cached(path)
    assert [row.record.name for row in again.rows] == ["Park Fire"]


def test_read_geopackage_cached_rebuilds_when_snapshot_changes(
    tmp_path: pathlib.Path,
    configured_feeds: list[peri_scribe.sources.feed_types.Feed],
) -> None:
    feed = configured_feeds[0]
    path = tests.helpers.factories.peri_scribe.geo.package.write_cache_snapshot(
        tmp_path,
        feed,
        [("Park Fire", "Active")],
    )
    peri_scribe.geo.reading.read_geopackage_cached(path)
    tests.helpers.factories.peri_scribe.geo.package.write_cache_snapshot(
        tmp_path,
        feed,
        [("ALTA", "Inactive")],
    )
    # Give the rewritten snapshot a deterministically different modification time.
    os.utime(path, ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000))
    contents = peri_scribe.geo.reading.read_geopackage_cached(path)
    assert [row.record.name for row in contents.rows] == ["ALTA"]


def test_read_geopackage_cached_rebuilds_corrupt_database(
    tmp_path: pathlib.Path,
    configured_feeds: list[peri_scribe.sources.feed_types.Feed],
) -> None:
    feed = configured_feeds[0]
    path = tests.helpers.factories.peri_scribe.geo.package.write_cache_snapshot(
        tmp_path,
        feed,
        [("Park Fire", "Active")],
    )
    peri_scribe.geo.reading.read_geopackage_cached(path)
    tests.helpers.peri_scribe.geo.package.record_cache_database_path(path).write_bytes(
        b"not a database",
    )
    # Change the snapshot's bucket directory so the in-process freshness memo
    # re-verifies and the corrupt database is rebuilt.
    os.utime(path.parent, ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000))
    contents = peri_scribe.geo.reading.read_geopackage_cached(path)
    assert [row.record.name for row in contents.rows] == ["Park Fire"]


@pytest.mark.parametrize("version", [1, 999])
def test_read_geopackage_cached_rebuilds_outdated_schema(
    tmp_path: pathlib.Path,
    configured_feeds: list[peri_scribe.sources.feed_types.Feed],
    version: int,
) -> None:
    feed = configured_feeds[0]
    path = tests.helpers.factories.peri_scribe.geo.package.write_cache_snapshot(
        tmp_path,
        feed,
        [("Park Fire", "Active")],
    )
    peri_scribe.geo.reading.read_geopackage_cached(path)
    conn = sqlite3.connect(
        tests.helpers.peri_scribe.geo.package.record_cache_database_path(path),
    )
    conn.execute(f"PRAGMA user_version = {version}")
    conn.commit()
    conn.close()
    # Change the snapshot's bucket directory so the in-process freshness memo
    # re-verifies and the outdated database is rebuilt.
    os.utime(path.parent, ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000))
    again = peri_scribe.geo.reading.read_geopackage_cached(path)
    assert [row.record.name for row in again.rows] == ["Park Fire"]


def test_read_geopackage_cached_reads_when_snapshot_directory_unreadable(
    tmp_path: pathlib.Path,
    configured_feeds: list[peri_scribe.sources.feed_types.Feed],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    feed = configured_feeds[0]
    path = tests.helpers.factories.peri_scribe.geo.package.write_cache_snapshot(
        tmp_path,
        feed,
        [("Park Fire", "Active")],
    )
    source_directory = path.parent.parent
    original_stat = pathlib.Path.stat

    failing_stat = (
        tests.helpers.doubles.peri_scribe.geo.package
    ).make_source_directory_stat_failure(
        source_directory=source_directory,
        original_stat=original_stat,
    )

    monkeypatch.setattr(pathlib.Path, "stat", failing_stat)
    contents = peri_scribe.geo.reading.read_geopackage_cached(path)
    assert [row.record.name for row in contents.rows] == ["Park Fire"]


def test_read_geopackage_cached_ignores_non_directory_entries(
    tmp_path: pathlib.Path,
    configured_feeds: list[peri_scribe.sources.feed_types.Feed],
) -> None:
    feed = configured_feeds[0]
    path = tests.helpers.factories.peri_scribe.geo.package.write_cache_snapshot(
        tmp_path,
        feed,
        [("Park Fire", "Active")],
    )
    (path.parent.parent / "stray.txt").write_text("not a snapshot")
    contents = peri_scribe.geo.reading.read_geopackage_cached(path)
    assert [row.record.name for row in contents.rows] == ["Park Fire"]


def test_read_geopackage_cached_ignores_unreadable_bucket_directory(
    tmp_path: pathlib.Path,
    configured_feeds: list[peri_scribe.sources.feed_types.Feed],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    feed = configured_feeds[0]
    path = tests.helpers.factories.peri_scribe.geo.package.write_cache_snapshot(
        tmp_path,
        feed,
        [("Park Fire", "Active")],
    )
    bucket_directory = path.parent
    original_stat = pathlib.Path.stat

    failing_stat = (
        tests.helpers.doubles.peri_scribe.geo.package
    ).make_bucket_directory_stat_failure(
        bucket_directory=bucket_directory,
        original_stat=original_stat,
    )

    monkeypatch.setattr(pathlib.Path, "stat", failing_stat)
    contents = peri_scribe.geo.reading.read_geopackage_cached(path)
    assert [row.record.name for row in contents.rows] == ["Park Fire"]


def test_read_geopackage_cached_falls_back_when_database_unusable(
    tmp_path: pathlib.Path,
    configured_feeds: list[peri_scribe.sources.feed_types.Feed],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    feed = configured_feeds[0]
    path = tests.helpers.factories.peri_scribe.geo.package.write_cache_snapshot(
        tmp_path,
        feed,
        [("Park Fire", "Active")],
    )

    failing_sync = (
        tests.helpers.doubles.peri_scribe.geo.package.fail_cache_synchronization
    )

    monkeypatch.setattr(peri_scribe.geo.database, "open_and_sync", failing_sync)
    contents = peri_scribe.geo.reading.read_geopackage_cached(path)
    assert [row.record.name for row in contents.rows] == ["Park Fire"]


def test_read_geopackage_cached_reads_without_cache_when_stat_fails(
    tmp_path: pathlib.Path,
    configured_feeds: list[peri_scribe.sources.feed_types.Feed],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    feed = configured_feeds[0]
    path = tests.helpers.factories.peri_scribe.geo.package.write_cache_snapshot(
        tmp_path,
        feed,
        [("Park Fire", "Active")],
    )
    original_stat = pathlib.Path.stat

    failing_stat = (
        tests.helpers.doubles.peri_scribe.geo.package.make_snapshot_stat_failure(
            path=path,
            original_stat=original_stat,
        )
    )

    monkeypatch.setattr(pathlib.Path, "stat", failing_stat)
    contents = peri_scribe.geo.reading.read_geopackage_cached(path)
    assert [row.record.name for row in contents.rows] == ["Park Fire"]


def test_read_geopackage_cached_stores_new_snapshots_incrementally(
    tmp_path: pathlib.Path,
    configured_feeds: list[peri_scribe.sources.feed_types.Feed],
) -> None:
    feed = configured_feeds[0]
    first = tests.helpers.factories.peri_scribe.geo.package.write_cache_snapshot(
        tmp_path,
        feed,
        [("Park Fire", "Active")],
    )
    peri_scribe.geo.reading.read_geopackage_cached(first)
    second = tests.helpers.factories.peri_scribe.geo.package.write_cache_snapshot(
        tmp_path,
        feed,
        [("ALTA", "Inactive")],
        serial_number=1,
    )
    contents = peri_scribe.geo.reading.read_geopackage_cached(second)
    assert [row.record.name for row in contents.rows] == ["ALTA"]
    again = peri_scribe.geo.reading.read_geopackage_cached(first)
    assert [row.record.name for row in again.rows] == ["Park Fire"]
    conn = sqlite3.connect(
        tests.helpers.peri_scribe.geo.package.record_cache_database_path(first),
    )
    try:
        serials = [
            row[0]
            for row in conn.execute("SELECT serial FROM snapshots ORDER BY serial")
        ]
    finally:
        conn.close()
    assert serials == [0, 1]


def test_read_geopackage_cached_drops_rows_for_missing_snapshots(
    tmp_path: pathlib.Path,
    configured_feeds: list[peri_scribe.sources.feed_types.Feed],
) -> None:
    feed = configured_feeds[0]
    first = tests.helpers.factories.peri_scribe.geo.package.write_cache_snapshot(
        tmp_path,
        feed,
        [("Park Fire", "Active")],
    )
    second = tests.helpers.factories.peri_scribe.geo.package.write_cache_snapshot(
        tmp_path,
        feed,
        [("ALTA", "Inactive")],
        serial_number=1,
    )
    peri_scribe.geo.reading.read_geopackage_cached(first)
    peri_scribe.geo.reading.read_geopackage_cached(second)
    first.unlink()
    peri_scribe.geo.reading.read_geopackage_cached(second)
    conn = sqlite3.connect(
        tests.helpers.peri_scribe.geo.package.record_cache_database_path(second),
    )
    try:
        serials = [
            row[0]
            for row in conn.execute("SELECT serial FROM snapshots ORDER BY serial")
        ]
    finally:
        conn.close()
    assert serials == [1]


def test_read_geopackage_cached_falls_back_when_read_fails(
    tmp_path: pathlib.Path,
    configured_feeds: list[peri_scribe.sources.feed_types.Feed],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    feed = configured_feeds[0]
    path = tests.helpers.factories.peri_scribe.geo.package.write_cache_snapshot(
        tmp_path,
        feed,
        [("Park Fire", "Active")],
    )
    peri_scribe.geo.reading.read_geopackage_cached(path)

    failing_read = tests.helpers.doubles.peri_scribe.geo.package.fail_cache_read

    monkeypatch.setattr(peri_scribe.geo.reading, "read_snapshot_contents", failing_read)
    contents = peri_scribe.geo.reading.read_geopackage_cached(path)
    assert [row.record.name for row in contents.rows] == ["Park Fire"]


def test_read_geopackage_cached_skips_snapshot_that_cannot_be_checked(
    tmp_path: pathlib.Path,
    configured_feeds: list[peri_scribe.sources.feed_types.Feed],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    feed = configured_feeds[0]
    path = tests.helpers.factories.peri_scribe.geo.package.write_cache_snapshot(
        tmp_path,
        feed,
        [("Park Fire", "Active")],
    )
    original = peri_scribe.sources.snapshots.existing_source_files

    phantom_files = (
        tests.helpers.doubles.peri_scribe.geo.package.make_phantom_snapshot_listing(
            original=original,
        )
    )

    monkeypatch.setattr(
        peri_scribe.sources.snapshots,
        "existing_source_files",
        phantom_files,
    )
    contents = peri_scribe.geo.reading.read_geopackage_cached(path)
    assert [row.record.name for row in contents.rows] == ["Park Fire"]
    conn = sqlite3.connect(
        tests.helpers.peri_scribe.geo.package.record_cache_database_path(path),
    )
    try:
        serials = [
            row[0]
            for row in conn.execute("SELECT serial FROM snapshots ORDER BY serial")
        ]
    finally:
        conn.close()
    assert serials == [0]


def test_read_geopackage_cached_reads_directly_when_snapshot_not_stored(
    tmp_path: pathlib.Path,
    configured_feeds: list[peri_scribe.sources.feed_types.Feed],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    feed = configured_feeds[0]
    first = tests.helpers.factories.peri_scribe.geo.package.write_cache_snapshot(
        tmp_path,
        feed,
        [("Park Fire", "Active")],
    )
    peri_scribe.geo.reading.read_geopackage_cached(first)
    second = tests.helpers.factories.peri_scribe.geo.package.write_cache_snapshot(
        tmp_path,
        feed,
        [("ALTA", "Inactive")],
        serial_number=1,
    )
    monkeypatch.setattr(
        peri_scribe.geo.database,
        "sync_database",
        lambda *_args, **_kwargs: None,
    )
    contents = peri_scribe.geo.reading.read_geopackage_cached(second)
    assert [row.record.name for row in contents.rows] == ["ALTA"]
