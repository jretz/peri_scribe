"""Build inputs for changes tests."""

from __future__ import annotations

import datetime
import pathlib

import geopandas
import pyproj
import shapely.geometry

import peri_scribe.models
import peri_scribe.output
import peri_scribe.sources.feed_types
import peri_scribe.sources.snapshots


def change_dataframe(
    rows: list[tuple[int, str, tuple[float, float]]],
) -> geopandas.GeoDataFrame:
    """Return a GeoDataFrame of point features for the given rows.

    Args:
        rows: The OBJECTID, name, and coordinates of each feature.

    Returns:
        The GeoDataFrame.
    """
    return geopandas.GeoDataFrame(
        {"OBJECTID": [row[0] for row in rows], "name": [row[1] for row in rows]},
        geometry=[shapely.geometry.Point(row[2]) for row in rows],
        crs=pyproj.CRS.from_epsg(4326),
    )


UTC = datetime.UTC


SAMPLE_FEATURE_ROW = (1, "a", (0.0, 0.0))


type FeatureRow = tuple[int, str, tuple[float, float]]


def modified_dataframe(
    rows: list[tuple[int, str, tuple[float, float]]],
) -> geopandas.GeoDataFrame:
    """Return a GeoDataFrame with OBJECTID and modified-time columns.

    Args:
        rows: The OBJECTID, modified time, and coordinates of each feature.

    Returns:
        The GeoDataFrame.
    """
    return geopandas.GeoDataFrame(
        {
            "OBJECTID": [row[0] for row in rows],
            "ModifiedOnDateTime_dt": [row[1] for row in rows],
        },
        geometry=[shapely.geometry.Point(row[2]) for row in rows],
        crs=pyproj.CRS.from_epsg(4326),
    )


def status_dataframe(
    rows: list[tuple[int, object, tuple[float, float]]],
) -> geopandas.GeoDataFrame:
    """Return a GeoDataFrame with OBJECTID and status columns.

    Args:
        rows: The OBJECTID, raw status value, and coordinates of each feature.

    Returns:
        The GeoDataFrame.
    """
    return geopandas.GeoDataFrame(
        {"OBJECTID": [row[0] for row in rows], "status": [row[1] for row in rows]},
        geometry=[shapely.geometry.Point(row[2]) for row in rows],
        crs=pyproj.CRS.from_epsg(4326),
    )


def polygon_feature_dataframe(
    rows: list[tuple[int, str, list[tuple[float, float]]]],
) -> geopandas.GeoDataFrame:
    """Return a GeoDataFrame of polygon features for the given rows.

    Args:
        rows: The OBJECTID, name, and exterior ring of each feature.

    Returns:
        The GeoDataFrame.
    """
    return geopandas.GeoDataFrame(
        {"OBJECTID": [row[0] for row in rows], "name": [row[1] for row in rows]},
        geometry=[shapely.geometry.Polygon(row[2]) for row in rows],
        crs=pyproj.CRS.from_epsg(4326),
    )


def write_snapshot(
    source_directory: pathlib.Path,
    feed: peri_scribe.sources.feed_types.Feed,
    serial_number: int,
    rows: list[tuple[int, str, tuple[float, float]]],
) -> None:
    """Write one snapshot GeoPackage under *source_directory*.

    Args:
        source_directory: The directory to write the snapshot into.
        feed: The feed the snapshot's layer belongs to.
        serial_number: The snapshot's serial number.
        rows: The OBJECTID, name, and coordinates of each feature.
    """
    relative_path = peri_scribe.sources.snapshots.SourceFile(
        serial_number=serial_number,
        last_edit_timestamp=0,
    ).relative_path
    path = source_directory / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    peri_scribe.output.write_geopackage(
        path,
        [
            peri_scribe.models.LayerData(
                name=feed.name,
                dataframe=change_dataframe(rows),
            ),
        ],
    )


def snapshot_source_directory(tmp_path: pathlib.Path) -> pathlib.Path:
    """Return an isolated feed snapshot directory under *tmp_path*.

    The snapshot directory sits one level under *tmp_path*, so each test's snapshots,
    current-state files, and record cache stay inside its own *tmp_path*.

    Args:
        tmp_path: The pytest-provided per-test directory.

    Returns:
        The feed's snapshot directory.
    """
    return tmp_path / "snapshots"
