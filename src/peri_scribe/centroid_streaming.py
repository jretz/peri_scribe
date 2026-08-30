"""Converting streamed building-footprint archives into centroid points.

The Microsoft building-footprint archives are zips, each holding a single GeoJSON
FeatureCollection of footprint polygons. The archives are multiple gigabytes when
decompressed, so the conversion here reads them as a stream: the archive's bytes arrive
incrementally (a download in progress), ``stream_unzip`` decompresses the member as the
bytes arrive, and the parsed geometry feeds the centroid conversion directly. Neither
the archive nor the GeoJSON is ever written to disk, and the conversion never holds more
than one bounded chunk of features in memory.

The centroid of each footprint is the polygon's area-weighted centroid, computed in
EPSG:3857 so the result matches a projection-aware centroid. Each ring is translated to
its own first point before the shoelace sums: EPSG:3857 coordinates are on the order of
10^7 meters while a building's double area is on the order of 10^3, so the naive sums
lose precision to catastrophic cancellation (the area itself can come out wrong by
meters). Centroid is translation-invariant, so each ring's offset is added back,
area-weighted.
"""

from __future__ import annotations

import collections
import dataclasses
import pathlib
import typing
from array import array

import ijson
import numpy as np
import pyogrio
import pyproj
import shapely
import stream_unzip

import peri_scribe.exceptions


# The maximum number of features per conversion chunk.
FEATURE_CHUNK_SIZE = 100_000

# The maximum number of ring vertices per conversion chunk, so a dense state cannot blow
# up the chunk's coordinate arrays (2M vertices ~= 16 MB float64).
MAXIMUM_VERTICES_PER_CHUNK = 2_000_000

WGS84_SPATIAL_REFERENCE = pyproj.CRS.from_epsg(4326)
WEB_MERCATOR_SPATIAL_REFERENCE = pyproj.CRS.from_epsg(3857)

TO_WEB_MERCATOR = pyproj.Transformer.from_crs(
    WGS84_SPATIAL_REFERENCE,
    WEB_MERCATOR_SPATIAL_REFERENCE,
    always_xy=True,
)
TO_WGS84 = pyproj.Transformer.from_crs(
    WEB_MERCATOR_SPATIAL_REFERENCE,
    WGS84_SPATIAL_REFERENCE,
    always_xy=True,
)

GEOJSON_MEMBER_SUFFIX = b".geojson"


class ByteStream:
    """A file-like reader over an iterable of bytes chunks.

    ijson needs a file-like object, and the decompressed chunks from ``stream_unzip``
    are an iterable of bytes, so this adapter presents them through a ``read()``
    interface without materializing them in a file.
    """

    def __init__(self, chunks: typing.Iterable[bytes]) -> None:
        self.chunks = iter(chunks)
        self.buffer = b""

    def read(self, size: int = -1) -> bytes:
        """Return the next up to *size* bytes of the stream.

        Args:
            size: The maximum number of bytes to return, or -1 for all remaining.

        Returns:
            The bytes, or ``b""`` at the end of the stream.
        """
        if size < 0:
            result = self.buffer + b"".join(self.chunks)
            self.buffer = b""
            return result
        while len(self.buffer) < size:
            try:
                self.buffer += next(self.chunks)
            except StopIteration:
                break
        if not self.buffer:
            return b""
        result, self.buffer = self.buffer[:size], self.buffer[size:]
        return result


@dataclasses.dataclass(frozen=True, kw_only=True)
class GeometryChunk:
    """One bounded collection of ring geometry from a GeoJSON stream.

    ``coordinates`` holds every ring's coordinates concatenated as an ``(M, 2)`` float64
    array; ``ring_bounds`` holds each ring's ``[start, end)`` into it as an ``(R, 2)``
    int64 array (rings are closed, so the first and last points coincide);
    ``ring_parts`` holds the part id of each ring, where a part is one polygon of a
    multipolygon and a part's first ring is its exterior; ``part_counts`` holds the
    number of parts per feature.
    """

    coordinates: np.ndarray
    ring_bounds: np.ndarray
    ring_parts: np.ndarray
    part_counts: np.ndarray


def collect_geometry_chunk(
    features_iter: typing.Iterator[typing.Any],
    chunk_size: int,
    maximum_vertices: int,
) -> GeometryChunk | None:
    """Return one bounded chunk of ring geometry from *features_iter*, or None.

    *features_iter* yields GeoJSON geometry dicts (``features.item.geometry`` from
    ijson) and is created once by the caller, because ijson's backends cannot start a
    fresh generator over a partially consumed stream. Collection stops at the feature
    limit or the vertex limit, whichever comes first. Coordinates accumulate into a C
    ``array('d')`` and are returned as a zero-copy numpy view, so the collection holds 8
    bytes per value rather than the ~32 bytes of a Python float list.

    Args:
        features_iter: The ijson geometry iterator.
        chunk_size: The maximum number of features per chunk.
        maximum_vertices: The maximum number of ring vertices per chunk.

    Returns:
        The chunk's ring geometry, or None at the end of the stream.
    """
    flat_coordinates = array("d")
    ring_bounds: list[tuple[int, int]] = []
    ring_parts: list[int] = []
    part_counts: list[int] = []
    part_id = 0
    for geometry in features_iter:
        geometry_type = geometry.get("type")
        coordinates = geometry.get("coordinates")
        if geometry_type == "Polygon":
            polygons = [coordinates]
        elif geometry_type == "MultiPolygon":
            polygons = coordinates
        else:
            continue
        first_part = part_id
        for polygon in polygons:
            for ring in polygon:
                start = len(flat_coordinates)
                for point in ring:
                    flat_coordinates.append(point[0])
                    flat_coordinates.append(point[1])
                ring_bounds.append((start >> 1, len(flat_coordinates) >> 1))
                ring_parts.append(part_id)
            part_id += 1
        part_counts.append(part_id - first_part)
        if (
            len(part_counts) >= chunk_size
            or (len(flat_coordinates) >> 1) >= maximum_vertices
        ):
            break
    if not part_counts:
        return None
    return GeometryChunk(
        coordinates=np.frombuffer(flat_coordinates, dtype=np.float64).reshape(-1, 2),
        ring_bounds=np.asarray(ring_bounds, dtype=np.int64),
        ring_parts=np.asarray(ring_parts, dtype=np.int64),
        part_counts=np.asarray(part_counts, dtype=np.int64),
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
    chunk: GeometryChunk,
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
    chunk: GeometryChunk,
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


def polygon_centroids(chunk: GeometryChunk) -> np.ndarray:
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


def convert_geometry_chunks(
    features_iter: typing.Iterator[typing.Any],
    output: pathlib.Path,
    layer_name: str,
    *,
    first: bool,
) -> int:
    """Convert *features_iter*'s geometry dicts into centroid points at *output*.

    Each bounded chunk's centroid points are appended to the GeoPackage at *output*; the
    first chunk overall creates the file (when *first* is true) and every later chunk
    appends.

    Args:
        features_iter: The ijson geometry iterator, created by the caller.
        output: The GeoPackage path to write to.
        layer_name: The GeoPackage layer.
        first: Whether this is the very first chunk of the whole output file.

    Returns:
        The number of features converted.
    """
    feature_count = 0
    wrote_any = False
    while True:
        chunk = collect_geometry_chunk(
            features_iter,
            FEATURE_CHUNK_SIZE,
            MAXIMUM_VERTICES_PER_CHUNK,
        )
        if chunk is None:
            break
        centroids = polygon_centroids(chunk)
        points = shapely.points(centroids[:, 0], centroids[:, 1])
        pyogrio.raw.write(
            output,
            geometry=shapely.to_wkb(points),
            field_data=np.empty(0),
            fields=np.array([], dtype=object),
            geometry_type="Point",
            crs="EPSG:4326",
            driver="GPKG",
            layer=layer_name,
            append=(not first) or wrote_any,
        )
        wrote_any = True
        feature_count += len(points)
    return feature_count


def convert_zip_members(
    bytes_source: typing.Iterable[bytes],
    output: pathlib.Path,
    layer_name: str,
    *,
    first: bool,
) -> tuple[int, bool]:
    """Convert the GeoJSON members of a zip archive streaming from *bytes_source*.

    Each member named like ``*.geojson`` is parsed and converted; other members are
    consumed so the archive's next member can be read from the stream.

    Args:
        bytes_source: An iterable of byte chunks of the zip archive, in order.
        output: The GeoPackage path to write to.
        layer_name: The GeoPackage layer.
        first: Whether this is the very first chunk of the whole output file.

    Returns:
        The number of features converted and whether any were written.
    """
    feature_count = 0
    wrote_any = False
    for filename, _size, chunks in stream_unzip.stream_unzip(bytes_source):
        if not filename.endswith(GEOJSON_MEMBER_SUFFIX):
            collections.deque(chunks, maxlen=0)
            continue
        features_iter = ijson.items(
            ByteStream(chunks),
            "features.item.geometry",
            use_float=True,
        )
        count = convert_geometry_chunks(
            features_iter,
            output,
            layer_name,
            first=first and not wrote_any,
        )
        wrote_any = wrote_any or count > 0
        feature_count += count
    return feature_count, wrote_any


def convert_zip_stream(
    bytes_source: typing.Iterable[bytes],
    output: pathlib.Path,
    layer_name: str,
    *,
    first: bool,
) -> int:
    """Convert the GeoJSON members of a zip archive streaming from *bytes_source*.

    The first member's first chunk creates *output* when *first* is true; everything
    else appends.

    Args:
        bytes_source: An iterable of byte chunks of the zip archive, in order.
        output: The GeoPackage path to write to.
        layer_name: The GeoPackage layer.
        first: Whether this is the very first chunk of the whole output file.

    Returns:
        The number of features converted.

    Raises:
        ExternalDataError: If the stream is not a zip archive or holds no GeoJSON
            member with any features.
    """
    try:
        feature_count, wrote_any = convert_zip_members(
            bytes_source,
            output,
            layer_name,
            first=first,
        )
    except stream_unzip.UnzipError as error:
        message = f"The streamed archive is not a zip file: {error}"
        raise peri_scribe.exceptions.ExternalDataError(message) from error
    except Exception as error:
        message = f"Failed to read the streamed GeoJSON: {error}"
        raise peri_scribe.exceptions.ExternalDataError(message) from error
    if not wrote_any:
        message = "No GeoJSON data found in the streamed archive"
        raise peri_scribe.exceptions.ExternalDataError(message)
    return feature_count
