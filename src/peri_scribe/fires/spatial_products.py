"""Retain exact spatial products while querying current external data generations."""

from __future__ import annotations

import hashlib
import pathlib
import typing

import shapely

import peri_scribe.execution
import peri_scribe.fires.buffering
import peri_scribe.fires.reuse
import spatial_data.cache_values
import spatial_data.point_store
import spatial_data.product_cache
import spatial_data.reference


BUFFER_NAMESPACE = "fire-building-buffer-v1"
COUNT_NAMESPACE = "fire-building-count-v1"


def geometry_key(geometry: shapely.Geometry, policy: str) -> str:
    """Identify exact coordinates and dependencies without retaining geometry objects.

    Args:
        geometry: The ordered geometry, including its SRID.
        policy: The complete calculation policy and external generation fingerprint.

    Returns:
        A compact deterministic product key.
    """
    return hashlib.sha256(
        policy.encode() + b"\0" + shapely.to_wkb(geometry, include_srid=True),
    ).hexdigest()


def buffer_policy() -> str:
    """Bind buffers to the actual distance and complete projection definitions.

    Returns:
        The exact buffering dependencies within the native runtime cache context.
    """
    return hashlib.sha256(
        spatial_data.cache_values.dumps((
            peri_scribe.fires.buffering.BUILDING_BUFFER.m_as("meters"),
            spatial_data.reference.WGS84_SPATIAL_REFERENCE.to_wkt(),
            spatial_data.reference.WEB_MERCATOR_SPATIAL_REFERENCE.to_wkt(),
        )),
    ).hexdigest()


def read_buffer(key: str) -> shapely.Geometry | None:
    """Treat damaged or incompatible buffer products as work to recompute.

    Args:
        key: The exact source geometry and buffer-policy identity.

    Returns:
        A fresh polygonal buffer, or None for a cache miss.
    """
    payload = spatial_data.product_cache.get(BUFFER_NAMESPACE, key)
    if payload is None:
        return None
    try:
        geometry = shapely.from_wkb(payload)
    except shapely.errors.GEOSException:
        return None
    return (
        geometry
        if isinstance(geometry, shapely.Polygon | shapely.MultiPolygon)
        else None
    )


def buffered_geometries(
    geometries: list[shapely.Geometry | None],
) -> list[shapely.Geometry | None]:
    """Run the original vectorized buffer calculation only for missing exact products.

    Args:
        geometries: Current WGS84 fire geometries in their scoring order.

    Returns:
        Exact buffered geometries in the same order, preserving missing inputs.
    """
    if not spatial_data.product_cache.active():
        return peri_scribe.fires.buffering.buffered_fire_geometries(geometries)
    policy = buffer_policy()
    result: list[shapely.Geometry | None] = [None] * len(geometries)
    missing: list[tuple[int, str, shapely.Geometry]] = []
    for index, geometry in enumerate(geometries):
        if geometry is None:
            continue
        key = geometry_key(geometry, policy)
        result[index] = read_buffer(key)
        if result[index] is None:
            missing.append((index, key, geometry))
    if missing:
        calculated = peri_scribe.fires.buffering.buffered_fire_geometries([
            geometry for _index, _key, geometry in missing
        ])
        for (index, key, _geometry), buffer in zip(missing, calculated, strict=True):
            result[index] = buffer
            spatial_data.product_cache.put(
                BUFFER_NAMESPACE,
                key,
                shapely.to_wkb(
                    typing.cast("shapely.Geometry", buffer),
                    include_srid=True,
                ),
            )
    return result


def file_generation(path: pathlib.Path) -> str:
    """Hash authoritative dataset bytes once within an execution that owns its inputs.

    Args:
        path: The complete published external dataset.

    Returns:
        A content checksum, never a timestamp-only identity across executions.
    """
    stat = path.stat()
    key = (
        "spatial_dataset",
        path.resolve(),
        stat.st_size,
        stat.st_mtime_ns,
        stat.st_ctime_ns,
        stat.st_ino,
    )
    cached = peri_scribe.execution.get(peri_scribe.execution.Group.DERIVED, key)
    if isinstance(cached, str):
        return cached
    result = peri_scribe.fires.reuse.file_digest(path)
    peri_scribe.execution.put(peri_scribe.execution.Group.DERIVED, key, result)
    return result


def read_count(key: str) -> int | None:
    """Require canonical nonnegative counts before avoiding a spatial query.

    Args:
        key: The complete query geometry, dataset, and counting-policy identity.

    Returns:
        The exact count, or None for an absent or invalid product.
    """
    payload = spatial_data.product_cache.get(COUNT_NAMESPACE, key)
    if payload is None:
        return None
    try:
        count = int(payload)
    except ValueError:
        return None
    return count if count >= 0 and str(count).encode() == payload else None


def building_counts(
    geometries: list[shapely.Geometry | None],
    path: pathlib.Path,
) -> list[int]:
    """Preserve strict containment and duplicate counting for current building data.

    Args:
        geometries: Current buffered WGS84 query geometries in scoring order.
        path: The complete compact building database.

    Returns:
        Exact counts in query order, with missing and empty geometry counting zero.
    """
    if (
        not spatial_data.product_cache.active()
        or not path.is_file()
        or path.with_name(f"{path.name}-wal").exists()
    ):
        return spatial_data.point_store.point_counts_within(geometries, path)
    policy = hashlib.sha256(
        spatial_data.cache_values.dumps((
            file_generation(path),
            spatial_data.point_store.expected_metadata(),
        )),
    ).hexdigest()
    result = [0] * len(geometries)
    missing: list[tuple[int, str, shapely.Geometry]] = []
    for index, geometry in enumerate(geometries):
        if geometry is None or geometry.is_empty:
            continue
        key = geometry_key(geometry, policy)
        count = read_count(key)
        if count is None:
            missing.append((index, key, geometry))
        else:
            result[index] = count
    if missing:
        calculated = spatial_data.point_store.point_counts_within(
            [geometry for _index, _key, geometry in missing],
            path,
        )
        for (index, key, _geometry), count in zip(missing, calculated, strict=True):
            result[index] = count
            spatial_data.product_cache.put(COUNT_NAMESPACE, key, str(count).encode())
    return result
