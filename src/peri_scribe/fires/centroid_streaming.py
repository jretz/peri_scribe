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
import shapely
import stream_unzip

import peri_scribe.exceptions
import peri_scribe.fires.centroid_math


# The maximum number of features per conversion chunk.

FEATURE_CHUNK_SIZE = 100_000


MAXIMUM_VERTICES_PER_CHUNK = 2_000_000


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
        centroids = peri_scribe.fires.centroid_math.polygon_centroids(chunk)
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
