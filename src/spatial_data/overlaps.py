"""Indexed overlap queries read candidate geometries in bounded chunks."""

from __future__ import annotations

import pathlib
import sqlite3
import typing

import geopandas
import numpy as np
import pyogrio
import pyproj
import shapely

import spatial_data.layers
import spatial_data.reference


QUERY_CHUNK_SIZE = 100_000


def gpkg_geometry_header_size(flags: int) -> int:
    """Return a GeoPackage geometry blob's header size for its flags byte.

    A point's envelope is trivial, so points store no envelope and use the 8-byte
    header. Other geometries store an XY envelope (40-byte header) or, when they carry a
    Z, an XYZ envelope (56-byte header).

    Args:
        flags: The geometry blob's flags byte.

    Returns:
        The header size in bytes.

    Examples:
        >>> gpkg_geometry_header_size(0)
        8

        >>> gpkg_geometry_header_size(0x02)
        40

        >>> gpkg_geometry_header_size(0x04)
        56
    """
    if flags & 0x04:
        return 56
    if flags & 0x02:
        return 40
    return 8


def gpkg_blob_geometry(blob: bytes) -> bytes:
    """Return the WKB payload of a GeoPackage geometry blob.

    Args:
        blob: The raw GeoPackage geometry blob.

    Returns:
        The WKB geometry payload.
    """
    return blob[gpkg_geometry_header_size(blob[3]) :]


def has_rtree(path: pathlib.Path, layer_name: str) -> bool:
    """Return True when the GeoPackage has an R-Tree index for *layer_name*.

    Args:
        path: The GeoPackage file.
        layer_name: The layer to check.

    Returns:
        True when the layer has an R-Tree index.
    """
    connection = sqlite3.connect(path)
    try:
        row = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (f"rtree_{layer_name}_geom",),
        ).fetchone()
        return row is not None
    finally:
        connection.close()


def candidate_fids(
    path: pathlib.Path,
    layer_name: str,
    boxes: list[tuple[int, float, float, float, float]],
) -> dict[int, list[int]]:
    """Return, per box index, the feature ids whose R-Tree envelope overlaps the box.

    Each box is ``(index, minimum_x, minimum_y, maximum_x, maximum_y)``.

    Args:
        path: The GeoPackage file.
        layer_name: The layer to query.
        boxes: The boxes to query, as ``(index, minimum_x, minimum_y, maximum_x,
            maximum_y)`` tuples.

    Returns:
        A mapping from box index to the feature ids whose envelopes overlap that box.
    """
    connection = sqlite3.connect(path)
    try:
        result: dict[int, list[int]] = {}
        for index, minimum_x, minimum_y, maximum_x, maximum_y in boxes:
            fids = [
                row[0]
                for row in connection.execute(
                    f"SELECT id FROM rtree_{layer_name}_geom "
                    "WHERE minx <= ? AND maxx >= ? AND miny <= ? AND maxy >= ?",
                    (maximum_x, minimum_x, maximum_y, minimum_y),
                )
            ]
            if fids:
                result[index] = fids
        return result
    finally:
        connection.close()


def fetch_layer_geometries(
    path: pathlib.Path,
    layer_name: str,
    fids: typing.Iterable[int],
) -> np.ndarray:
    """Return the geometries of *fids* from *layer_name*, in fid order.

    The features are read straight from the GeoPackage's SQLite storage via a temporary
    table left-joined to the layer, so each candidate is an indexed ``fid`` lookup and
    no attribute columns are parsed.

    Args:
        path: The GeoPackage file.
        layer_name: The layer to read.
        fids: The feature ids to fetch.

    Returns:
        The geometries as a numpy array of shapely geometries.
    """
    sorted_fids = sorted(fids)
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TEMP TABLE cand (fid INTEGER PRIMARY KEY)")
        connection.executemany(
            "INSERT OR IGNORE INTO cand VALUES (?)",
            ((fid,) for fid in sorted_fids),
        )
        blobs = [
            row[0]
            for row in connection.execute(
                f"SELECT b.geom FROM cand c LEFT JOIN {layer_name} b ON b.fid = c.fid",
            )
        ]
    finally:
        connection.close()
    geometry_wkb = np.asarray(
        [gpkg_blob_geometry(blob) for blob in blobs],
        dtype=object,
    )
    return np.asarray(shapely.from_wkb(geometry_wkb))


def overlapping_layer_indices(
    geometries: list[shapely.Geometry | None],
    path: pathlib.Path,
    layer_name: str,
    chunk_size: int = QUERY_CHUNK_SIZE,
) -> set[int]:
    """Return the indices of *geometries* that overlap a feature of *layer_name*.

    The layer's R-Tree index is used to fetch only the features whose envelopes overlap
    a query footprint, then those features are tested for intersection through a spatial
    index over the query geometries. The query geometries are transformed to the layer's
    spatial reference; a layer without one is treated as WGS84.

    Args:
        geometries: The query geometries, in WGS84, or None.
        path: The layer's GeoPackage.
        layer_name: The layer to read.
        chunk_size: The maximum number of features read at once when the layer has no
            R-Tree index and the streaming fallback is used.

    Returns:
        The indices of the geometries that overlap at least one layer feature.
    """
    valid = [
        (index, geometry)
        for index, geometry in enumerate(geometries)
        if geometry is not None and not geometry.is_empty
    ]
    if not valid:
        return set()
    raw_crs = pyogrio.read_info(path, layer=layer_name)["crs"]
    layer_crs = (
        spatial_data.reference.WGS84_SPATIAL_REFERENCE
        if raw_crs is None
        else pyproj.CRS.from_user_input(raw_crs)
    )
    valid_geometries = [geometry for _index, geometry in valid]
    if layer_crs.equals(spatial_data.reference.WGS84_SPATIAL_REFERENCE):
        reprojected = valid_geometries
    else:
        reprojected = list(
            geopandas.GeoSeries(
                valid_geometries,
                crs=spatial_data.reference.WGS84_SPATIAL_REFERENCE,
            ).to_crs(layer_crs),
        )
    reproj = [
        (index, geometry)
        for (index, _original), geometry in zip(valid, reprojected, strict=True)
    ]
    tree_geometries = np.asarray([geometry for _index, geometry in reproj])
    tree = shapely.STRtree(tree_geometries)
    if has_rtree(path, layer_name):
        boxes = [(index, *geometry.bounds) for index, geometry in reproj]
        query_fids = candidate_fids(path, layer_name, boxes)
        if not query_fids:
            return set()
        fids = sorted({fid for fids in query_fids.values() for fid in fids})
        candidates = fetch_layer_geometries(path, layer_name, fids)
        return overlapping_indices(candidates, tree, tree_geometries, reproj)
    overlapping: set[int] = set()
    for chunk in spatial_data.layers.read_layer_chunks(
        path,
        layer_name,
        chunk_size,
    ):
        overlapping.update(
            overlapping_indices(
                np.asarray(chunk.geometry),
                tree,
                tree_geometries,
                reproj,
            ),
        )
    return overlapping


def overlapping_indices(
    candidates: np.ndarray,
    tree: shapely.STRtree,
    tree_geometries: np.ndarray,
    reproj: list[tuple[int, shapely.Geometry]],
) -> set[int]:
    """Return the query indices whose reprojected geometry intersects a candidate.

    Args:
        candidates: The layer features to test.
        tree: A spatial index over the reprojected query geometries.
        tree_geometries: The reprojected query geometries backing *tree*.
        reproj: The ``(index, geometry)`` pairs aligned with *tree_geometries*.

    Returns:
        The query indices that intersect at least one candidate.
    """
    input_indices, tree_indices = tree.query(candidates)
    if len(input_indices) == 0:
        return set()
    intersects = shapely.intersects(
        candidates[input_indices],
        tree_geometries[tree_indices],
    )
    return {reproj[position][0] for position in np.unique(tree_indices[intersects])}
