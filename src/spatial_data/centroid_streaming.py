"""Convert polygon archives without keeping a whole archive in memory.

Decompressed GeoJSON archives can exceed available memory. ``stream_unzip`` decompresses
each member as bytes arrive, and parsed geometries go directly into centroid conversion.
Neither the archive nor its GeoJSON is written to disk. Chunks end between features to
keep polygons intact, so one large feature can exceed the vertex threshold.

Centroids are computed in EPSG:3857 and then converted back to WGS84. Large projected
coordinates can lose precision in the shoelace sums: coordinates may be around 10^7
meters while a small polygon's double area is only around 10^3 square meters.
Subtracting nearly equal large products can then distort the result. Moving each ring's
first point to the origin reduces that cancellation. Its area-weighted offset restores
the position when the rings are combined.

[Building centroid reasoning](../../docs/algorithms/building-centroids.md)
explains the contract and correctness argument.
"""

from __future__ import annotations

import array
import collections
import pathlib
import typing

import ijson
import numpy as np
import pyogrio
import shapely
import stream_unzip

import spatial_data.centroid_data
import spatial_data.centroid_math
import spatial_data.exceptions
import spatial_data.reference


# The maximum number of features per conversion chunk.

FEATURE_CHUNK_SIZE = 100_000


MAXIMUM_VERTICES_PER_CHUNK = 2_000_000


GEOJSON_MEMBER_SUFFIX = b".geojson"


def collect_geometry_chunk(
    features_iter: typing.Iterator[typing.Any],
    chunk_size: int,
    maximum_vertices: int,
) -> spatial_data.centroid_data.GeometryChunk | None:
    """Return the next chunk of ring geometry from *features_iter*, or None.

    The caller creates one ijson iterator over ``features.item.geometry`` and keeps
    using it: ijson's backends cannot start a new generator partway through the same
    stream. Collection stops after the feature that reaches either the feature limit or
    the vertex threshold, so a complete feature can take the chunk over that threshold.

    Coordinates accumulate in ``array.array('d')`` and become a NumPy view without
    copying. Each value occupies 8 bytes there; a list of Python floats would also need
    space for the individual float objects and their references.

    Args:
        features_iter: The ijson geometry iterator.
        chunk_size: The maximum number of features per chunk.
        maximum_vertices: The vertex threshold checked after each complete feature.

    Returns:
        The chunk's ring geometry, or None at the end of the stream.
    """
    flat_coordinates = array.array("d")
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
    return spatial_data.centroid_data.GeometryChunk(
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
    for centroids in centroid_chunks(features_iter):
        points = shapely.points(centroids[:, 0], centroids[:, 1])
        pyogrio.raw.write(
            output,
            geometry=shapely.to_wkb(points),
            field_data=np.empty(0),
            fields=np.array([], dtype=object),
            geometry_type="Point",
            crs=str(spatial_data.reference.WGS84_SPATIAL_REFERENCE),
            driver="GPKG",
            layer=layer_name,
            append=(not first) or feature_count > 0,
        )
        feature_count += len(points)
    return feature_count


def centroid_chunks(
    features: typing.Iterator[typing.Any],
) -> typing.Iterator[np.ndarray]:
    """Convert geometries in chunks, keeping each feature intact.

    The feature limit and vertex threshold keep ordinary chunks small. A single large
    feature can exceed the vertex threshold because splitting a polygon would change its
    centroid.

    Args:
        features: A single-pass stream of GeoJSON geometries.

    Yields:
        Centroid arrays in source order, with one point per polygon or multipolygon
        feature in each chunk. Other geometry types are skipped.
    """
    while (
        chunk := collect_geometry_chunk(
            features,
            FEATURE_CHUNK_SIZE,
            MAXIMUM_VERTICES_PER_CHUNK,
        )
    ) is not None:
        centroids = spatial_data.centroid_math.polygon_centroids(chunk)
        del chunk
        yield centroids


def zip_geometries(bytes_source: typing.Iterable[bytes]) -> typing.Iterator[typing.Any]:
    """Finish every ZIP member before advancing to the next member.

    Args:
        bytes_source: Compressed archive bytes in source order.

    Yields:
        GeoJSON geometries from every matching archive member.
    """
    for filename, _size, chunks in stream_unzip.stream_unzip(bytes_source):
        if filename.endswith(GEOJSON_MEMBER_SUFFIX):
            yield from ijson.items(
                ijson.from_iter(chunks),
                "features.item.geometry",
                use_float=True,
            )
        else:
            collections.deque(chunks, maxlen=0)


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
        GeometryStreamError: If the stream cannot be read or holds no GeoJSON member
            with convertible polygon features.
    """
    try:
        feature_count = convert_geometry_chunks(
            zip_geometries(bytes_source),
            output,
            layer_name,
            first=first,
        )
    except stream_unzip.UnzipError as error:
        message = f"Failed to read the streamed ZIP archive: {error}"
        raise spatial_data.exceptions.GeometryStreamError(message) from error
    except Exception as error:
        message = f"Failed to read the streamed GeoJSON: {error}"
        raise spatial_data.exceptions.GeometryStreamError(message) from error
    if not feature_count:
        message = "No GeoJSON data found in the streamed archive"
        raise spatial_data.exceptions.GeometryStreamError(message)
    return feature_count
