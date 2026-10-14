"""Shared geometry chunks keep streaming and centroid calculations independent.

[Building centroid reasoning](../../docs/algorithms/building-centroids.md)
explains the contract and correctness argument.
"""

from __future__ import annotations

import dataclasses
import typing


if typing.TYPE_CHECKING:
    import numpy as np


@dataclasses.dataclass(frozen=True, kw_only=True)
class GeometryChunk:
    """Ring coordinates and polygon boundaries for one chunk of a GeoJSON stream.

    ``coordinates`` joins every ring's coordinates in an ``(M, 2)`` float64 array.
    ``ring_bounds`` gives each ring's ``[start, end)`` slice as an ``(R, 2)`` int64
    array. Rings are closed, so their first and last points coincide.

    ``ring_parts`` identifies the polygon each ring belongs to. A polygon's first ring
    is its exterior; any others are holes. ``part_counts`` records how many polygons
    belong to each feature, so the same representation handles polygons and
    multipolygons.
    """

    coordinates: np.ndarray
    ring_bounds: np.ndarray
    ring_parts: np.ndarray
    part_counts: np.ndarray
