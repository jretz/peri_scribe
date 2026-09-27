"""Exact centroid moments and streamed artifacts connect the proofs to real geometry."""

from __future__ import annotations

import itertools
import json
import pathlib
import typing

import numpy as np
import pyogrio

import spatial_data.centroid_data
import spatial_data.centroid_math
import spatial_data.centroid_streaming
import tests.formal.helpers.oracle
import tests.helpers.factories.spatial_data.centroid_streaming


if typing.TYPE_CHECKING:
    import pytest


type Point = tuple[int, int]
type Ring = tuple[Point, ...]
type Polygon = tuple[Ring, ...]
type Feature = tuple[Polygon, ...]


OUTER: Ring = ((0, 0), (12, 0), (12, 10), (0, 10), (0, 0))
HOLE: Ring = ((1, 1), (4, 1), (4, 3), (1, 3), (1, 1))
PART: Ring = ((15, 0), (19, 0), (19, 2), (15, 2), (15, 0))
CONCAVE: Ring = ((0, 0), (8, 0), (8, 2), (2, 2), (2, 7), (0, 7), (0, 0))
DEGENERATE: Ring = ((0, 0), (3, 0), (9, 0), (0, 0))


def cases() -> list[Feature]:
    """Exercise holes, unequal parts, winding, ring anchors and large offsets.

    Returns:
        Integer projected geometry independent of the vectorized implementation.
    """
    shapes: tuple[Feature, ...] = (
        ((OUTER,),),
        ((OUTER, HOLE),),
        ((OUTER, HOLE), (PART,)),
        ((CONCAVE,),),
        ((DEGENERATE,),),
    )
    results: list[Feature] = []
    for shape, offset, rotation, winding in itertools.product(
        shapes,
        ((0, 0), (12_000_000, -5_000_000), (-12_000_000, 5_000_000)),
        (0, 1, 2),
        (0, 1, 2, 3),
    ):
        polygons = []
        for polygon in shape:
            rings = []
            for index, ring in enumerate(polygon):
                vertices = ring[:-1]
                if winding & (1 << index):
                    vertices = tuple(reversed(vertices))
                vertices = vertices[rotation:] + vertices[:rotation]
                rings.append(
                    tuple(
                        (point[0] + offset[0], point[1] + offset[1])
                        for point in (*vertices, vertices[0])
                    ),
                )
            polygons.append(tuple(rings))
        results.append(tuple(polygons))
    return results


def command(feature: Feature) -> str:
    """Send the complete integer footprint to Lean without rounding centroid results.

    Args:
        feature: Polygon parts with positional exterior and hole rings.

    Returns:
        One executable-reference request.
    """
    return "centroid " + " ".join(
        "|".join(";".join(f"{x},{y}" for x, y in ring) for ring in polygon)
        for polygon in feature
    )


def geometry(feature: Feature, *, geographic: bool = False) -> dict[str, object]:
    """Keep coordinate projection real when exercising the complete ZIP converter.

    Args:
        feature: Integer geometry in projected meters.
        geographic: Whether to inverse-project inputs to GeoJSON longitude/latitude.

    Returns:
        A polygon or multipolygon GeoJSON geometry.
    """
    polygons = []
    for polygon in feature:
        rings = []
        for ring in polygon:
            points = np.asarray(ring, dtype=float)
            if geographic:
                points = np.column_stack(
                    spatial_data.centroid_math.TO_WGS84.transform(
                        points[:, 0],
                        points[:, 1],
                    ),
                )
            rings.append(points.tolist())
        polygons.append(rings)
    return {
        "type": "Polygon" if len(polygons) == 1 else "MultiPolygon",
        "coordinates": polygons[0] if len(polygons) == 1 else polygons,
    }


def exact_centroids(features: list[Feature]) -> np.ndarray:
    """Evaluate the checked area-versus-vertex-mean policy for each complete feature.

    Args:
        features: Ordered footprints including repeated features.

    Returns:
        Exact rational centroids rounded once to doubles for comparison.
    """
    results = tests.formal.helpers.oracle.evaluate(
        [command(feature) for feature in features],
        executable="oracleObservers",
    )
    return np.asarray([
        (horizontal / denominator, vertical / denominator)
        for _area, horizontal, vertical, denominator in results
    ])


def replay_math() -> None:
    """Compare every vectorized ring/part/feature result with the Lean expression."""
    features = cases()
    expected = exact_centroids(features)
    iterator = iter(geometry(feature) for feature in features)
    chunk = spatial_data.centroid_streaming.collect_geometry_chunk(
        iterator,
        len(features),
        1_000_000,
    )
    assert chunk is not None
    sums = spatial_data.centroid_math.ring_centroid_sums(
        chunk.coordinates,
        chunk.ring_bounds,
    )
    actual = spatial_data.centroid_math.projected_centroids(
        chunk.coordinates,
        chunk,
        sums,
    )
    np.testing.assert_allclose(actual, expected, rtol=0, atol=2e-9)
    assert (
        spatial_data.centroid_streaming.collect_geometry_chunk(iterator, 1, 1) is None
    )


def reconstructed_geometry(
    chunk: spatial_data.centroid_data.GeometryChunk,
) -> list[dict[str, object]]:
    """Recover feature ownership from stored ring and part boundaries.

    Args:
        chunk: The actual collected arrays, before centroid aggregation.

    Returns:
        Complete ordered GeoJSON geometry, including every ring vertex.
    """
    reconstructed: list[dict[str, object]] = []
    ring_index = 0
    for parts in chunk.part_counts:
        polygons = []
        for _ in range(parts):
            owner = chunk.ring_parts[ring_index]
            rings = []
            while ring_index < len(chunk.ring_parts) and (
                chunk.ring_parts[ring_index] == owner
            ):
                start, end = chunk.ring_bounds[ring_index]
                rings.append(chunk.coordinates[start:end].tolist())
                ring_index += 1
            polygons.append(rings)
        reconstructed.append({
            "type": "Polygon" if len(polygons) == 1 else "MultiPolygon",
            "coordinates": polygons[0] if len(polygons) == 1 else polygons,
        })
    return reconstructed


def replay_chunks(limit: int, budget: int) -> None:
    """Compare actual collected geometry with the proved greedy whole-feature split.

    Args:
        limit: Maximum features before publishing a chunk.
        budget: Vertex threshold checked after accepting each complete feature.
    """
    features = [((OUTER,),), ((OUTER, HOLE), (PART,)), ((PART,),), ((OUTER,),)]
    shapes = [geometry(feature) for feature in features]
    inputs = [shapes[0], {"type": "Point", "coordinates": [0, 0]}, *shapes[1:]]
    vertex_counts = [5, 1, 15, 5, 5]
    encoded = " ".join(
        f"{index},{vertices},{int(index != 1)}"
        for index, vertices in enumerate(vertex_counts)
    )
    result = tests.formal.helpers.oracle.evaluate(
        [f"chunks {limit} {budget} {encoded}"],
        executable="oracleObservers",
    )[0]
    expected = []
    position = 0
    while position < len(result):
        length = result[position]
        expected.append(result[position + 1 : position + 1 + length])
        position += length + 1
    iterator = iter(inputs)
    consumed = []
    for identities in expected:
        chunk = spatial_data.centroid_streaming.collect_geometry_chunk(
            iterator,
            limit,
            budget,
        )
        assert chunk is not None
        reconstructed = reconstructed_geometry(chunk)
        assert reconstructed == [inputs[index] for index in identities]
        assert len(reconstructed) <= max(1, limit)
        consumed.extend(identities)
    assert consumed == [0, 2, 3, 4]
    assert (
        spatial_data.centroid_streaming.collect_geometry_chunk(
            iterator,
            limit,
            budget,
        )
        is None
    )


def replay_archive(
    directory: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    byte_chunk: int,
    feature_limit: int,
    vertex_budget: int,
) -> None:
    """Read actual ZIP/JSON bytes and verify ordered points in the written GeoPackage.

    Args:
        directory: Isolated output location.
        monkeypatch: Per-case conversion budget overrides.
        byte_chunk: ZIP transport fragmentation size.
        feature_limit: Whole-feature chunk limit.
        vertex_budget: Vertex threshold between features.
    """
    features = [cases()[index] for index in (0, 48, 84, 108, 144, 84)]
    geometries = [geometry(feature, geographic=True) for feature in features]
    members = {}
    for index, group in enumerate((geometries[:2], geometries[2:3], geometries[3:])):
        members[f"{index}.geojson"] = json.dumps({
            "features": [{"geometry": item} for item in group],
        }).encode()
        members[f"{index}.txt"] = b"ignored archive member" * 20
    archive = tests.helpers.factories.spatial_data.centroid_streaming.archive_bytes(
        members,
    )
    chunks = (
        archive[index : index + byte_chunk]
        for index in range(0, len(archive), byte_chunk)
    )
    monkeypatch.setattr(
        spatial_data.centroid_streaming,
        "FEATURE_CHUNK_SIZE",
        feature_limit,
    )
    monkeypatch.setattr(
        spatial_data.centroid_streaming,
        "MAXIMUM_VERTICES_PER_CHUNK",
        vertex_budget,
    )
    output = directory / "centroids.gpkg"
    count = spatial_data.centroid_streaming.convert_zip_stream(
        chunks,
        output,
        "buildings",
        first=True,
    )
    assert count == len(features)
    actual = pyogrio.read_dataframe(output, layer="buildings")
    projected = np.column_stack(
        spatial_data.centroid_math.TO_WEB_MERCATOR.transform(
            actual.geometry.x.to_numpy(),
            actual.geometry.y.to_numpy(),
        ),
    )
    np.testing.assert_allclose(projected, exact_centroids(features), rtol=0, atol=2e-7)
