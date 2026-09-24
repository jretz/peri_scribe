"""Ordered row fingerprints let per-fire caches skip materializing unchanged slices."""

from __future__ import annotations

import dataclasses
import hashlib
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
    geometry_name = frame.active_geometry_name
    schema = spatial_data.cache_values.dumps((
        tuple(frame.columns),
        tuple(str(dtype) for dtype in frame.dtypes),
        geometry_name,
        None if geometry_name is None or frame.crs is None else frame.crs.to_wkt(),
    ))
    return FrameRows(
        schema=hashlib.sha256(schema).digest(),
        rows=tuple(
            hashlib.sha256(spatial_data.cache_values.dumps(row)).digest()
            for row in frame.itertuples(index=False, name=None)
        ),
    )


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
    selected = tuple(
        (frame.schema, tuple(frame.rows[position] for position in rows))
        for frame, rows in zip(frames, positions, strict=True)
    )
    return hashlib.sha256(
        spatial_data.cache_values.dumps((identity, selected)),
    ).hexdigest()
