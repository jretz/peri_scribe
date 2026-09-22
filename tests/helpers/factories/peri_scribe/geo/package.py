"""Build inputs for package tests."""

from __future__ import annotations

import pathlib
import typing

import geopandas
import pyproj
import shapely
import shapely.geometry

import spatial_data.layers


if typing.TYPE_CHECKING:
    import peri_scribe.sources.feed_types


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
