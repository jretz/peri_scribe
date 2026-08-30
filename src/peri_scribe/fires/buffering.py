"""Buffering fire geometries for building-count distance."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor

import geopandas
import shapely

import peri_scribe.geo.spatial_reference


BUILDING_BUFFER_IN_METERS = 1609.34


def union_geometry(geometries: geopandas.GeoSeries) -> shapely.Geometry | None:
    """Return the union of *geometries*, or None when there is none.

    Args:
        geometries: The geometries to combine.

    Returns:
        The union of the non-empty geometries, or None when all are empty or missing.
    """
    non_empty = [
        geometry
        for geometry in geometries
        if geometry is not None and not geometry.is_empty
    ]
    if not non_empty:
        return None
    if len(non_empty) == 1:
        return non_empty[0]
    return shapely.union_all(non_empty)


def buffered_fire_geometries(
    geometries: list[shapely.Geometry | None],
) -> list[shapely.Geometry | None]:
    """Return each fire geometry buffered by the building-count distance, or None.

    The geometries are reprojected to web mercator in one vectorized pass, buffered in
    parallel across a small thread pool (the GEOS buffer releases the GIL), and
    reprojected back in one vectorized pass.

    Args:
        geometries: The fire geometries, in WGS84.

    Returns:
        One buffered WGS84 geometry per fire, None where the fire has no geometry.
    """
    result: list[shapely.Geometry | None] = [None] * len(geometries)
    present = [
        (index, geometry)
        for index, geometry in enumerate(geometries)
        if geometry is not None
    ]
    if not present:
        return result
    metric = geopandas.GeoSeries(
        [geometry for _index, geometry in present],
        crs=peri_scribe.geo.spatial_reference.WGS84_SPATIAL_REFERENCE,
    ).to_crs(peri_scribe.geo.spatial_reference.WEB_MERCATOR_SPATIAL_REFERENCE)
    with ThreadPoolExecutor(max_workers=buffer_worker_count()) as executor:
        buffered_metric = list(executor.map(buffer_geometry, metric))
    buffered = geopandas.GeoSeries(
        buffered_metric,
        crs=peri_scribe.geo.spatial_reference.WEB_MERCATOR_SPATIAL_REFERENCE,
    ).to_crs(peri_scribe.geo.spatial_reference.WGS84_SPATIAL_REFERENCE)
    for (index, _geometry), buffered_geometry in zip(present, buffered, strict=True):
        result[index] = buffered_geometry
    return result


def buffer_geometry(geometry: shapely.Geometry) -> shapely.Geometry:
    """Return *geometry* buffered by the building-count distance.

    Args:
        geometry: The geometry to buffer.

    Returns:
        The buffered geometry.
    """
    return geometry.buffer(BUILDING_BUFFER_IN_METERS)


def buffer_worker_count() -> int:
    """Return a sensible number of buffer threads for this machine.

    Returns:
        The number of worker threads, between 1 and 8.
    """
    return max(1, min(8, os.cpu_count() or 1))
