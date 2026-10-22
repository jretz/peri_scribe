"""Build inputs for package tests."""

from __future__ import annotations

import contextlib
import pathlib
import sqlite3

import geopandas
import pyproj
import shapely
import shapely.geometry

import peri_scribe.geo.fingerprints
import peri_scribe.geo.package
import peri_scribe.sources.feed_types
import spatial_data.layers


def cache_row(
    source: peri_scribe.geo.package.FireRowRecord,
    **changes: object,
) -> sqlite3.Row:
    """Expose exact logical payloads under the public row adapter's column names.

    Args:
        source: Complete original evidence serialized with its typed metadata.
        changes: Deliberate changes to stored columns after their fingerprint is set.

    Returns:
        A named SQLite row independent of any persistent database schema.
    """
    columns = (
        "serial",
        "object_id",
        "source_name",
        "name",
        "status",
        "identifiers",
        "names",
        "geometry_wkb",
        "observed_at",
        "mission",
        "point_of_origin_state",
        "point_of_origin_fips",
        "attributes_json",
    )
    values = dict(zip(columns, source.to_row(7), strict=True))
    values["evidence_fingerprint"] = (
        peri_scribe.geo.fingerprints.complete_row_fingerprint(source)
    )
    values.update(changes)
    with contextlib.closing(sqlite3.connect(":memory:")) as connection:
        connection.row_factory = sqlite3.Row
        return connection.execute(
            "SELECT " + ", ".join(f"? AS {column}" for column in values),
            tuple(values.values()),
        ).fetchone()


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
        geometry = [shapely.geometry.Point(0, 0), shapely.geometry.Point(1, 1)]
    return geopandas.GeoDataFrame(columns, geometry=geometry)


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
    spatial_data.layers.write_geopackage(
        path,
        [
            spatial_data.layers.LayerData(
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
