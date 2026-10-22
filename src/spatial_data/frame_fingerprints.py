"""Use row fingerprints to reuse fire data without rebuilding unchanged slices.

[Evidence and cache reasoning](../../docs/algorithms/product-caching.md)
explains the contract and correctness argument.
"""

from __future__ import annotations

import dataclasses
import hashlib
import struct
import typing

import spatial_data.cache_values


if typing.TYPE_CHECKING:
    import geopandas


@dataclasses.dataclass(frozen=True, kw_only=True)
class FrameRows:
    """Keep column semantics and row order separate from a fire's selected positions."""

    schema: bytes
    rows: tuple[bytes, ...]


def frame_rows(frame: geopandas.GeoDataFrame) -> FrameRows:
    """Fingerprint full row evidence once, including geometry, schema, and CRS.

    Index labels are excluded because history consumers select and iterate positionally.
    Missing sentinels and attribute types remain distinct even when pandas considers
    them equivalent.

    Args:
        frame: A history layer in its original row order.

    Returns:
        Schema and per-row SHA-256 digests for ordered subset selection.

    """
    # Series iteration preserves scalar types and repeated column labels.
    rows = (
        ()
        if frame.empty
        else tuple(
            hashlib.sha256(spatial_data.cache_values.dumps(row)).digest()
            for row in zip(*(column[1] for column in frame.items()), strict=True)
        )
    )
    return FrameRows(
        schema=frame_schema(frame),
        rows=rows,
    )


def frame_schema(frame: geopandas.GeoDataFrame) -> bytes:
    """Fingerprint column semantics once for many latest-row selections.

    Args:
        frame: The complete source layer.

    Returns:
        The exact ordered schema and CRS digest, independent of selected positions.
    """
    geometry_name = frame.active_geometry_name
    schema = spatial_data.cache_values.dumps((
        tuple(frame.columns),
        tuple(str(dtype) for dtype in frame.dtypes),
        geometry_name,
        None if geometry_name is None or frame.crs is None else frame.crs.to_wkt(),
    ))
    return hashlib.sha256(schema).digest()


def selected_key(
    frames: tuple[FrameRows, ...],
    positions: tuple[tuple[int, ...], ...],
    identity: object,
) -> str:
    """Tie a prepared result to complete ordered evidence and its canonical identity.

    Args:
        frames: Fingerprinted source layers in their semantic order.
        positions: The selected row positions for each layer.
        identity: Additional identity or configuration that affects the result.

    Returns:
        The combined SHA-256 cache key.
    """
    payload = spatial_data.cache_values.dumps(identity)
    digest = hashlib.sha256(b"selected-rows-v2\0")
    digest.update(struct.pack("!QQ", len(payload), len(frames)))
    digest.update(payload)
    for frame, rows in zip(frames, positions, strict=True):
        digest.update(struct.pack("!QQ", len(frame.schema), len(rows)))
        digest.update(frame.schema)
        for position in rows:
            row = frame.rows[position]
            digest.update(struct.pack("!Q", len(row)))
            digest.update(row)
    return digest.hexdigest()
