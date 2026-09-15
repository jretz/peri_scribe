"""Shared geometry chunks keep streaming and centroid calculations independent."""

from __future__ import annotations

import dataclasses
import typing


if typing.TYPE_CHECKING:
    import numpy as np


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
