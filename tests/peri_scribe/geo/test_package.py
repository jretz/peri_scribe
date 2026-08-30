"""Tests for peri_scribe.geo.package."""

from __future__ import annotations

import datetime
import os
import pathlib
import re
import sqlite3
import typing

import geopandas
import pandas as pd
import pyproj
import pytest
import shapely
import shapely.geometry

import peri_scribe.exceptions
import peri_scribe.geo.database
import peri_scribe.geo.package
import peri_scribe.geo.reading
import peri_scribe.models
import peri_scribe.output
import peri_scribe.sources.feed_types
import peri_scribe.sources.snapshots
import tests.peri_scribe.geo.geo_helpers


def stub_single_layer(
    stub_geo_package: typing.Callable[
        [pd.DataFrame, dict[str, pd.DataFrame]],
        None,
    ],
    layer_name: str,
    geometry_type: str,
    dataframe: pd.DataFrame,
) -> None:
    """Point the GeoPackage reader at a single layer.

    Args:
        stub_geo_package: The fixture installing in-memory GeoPackage reads.
        layer_name: The layer's name, matching a configured feed.
        geometry_type: The layer's reported geometry type.
        dataframe: The layer's rows.
    """
    stub_geo_package(
        pd.DataFrame({"name": [layer_name], "geometry_type": [geometry_type]}),
        {layer_name: dataframe},
    )


def wgs84_dataframe(
    columns: dict[str, list[object]],
    geometry: list[shapely.Geometry | None] | None = None,
) -> geopandas.GeoDataFrame:
    """Build an unprojected GeoDataFrame with the given columns.

    Args:
        columns: The attribute columns.
        geometry: The feature geometries; defaults to two WGS84 points.

    Returns:
        The GeoDataFrame, without an explicit CRS.
    """
    if geometry is None:
        geometry = [
            shapely.geometry.Point(0, 0),
            shapely.geometry.Point(1, 1),
        ]
    return geopandas.GeoDataFrame(columns, geometry=geometry)


def test_read_geopackage_reads_records_from_every_layer(
    configured_feeds: list[peri_scribe.sources.feed_types.Feed],
    stub_geo_package: typing.Callable[[pd.DataFrame, dict[str, pd.DataFrame]], None],
) -> None:
    stub_geo_package(
        pd.DataFrame({
            "name": ["Fires_One_0", "Fires_Two_0"],
            "geometry_type": ["Polygon", "Point"],
        }),
        {
            "Fires_One_0": geopandas.GeoDataFrame(
                {
                    "incident_name": ["Park Fire", "ALTA"],
                    "displayStatus": ["Active", "Inactive"],
                },
                geometry=[
                    shapely.geometry.Point(0, 0),
                    shapely.geometry.Point(1, 1),
                ],
            ),
            "Fires_Two_0": geopandas.GeoDataFrame(
                {
                    "IncidentName": ["Creek Fire"],
                    "ActiveFireCandidate": [1],
                },
                geometry=[shapely.geometry.Point(2, 2)],
            ),
        },
    )
    contents = peri_scribe.geo.package.read_geopackage(pathlib.Path("fires.gpkg"))
    records = [row.record for row in contents.rows]
    assert [record.name for record in records] == [
        "Park Fire",
        "ALTA",
        "Creek Fire",
    ]
    assert [record.status for record in records] == [
        tests.peri_scribe.geo.geo_helpers.ACTIVE,
        tests.peri_scribe.geo.geo_helpers.INACTIVE,
        tests.peri_scribe.geo.geo_helpers.ACTIVE,
    ]
    assert [record.names for record in records] == [
        frozenset({"park fire"}),
        frozenset({"alta"}),
        frozenset({"creek fire"}),
    ]


def test_read_geopackage_omits_rows_without_status(
    configured_feeds: list[peri_scribe.sources.feed_types.Feed],
    stub_geo_package: typing.Callable[[pd.DataFrame, dict[str, pd.DataFrame]], None],
) -> None:
    stub_single_layer(
        stub_geo_package,
        "Fires_One_0",
        "Polygon",
        wgs84_dataframe({
            "incident_name": ["Park Fire", "ALTA"],
            "displayStatus": ["Active", None],
        }),
    )
    contents = peri_scribe.geo.package.read_geopackage(pathlib.Path("fires.gpkg"))
    assert [row.record.name for row in contents.rows] == [
        "Park Fire",
    ]


def test_read_geopackage_names_blank_rows_from_mission(
    configured_feeds_with_mission: list[peri_scribe.sources.feed_types.Feed],
    stub_geo_package: typing.Callable[[pd.DataFrame, dict[str, pd.DataFrame]], None],
) -> None:
    stub_single_layer(
        stub_geo_package,
        "Fires_One_0",
        "Polygon",
        wgs84_dataframe({
            "incident_name": [None, "Woodside"],
            "displayStatus": ["Active", "Active"],
            "incident_number": [None, None],
            "mission": ["CA-HUU-WOODS-N40Y", "WOODSIDE"],
            "poly_DateCurrent": [None, None],
        }),
    )
    contents = peri_scribe.geo.package.read_geopackage(pathlib.Path("fires.gpkg"))
    assert [row.record.name for row in contents.rows] == ["WOODS", "Woodside"]


def test_read_geopackage_omits_rows_with_no_name_at_all(
    configured_feeds: list[peri_scribe.sources.feed_types.Feed],
    stub_geo_package: typing.Callable[[pd.DataFrame, dict[str, pd.DataFrame]], None],
) -> None:
    stub_single_layer(
        stub_geo_package,
        "Fires_One_0",
        "Polygon",
        wgs84_dataframe(
            {
                "incident_name": [None],
                "displayStatus": ["Active"],
            },
            geometry=[shapely.geometry.Point(0, 0)],
        ),
    )
    contents = peri_scribe.geo.package.read_geopackage(pathlib.Path("fires.gpkg"))
    assert contents.rows == ()


def test_read_geopackage_raises_for_layer_without_configured_feed(
    configured_feeds: list[peri_scribe.sources.feed_types.Feed],
    stub_geo_package: typing.Callable[[pd.DataFrame, dict[str, pd.DataFrame]], None],
) -> None:
    stub_geo_package(
        pd.DataFrame({
            "name": ["Fires_One_0", "Mystery_Layer_0"],
            "geometry_type": ["Polygon", "Point"],
        }),
        {
            "Fires_One_0": geopandas.GeoDataFrame(
                {
                    "incident_name": ["Park Fire"],
                    "displayStatus": ["Active"],
                },
                geometry=[shapely.geometry.Point(0, 0)],
            ),
        },
    )
    with pytest.raises(
        peri_scribe.exceptions.UnknownLayerError,
        match=re.escape("layer Mystery_Layer_0 in fires.gpkg"),
    ):
        peri_scribe.geo.package.read_geopackage(pathlib.Path("fires.gpkg"))


def test_read_geopackage_reads_normalized_identifiers(
    configured_feeds_with_identifiers: list[peri_scribe.sources.feed_types.Feed],
    stub_geo_package: typing.Callable[[pd.DataFrame, dict[str, pd.DataFrame]], None],
) -> None:
    stub_single_layer(
        stub_geo_package,
        "Fires_One_0",
        "Polygon",
        wgs84_dataframe({
            "incident_name": ["Bug", "BUG"],
            "displayStatus": ["Active", "Inactive"],
            "incident_number": [
                "{E3094E35-8B33-4A82-BE4B-D2E83652C29F}",
                None,
            ],
        }),
    )
    contents = peri_scribe.geo.package.read_geopackage(pathlib.Path("fires.gpkg"))
    assert [row.record.identifiers for row in contents.rows] == [
        frozenset({"e3094e35-8b33-4a82-be4b-d2e83652c29f"}),
        frozenset(),
    ]


def test_read_geopackage_reads_geometry_and_observation_time(
    configured_feeds_with_mission: list[peri_scribe.sources.feed_types.Feed],
    stub_geo_package: typing.Callable[[pd.DataFrame, dict[str, pd.DataFrame]], None],
) -> None:
    stub_single_layer(
        stub_geo_package,
        "Fires_One_0",
        "Polygon",
        wgs84_dataframe(
            {
                "incident_name": ["Bug"],
                "displayStatus": ["Active"],
                "incident_number": [None],
                "mission": [None],
                "poly_DateCurrent": [datetime.datetime(2026, 8, 9, 1, 28, 25)],
            },
            geometry=[shapely.geometry.Point(0, 0)],
        ),
    )
    contents = peri_scribe.geo.package.read_geopackage(pathlib.Path("fires.gpkg"))
    record = contents.rows[0].record
    assert record.geometry == shapely.geometry.Point(0, 0)
    assert record.observed_at == datetime.datetime(
        2026,
        8,
        9,
        1,
        28,
        25,
        tzinfo=datetime.UTC,
    )


def test_read_geopackage_reads_mission_and_point_of_origin(
    configured_feeds_with_point_of_origin: list[peri_scribe.sources.feed_types.Feed],
    stub_geo_package: typing.Callable[[pd.DataFrame, dict[str, pd.DataFrame]], None],
) -> None:
    stub_single_layer(
        stub_geo_package,
        "Fires_Two_0",
        "Point",
        wgs84_dataframe(
            {
                "IncidentName": ["Bug"],
                "ActiveFireCandidate": ["Active"],
                "IrwinID": ["2026-nvccd-030683"],
                "mission": ["2026-NVCCD-030683"],
                "POOState": ["US-CA"],
                "POOFips": ["06035"],
            },
            geometry=[shapely.geometry.Point(0, 0)],
        ),
    )
    contents = peri_scribe.geo.package.read_geopackage(pathlib.Path("fires.gpkg"))
    record = contents.rows[0].record
    assert record.mission == "2026-NVCCD-030683"
    assert record.point_of_origin_state == "US-CA"
    assert record.point_of_origin_fips == "06035"


def test_read_geopackage_reads_complex_memberships(
    configured_feeds_with_identifiers: list[peri_scribe.sources.feed_types.Feed],
    stub_geo_package: typing.Callable[[pd.DataFrame, dict[str, pd.DataFrame]], None],
) -> None:
    stub_single_layer(
        stub_geo_package,
        "Fires_Two_0",
        "Point",
        wgs84_dataframe({
            "IncidentName": ["0445 CROSSWHITE", "ROWE CREEK COMPLEX"],
            "ActiveFireCandidate": [1, 1],
            "IrwinID": [
                "{1B0219EE-5298-4FEF-9927-C2666D9D53FC}",
                "{B8431C26-6A9B-4EF0-88D8-F7EA9A3F56C3}",
            ],
            "CpxID": ["{B8431C26-6A9B-4EF0-88D8-F7EA9A3F56C3}", None],
            "CpxName": ["ROWE CREEK COMPLEX", None],
            "IsCpxChild": [1, 0],
        }),
    )
    contents = peri_scribe.geo.package.read_geopackage(pathlib.Path("fires.gpkg"))
    assert contents.memberships == (
        peri_scribe.models.ComplexMembership(
            fire_identifier="1b0219ee-5298-4fef-9927-c2666d9d53fc",
            complex_identifier="b8431c26-6a9b-4ef0-88d8-f7ea9a3f56c3",
            complex_name="ROWE CREEK COMPLEX",
        ),
    )


def test_read_geopackage_reads_no_memberships_without_complex_columns(
    configured_feeds_with_identifiers: list[peri_scribe.sources.feed_types.Feed],
    stub_geo_package: typing.Callable[[pd.DataFrame, dict[str, pd.DataFrame]], None],
) -> None:
    stub_single_layer(
        stub_geo_package,
        "Fires_One_0",
        "Polygon",
        wgs84_dataframe(
            {
                "incident_name": ["Bug"],
                "displayStatus": ["Active"],
                "incident_number": ["some-id"],
            },
            geometry=[shapely.geometry.Point(0, 0)],
        ),
    )
    contents = peri_scribe.geo.package.read_geopackage(pathlib.Path("fires.gpkg"))
    assert contents.memberships == ()


def test_read_geopackage_skips_rows_not_marked_as_complex_children(
    configured_feeds_with_identifiers: list[peri_scribe.sources.feed_types.Feed],
    stub_geo_package: typing.Callable[[pd.DataFrame, dict[str, pd.DataFrame]], None],
) -> None:
    stub_single_layer(
        stub_geo_package,
        "Fires_Two_0",
        "Point",
        wgs84_dataframe(
            {
                "IncidentName": ["Creek Fire"],
                "ActiveFireCandidate": [1],
                "IrwinID": ["some-id"],
                "CpxID": ["{B8431C26-6A9B-4EF0-88D8-F7EA9A3F56C3}"],
                "CpxName": ["ROWE CREEK COMPLEX"],
                "IsCpxChild": [0],
            },
            geometry=[shapely.geometry.Point(0, 0)],
        ),
    )
    contents = peri_scribe.geo.package.read_geopackage(pathlib.Path("fires.gpkg"))
    assert contents.memberships == ()


def test_read_geopackage_omits_memberships_with_blank_values(
    configured_feeds_with_identifiers: list[peri_scribe.sources.feed_types.Feed],
    stub_geo_package: typing.Callable[[pd.DataFrame, dict[str, pd.DataFrame]], None],
) -> None:
    stub_single_layer(
        stub_geo_package,
        "Fires_Two_0",
        "Point",
        wgs84_dataframe({
            "IncidentName": ["A", "B"],
            "ActiveFireCandidate": [1, 1],
            "IrwinID": ["", "id-b"],
            "CpxID": ["{B8431C26-6A9B-4EF0-88D8-F7EA9A3F56C3}", ""],
            "CpxName": ["", "ROWE CREEK COMPLEX"],
            "IsCpxChild": [1, 1],
        }),
    )
    contents = peri_scribe.geo.package.read_geopackage(pathlib.Path("fires.gpkg"))
    assert contents.memberships == ()


def test_read_geopackage_reads_full_rows(
    configured_feeds: list[peri_scribe.sources.feed_types.Feed],
    stub_geo_package: typing.Callable[[pd.DataFrame, dict[str, pd.DataFrame]], None],
) -> None:
    object_id = 7
    area_in_acres = 12
    stub_geo_package(
        pd.DataFrame({"name": ["Fires_One_0"], "geometry_type": ["Point"]}),
        {
            "Fires_One_0": geopandas.GeoDataFrame(
                {
                    "incident_name": ["Park Fire"],
                    "displayStatus": ["Active"],
                    "OBJECTID": [object_id],
                    "area_acres": [area_in_acres],
                },
                geometry=[shapely.geometry.Point(0, 0)],
            ),
        },
    )
    rows = peri_scribe.geo.package.read_geopackage(pathlib.Path("fires.gpkg")).rows
    assert len(rows) == 1
    assert rows[0].object_id == object_id
    assert rows[0].source_name == "Fires_One_0"
    assert rows[0].record.name == "Park Fire"
    assert rows[0].attributes["area_acres"] == area_in_acres
    assert "geometry" not in rows[0].attributes


def test_read_geopackage_reads_missing_object_id(
    configured_feeds: list[peri_scribe.sources.feed_types.Feed],
    stub_geo_package: typing.Callable[[pd.DataFrame, dict[str, pd.DataFrame]], None],
) -> None:
    stub_geo_package(
        pd.DataFrame({"name": ["Fires_One_0"], "geometry_type": ["Point"]}),
        {
            "Fires_One_0": geopandas.GeoDataFrame(
                {
                    "incident_name": ["Park Fire"],
                    "displayStatus": ["Active"],
                },
                geometry=[shapely.geometry.Point(0, 0)],
            ),
        },
    )
    rows = peri_scribe.geo.package.read_geopackage(pathlib.Path("fires.gpkg")).rows
    assert rows[0].object_id is None


def test_read_geopackage_skips_rows_without_status(
    configured_feeds: list[peri_scribe.sources.feed_types.Feed],
    stub_geo_package: typing.Callable[[pd.DataFrame, dict[str, pd.DataFrame]], None],
) -> None:
    stub_geo_package(
        pd.DataFrame({"name": ["Fires_One_0"], "geometry_type": ["Point"]}),
        {
            "Fires_One_0": geopandas.GeoDataFrame(
                {
                    "incident_name": ["Park Fire", "No Status"],
                    "displayStatus": ["Active", None],
                },
                geometry=[
                    shapely.geometry.Point(0, 0),
                    shapely.geometry.Point(1, 1),
                ],
            ),
        },
    )
    rows = peri_scribe.geo.package.read_geopackage(pathlib.Path("fires.gpkg")).rows
    assert [row.record.name for row in rows] == ["Park Fire"]


def write_cache_snapshot(
    tmp_path: pathlib.Path,
    feed: peri_scribe.sources.feed_types.Feed,
    rows: list[tuple[str, str]],
    *,
    serial_number: int = 0,
) -> pathlib.Path:
    """Write one snapshot GeoPackage for *feed* under a sources-like layout.

    Args:
        tmp_path: The per-test directory holding the sources tree.
        feed: The feed the snapshot's layer belongs to.
        rows: The name and status of each feature.
        serial_number: The snapshot's serial number.

    Returns:
        The snapshot's path.
    """
    path = (
        tmp_path
        / "sources"
        / feed.name
        / "000___"
        / f"{serial_number:06d},lastEdit=0.gpkg"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    peri_scribe.output.write_geopackage(
        path,
        [
            peri_scribe.models.LayerData(
                name=feed.name,
                dataframe=geopandas.GeoDataFrame(
                    {
                        "incident_name": [name for name, _status in rows],
                        "displayStatus": [status for _name, status in rows],
                    },
                    geometry=[shapely.geometry.Point(0, 0) for _row in rows],
                    crs=pyproj.CRS.from_epsg(4326),
                ),
            ),
        ],
    )
    return path


def record_cache_database_path(path: pathlib.Path) -> pathlib.Path:
    """Return the record cache database for the feed holding *path*.

    Args:
        path: A snapshot path under ``sources/{feed}/...``.

    Returns:
        The feed's record cache database path.
    """
    return peri_scribe.sources.snapshots.record_cache_database_path(path.parent.parent)


def test_read_geopackage_cached_writes_and_reuses_cache(
    tmp_path: pathlib.Path,
    configured_feeds: list[peri_scribe.sources.feed_types.Feed],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    feed = configured_feeds[0]
    path = write_cache_snapshot(tmp_path, feed, [("Park Fire", "Active")])
    contents = peri_scribe.geo.reading.read_geopackage_cached(path)
    assert [row.record.name for row in contents.rows] == ["Park Fire"]
    assert record_cache_database_path(path).is_file()
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
    path = write_cache_snapshot(tmp_path, feed, [("Park Fire", "Active")])
    peri_scribe.geo.reading.read_geopackage_cached(path)
    write_cache_snapshot(tmp_path, feed, [("ALTA", "Inactive")])
    # Give the rewritten snapshot a deterministically different modification time.
    os.utime(path, ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000))
    contents = peri_scribe.geo.reading.read_geopackage_cached(path)
    assert [row.record.name for row in contents.rows] == ["ALTA"]


def test_read_geopackage_cached_rebuilds_corrupt_database(
    tmp_path: pathlib.Path,
    configured_feeds: list[peri_scribe.sources.feed_types.Feed],
) -> None:
    feed = configured_feeds[0]
    path = write_cache_snapshot(tmp_path, feed, [("Park Fire", "Active")])
    peri_scribe.geo.reading.read_geopackage_cached(path)
    record_cache_database_path(path).write_bytes(b"not a database")
    # Change the snapshot's bucket directory so the in-process freshness memo
    # re-verifies and the corrupt database is rebuilt.
    os.utime(
        path.parent,
        ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000),
    )
    contents = peri_scribe.geo.reading.read_geopackage_cached(path)
    assert [row.record.name for row in contents.rows] == ["Park Fire"]


def test_read_geopackage_cached_rebuilds_outdated_schema(
    tmp_path: pathlib.Path,
    configured_feeds: list[peri_scribe.sources.feed_types.Feed],
) -> None:
    feed = configured_feeds[0]
    path = write_cache_snapshot(tmp_path, feed, [("Park Fire", "Active")])
    peri_scribe.geo.reading.read_geopackage_cached(path)
    conn = sqlite3.connect(record_cache_database_path(path))
    conn.execute("PRAGMA user_version = 999")
    conn.commit()
    conn.close()
    # Change the snapshot's bucket directory so the in-process freshness memo
    # re-verifies and the outdated database is rebuilt.
    os.utime(
        path.parent,
        ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000),
    )
    again = peri_scribe.geo.reading.read_geopackage_cached(path)
    assert [row.record.name for row in again.rows] == ["Park Fire"]


def test_read_geopackage_cached_reads_when_snapshot_directory_unreadable(
    tmp_path: pathlib.Path,
    configured_feeds: list[peri_scribe.sources.feed_types.Feed],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    feed = configured_feeds[0]
    path = write_cache_snapshot(tmp_path, feed, [("Park Fire", "Active")])
    source_directory = path.parent.parent
    original_stat = pathlib.Path.stat

    def failing_stat(self: pathlib.Path) -> object:
        if self == source_directory:
            message = "no such directory"
            raise OSError(message)
        return original_stat(self)

    monkeypatch.setattr(pathlib.Path, "stat", failing_stat)
    contents = peri_scribe.geo.reading.read_geopackage_cached(path)
    assert [row.record.name for row in contents.rows] == ["Park Fire"]


def test_read_geopackage_cached_ignores_non_directory_entries(
    tmp_path: pathlib.Path,
    configured_feeds: list[peri_scribe.sources.feed_types.Feed],
) -> None:
    feed = configured_feeds[0]
    path = write_cache_snapshot(tmp_path, feed, [("Park Fire", "Active")])
    (path.parent.parent / "stray.txt").write_text("not a snapshot")
    contents = peri_scribe.geo.reading.read_geopackage_cached(path)
    assert [row.record.name for row in contents.rows] == ["Park Fire"]


def test_read_geopackage_cached_ignores_unreadable_bucket_directory(
    tmp_path: pathlib.Path,
    configured_feeds: list[peri_scribe.sources.feed_types.Feed],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    feed = configured_feeds[0]
    path = write_cache_snapshot(tmp_path, feed, [("Park Fire", "Active")])
    bucket_directory = path.parent
    original_stat = pathlib.Path.stat

    def failing_stat(self: pathlib.Path) -> object:
        if self == bucket_directory:
            message = "no such directory"
            raise OSError(message)
        return original_stat(self)

    monkeypatch.setattr(pathlib.Path, "stat", failing_stat)
    contents = peri_scribe.geo.reading.read_geopackage_cached(path)
    assert [row.record.name for row in contents.rows] == ["Park Fire"]


def test_read_geopackage_cached_falls_back_when_database_unusable(
    tmp_path: pathlib.Path,
    configured_feeds: list[peri_scribe.sources.feed_types.Feed],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    feed = configured_feeds[0]
    path = write_cache_snapshot(tmp_path, feed, [("Park Fire", "Active")])

    def failing_sync(*_arguments: object, **_keywords: object) -> None:
        message = "boom"
        raise sqlite3.OperationalError(message)

    monkeypatch.setattr(
        peri_scribe.geo.database,
        "open_and_sync",
        failing_sync,
    )
    contents = peri_scribe.geo.reading.read_geopackage_cached(path)
    assert [row.record.name for row in contents.rows] == ["Park Fire"]


def test_read_geopackage_cached_reads_without_cache_when_stat_fails(
    tmp_path: pathlib.Path,
    configured_feeds: list[peri_scribe.sources.feed_types.Feed],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    feed = configured_feeds[0]
    path = write_cache_snapshot(tmp_path, feed, [("Park Fire", "Active")])
    original_stat = pathlib.Path.stat

    def failing_stat(self: pathlib.Path) -> object:
        if self == path:
            message = "no such file"
            raise OSError(message)
        return original_stat(self)

    monkeypatch.setattr(pathlib.Path, "stat", failing_stat)
    contents = peri_scribe.geo.reading.read_geopackage_cached(path)
    assert [row.record.name for row in contents.rows] == ["Park Fire"]


def test_read_geopackage_cached_stores_new_snapshots_incrementally(
    tmp_path: pathlib.Path,
    configured_feeds: list[peri_scribe.sources.feed_types.Feed],
) -> None:
    feed = configured_feeds[0]
    first = write_cache_snapshot(tmp_path, feed, [("Park Fire", "Active")])
    peri_scribe.geo.reading.read_geopackage_cached(first)
    second = write_cache_snapshot(
        tmp_path,
        feed,
        [("ALTA", "Inactive")],
        serial_number=1,
    )
    contents = peri_scribe.geo.reading.read_geopackage_cached(second)
    assert [row.record.name for row in contents.rows] == ["ALTA"]
    again = peri_scribe.geo.reading.read_geopackage_cached(first)
    assert [row.record.name for row in again.rows] == ["Park Fire"]
    conn = sqlite3.connect(record_cache_database_path(first))
    try:
        serials = [
            row[0]
            for row in conn.execute(
                "SELECT serial FROM snapshots ORDER BY serial",
            )
        ]
    finally:
        conn.close()
    assert serials == [0, 1]


def test_read_geopackage_cached_drops_rows_for_missing_snapshots(
    tmp_path: pathlib.Path,
    configured_feeds: list[peri_scribe.sources.feed_types.Feed],
) -> None:
    feed = configured_feeds[0]
    first = write_cache_snapshot(tmp_path, feed, [("Park Fire", "Active")])
    second = write_cache_snapshot(
        tmp_path,
        feed,
        [("ALTA", "Inactive")],
        serial_number=1,
    )
    peri_scribe.geo.reading.read_geopackage_cached(first)
    peri_scribe.geo.reading.read_geopackage_cached(second)
    first.unlink()
    peri_scribe.geo.reading.read_geopackage_cached(second)
    conn = sqlite3.connect(record_cache_database_path(second))
    try:
        serials = [
            row[0]
            for row in conn.execute(
                "SELECT serial FROM snapshots ORDER BY serial",
            )
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
    path = write_cache_snapshot(tmp_path, feed, [("Park Fire", "Active")])
    peri_scribe.geo.reading.read_geopackage_cached(path)

    def failing_read(*_arguments: object, **_keywords: object) -> object:
        message = "boom"
        raise sqlite3.OperationalError(message)

    monkeypatch.setattr(
        peri_scribe.geo.reading,
        "read_snapshot_contents",
        failing_read,
    )
    contents = peri_scribe.geo.reading.read_geopackage_cached(path)
    assert [row.record.name for row in contents.rows] == ["Park Fire"]


def test_read_geopackage_cached_skips_snapshot_that_cannot_be_checked(
    tmp_path: pathlib.Path,
    configured_feeds: list[peri_scribe.sources.feed_types.Feed],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    feed = configured_feeds[0]
    path = write_cache_snapshot(tmp_path, feed, [("Park Fire", "Active")])
    original = peri_scribe.sources.snapshots.existing_source_files

    def phantom_files(
        directory: pathlib.Path,
    ) -> list[peri_scribe.sources.snapshots.SourceFile]:
        files = original(directory)
        return [
            *files,
            peri_scribe.sources.snapshots.SourceFile(
                serial_number=99,
                last_edit_timestamp=0,
            ),
        ]

    monkeypatch.setattr(
        peri_scribe.sources.snapshots,
        "existing_source_files",
        phantom_files,
    )
    contents = peri_scribe.geo.reading.read_geopackage_cached(path)
    assert [row.record.name for row in contents.rows] == ["Park Fire"]
    conn = sqlite3.connect(record_cache_database_path(path))
    try:
        serials = [
            row[0]
            for row in conn.execute(
                "SELECT serial FROM snapshots ORDER BY serial",
            )
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
    first = write_cache_snapshot(tmp_path, feed, [("Park Fire", "Active")])
    peri_scribe.geo.reading.read_geopackage_cached(first)
    second = write_cache_snapshot(
        tmp_path,
        feed,
        [("ALTA", "Inactive")],
        serial_number=1,
    )
    monkeypatch.setattr(
        peri_scribe.geo.database,
        "sync_database",
        lambda *_arguments, **_keywords: None,
    )
    contents = peri_scribe.geo.reading.read_geopackage_cached(second)
    assert [row.record.name for row in contents.rows] == ["ALTA"]


def test_read_geopackage_cached_round_trips_memberships(
    tmp_path: pathlib.Path,
    configured_feeds_with_identifiers: list[peri_scribe.sources.feed_types.Feed],
) -> None:
    feed = configured_feeds_with_identifiers[1]
    path = tmp_path / "sources" / feed.name / "000___" / "000000,lastEdit=0.gpkg"
    path.parent.mkdir(parents=True, exist_ok=True)
    dataframe = wgs84_dataframe({
        "IncidentName": ["0445 CROSSWHITE", "ROWE CREEK COMPLEX"],
        "ActiveFireCandidate": [1, 1],
        "IrwinID": [
            "{1B0219EE-5298-4FEF-9927-C2666D9D53FC}",
            "{B8431C26-6A9B-4EF0-88D8-F7EA9A3F56C3}",
        ],
        "CpxID": [
            "{B8431C26-6A9B-4EF0-88D8-F7EA9A3F56C3}",
            None,
        ],
        "CpxName": ["ROWE CREEK COMPLEX", None],
        "IsCpxChild": [1, 0],
    })
    dataframe.crs = pyproj.CRS.from_epsg(4326)
    peri_scribe.output.write_geopackage(
        path,
        [
            peri_scribe.models.LayerData(
                name=feed.name,
                dataframe=dataframe,
            ),
        ],
    )
    direct = peri_scribe.geo.package.read_geopackage(path)
    cached = peri_scribe.geo.reading.read_geopackage_cached(path)
    # The records' fixed fields and the memberships round-trip exactly; the
    # attribute bags round-trip with normalized values (numpy scalars become
    # Python values and missing values become None).
    assert [row.record for row in cached.rows] == [row.record for row in direct.rows]
    assert cached.memberships == direct.memberships
    assert [row.attributes.keys() for row in cached.rows] == [
        row.attributes.keys() for row in direct.rows
    ]
