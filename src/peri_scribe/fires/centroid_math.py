"""Computing polygon centroids from raw geometry bytes."""

from __future__ import annotations

import dataclasses

import numpy as np
import pyproj

import peri_scribe.fires.centroid_streaming
import peri_scribe.geo.spatial_reference


# The maximum number of features per conversion chunk.


TO_WEB_MERCATOR = pyproj.Transformer.from_crs(
    peri_scribe.geo.spatial_reference.WGS84_SPATIAL_REFERENCE,
    peri_scribe.geo.spatial_reference.WEB_MERCATOR_SPATIAL_REFERENCE,
    always_xy=True,
)


TO_WGS84 = pyproj.Transformer.from_crs(
    peri_scribe.geo.spatial_reference.WEB_MERCATOR_SPATIAL_REFERENCE,
    peri_scribe.geo.spatial_reference.WGS84_SPATIAL_REFERENCE,
    always_xy=True,
)


@dataclasses.dataclass(frozen=True, kw_only=True)
class SegmentIndexes:
    """Per-ring segment index arrays for one chunk.

    ``ring_segment_starts`` holds the index of each ring's first segment in the
    concatenated segment arrays; ``segment_indices`` holds the absolute coordinate index
    of each segment's start; ``ring_of_segment`` holds the ring of each segment.
    """

    ring_segment_starts: np.ndarray
    segment_indices: np.ndarray
    ring_of_segment: np.ndarray


@dataclasses.dataclass(frozen=True, kw_only=True)
class RingCentroidSums:
    """Per-ring shoelace quantities for centroid aggregation.

    ``absolute_double_areas`` holds each ring's absolute signed double area;
    ``signed_numerators`` holds each ring's signed centroid numerator as an ``(R, 2)``
    array (translated coordinates); ``area_weighted_offsets`` holds each ring's double
    area times its translation offset, so the original-coordinate centroid is
    ``(signed_numerators + 3 * area_weighted_offsets) / (3 * absolute_double_areas)``
    combined by part and feature.
    """

    absolute_double_areas: np.ndarray
    signed_numerators: np.ndarray
    area_weighted_offsets: np.ndarray


def segment_indexes(ring_bounds: np.ndarray) -> SegmentIndexes:
    """Return per-ring segment index arrays for *ring_bounds*.

    The segment index arrays are capped by the vertex budget, so int32 is safe and
    halves their footprint versus int64.

    Args:
        ring_bounds: Each ring's ``[start, end)`` into the concatenated coordinates.

    Returns:
        The per-ring segment index arrays.
    """
    ring_starts = ring_bounds[:, 0]
    ring_ends = ring_bounds[:, 1]
    segment_counts = ring_ends - ring_starts - 1
    ring_segment_starts = np.concatenate([[0], np.cumsum(segment_counts[:-1])])
    total_segments = int(segment_counts.sum())
    segment_in_ring = np.arange(total_segments, dtype=np.int32) - np.repeat(
        ring_segment_starts.astype(np.int32),
        segment_counts.astype(np.int32),
    )
    segment_indices = (
        np.repeat(
            ring_starts.astype(np.int32),
            segment_counts.astype(np.int32),
        )
        + segment_in_ring
    )
    ring_of_segment = np.repeat(
        np.arange(len(ring_bounds), dtype=np.int32),
        segment_counts,
    )
    return SegmentIndexes(
        ring_segment_starts=ring_segment_starts,
        segment_indices=segment_indices,
        ring_of_segment=ring_of_segment,
    )


def ring_shoelace_sums(
    x: np.ndarray,
    y: np.ndarray,
    offsets: np.ndarray,
    indexes: SegmentIndexes,
) -> tuple[np.ndarray, np.ndarray]:
    """Return each ring's cross sum and centroid numerator for its segments.

    Args:
        x: The concatenated x coordinates.
        y: The concatenated y coordinates.
        offsets: Each ring's translation offset.
        indexes: The per-ring segment index arrays.

    Returns:
        The per-ring cross sums and the ``(R, 2)`` centroid numerators.
    """
    segment_x = x[indexes.segment_indices] - offsets[indexes.ring_of_segment, 0]
    segment_y = y[indexes.segment_indices] - offsets[indexes.ring_of_segment, 1]
    end_x = x[indexes.segment_indices + 1] - offsets[indexes.ring_of_segment, 0]
    end_y = y[indexes.segment_indices + 1] - offsets[indexes.ring_of_segment, 1]
    cross_products = segment_x * end_y - end_x * segment_y
    numerators = np.column_stack(
        [
            np.add.reduceat(
                (segment_x + end_x) * cross_products,
                indexes.ring_segment_starts,
            ),
            np.add.reduceat(
                (segment_y + end_y) * cross_products,
                indexes.ring_segment_starts,
            ),
        ],
    )
    return (
        np.add.reduceat(cross_products, indexes.ring_segment_starts),
        numerators,
    )


def ring_centroid_sums(
    coordinates: np.ndarray,
    ring_bounds: np.ndarray,
) -> RingCentroidSums:
    """Return per-ring shoelace quantities for *coordinates*.

    Each ring is translated so its first point is the origin before the shoelace sums,
    then the offset is returned area-weighted so the caller can add it back.

    Args:
        coordinates: The concatenated ring coordinates.
        ring_bounds: Each ring's ``[start, end)`` into *coordinates*.

    Returns:
        The per-ring quantities.
    """
    x = coordinates[:, 0]
    y = coordinates[:, 1]
    indexes = segment_indexes(ring_bounds)
    offsets = coordinates[ring_bounds[:, 0]]
    ring_cross_sums, numerators = ring_shoelace_sums(
        x,
        y,
        offsets,
        indexes,
    )
    signs = np.sign(ring_cross_sums)
    signed_numerators = signs[:, None] * numerators
    absolute_double_areas = np.abs(ring_cross_sums)
    return RingCentroidSums(
        absolute_double_areas=absolute_double_areas,
        signed_numerators=signed_numerators,
        area_weighted_offsets=absolute_double_areas[:, None] * offsets,
    )


def part_boundaries(ring_parts: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return the part-boundary index arrays for *ring_parts*.

    ``part_starts`` holds the ring index where each part after the first begins;
    ``boundaries`` is the same list prefixed with zero, for ``np.add.reduceat``.

    Args:
        ring_parts: The part id of each ring.

    Returns:
        The part-start ring indexes and the reduceat boundaries.
    """
    part_starts = np.flatnonzero(np.diff(ring_parts)) + 1
    return part_starts, np.concatenate([[0], part_starts])


def feature_boundaries(part_counts: np.ndarray) -> np.ndarray:
    """Return the part-index boundaries between features for reduceat.

    Args:
        part_counts: The number of parts per feature.

    Returns:
        The reduceat boundaries over per-part arrays.
    """
    part_features = np.repeat(np.arange(len(part_counts)), part_counts)
    feature_starts = np.flatnonzero(np.diff(part_features)) + 1
    return np.concatenate([[0], feature_starts])


def mean_vertex_centroids(
    projected: np.ndarray,
    chunk: peri_scribe.fires.centroid_streaming.GeometryChunk,
) -> np.ndarray:
    """Return each feature's mean projected ring vertex, as an ``(F, 2)`` array.

    Used as the fallback centroid for degenerate (zero-area) features, in the same
    projected space the centroids are computed in.

    Args:
        projected: The chunk's rings projected to EPSG:3857.
        chunk: The chunk whose features' vertex means are returned.

    Returns:
        The mean vertex per feature, in EPSG:3857.
    """
    ring_vertex_sums = np.add.reduceat(projected, chunk.ring_bounds[:, 0])
    ring_lengths = chunk.ring_bounds[:, 1] - chunk.ring_bounds[:, 0]
    _part_starts, boundaries = part_boundaries(chunk.ring_parts)
    part_vertex_sums = np.add.reduceat(ring_vertex_sums, boundaries)
    part_vertex_lengths = np.add.reduceat(ring_lengths[:, None], boundaries)
    feature_boundary_indexes = feature_boundaries(chunk.part_counts)
    feature_vertex_sums = np.add.reduceat(part_vertex_sums, feature_boundary_indexes)
    feature_vertex_lengths = np.add.reduceat(
        part_vertex_lengths,
        feature_boundary_indexes,
    )
    return feature_vertex_sums / feature_vertex_lengths


def projected_centroids(
    projected: np.ndarray,
    chunk: peri_scribe.fires.centroid_streaming.GeometryChunk,
    sums: RingCentroidSums,
) -> np.ndarray:
    """Return each feature's EPSG:3857 centroid from its ring shoelace sums.

    A part (single polygon) combines its exterior ring positively and its interior rings
    negatively; a feature (possibly a multipolygon) combines its parts by area. This is
    the same area-weighted combination GEOS applies for polygon centroids.

    Args:
        projected: The chunk's rings projected to EPSG:3857.
        chunk: The chunk being converted.
        sums: Its per-ring shoelace quantities.

    Returns:
        The ``(F, 2)`` centroid coordinates in EPSG:3857.
    """
    part_starts, boundaries = part_boundaries(chunk.ring_parts)
    is_part_start = np.zeros(len(chunk.ring_bounds), dtype=bool)
    is_part_start[0] = True
    is_part_start[part_starts] = True
    ring_weights = np.where(is_part_start, 1.0, -1.0)
    part_double_areas = np.add.reduceat(
        sums.absolute_double_areas * ring_weights,
        boundaries,
    )
    part_numerators = np.add.reduceat(
        (sums.signed_numerators + 3.0 * sums.area_weighted_offsets)
        * ring_weights[:, None],
        boundaries,
    )
    feature_boundary_indexes = feature_boundaries(chunk.part_counts)
    double_areas = np.add.reduceat(part_double_areas, feature_boundary_indexes)
    numerators = np.add.reduceat(part_numerators, feature_boundary_indexes)
    with np.errstate(divide="ignore", invalid="ignore"):
        centroids = numerators / (3.0 * double_areas)[:, None]
    degenerate = ~np.isfinite(centroids[:, 0]) | ~np.isfinite(centroids[:, 1])
    if degenerate.any():
        centroids[degenerate] = mean_vertex_centroids(projected, chunk)[degenerate]
    return centroids


def polygon_centroids(
    chunk: peri_scribe.fires.centroid_streaming.GeometryChunk,
) -> np.ndarray:
    """Return each feature's WGS84 centroid point from *chunk*'s WGS84 rings.

    The rings are projected to EPSG:3857, the area-weighted centroid is computed, and
    the centroid is projected back to WGS84, matching how a projection-aware centroid is
    computed.

    Args:
        chunk: The chunk whose features' centroids are returned.

    Returns:
        The ``(F, 2)`` centroid longitudes and latitudes.
    """
    projected = np.column_stack(
        TO_WEB_MERCATOR.transform(
            chunk.coordinates[:, 0],
            chunk.coordinates[:, 1],
        ),
    )
    sums = ring_centroid_sums(projected, chunk.ring_bounds)
    centroids_3857 = projected_centroids(projected, chunk, sums)
    return np.column_stack(
        TO_WGS84.transform(centroids_3857[:, 0], centroids_3857[:, 1]),
    )
