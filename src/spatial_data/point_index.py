"""Amortize envelope selection across queries sharing a decoded point tile.

[Adaptive point queries](../../docs/algorithms/adaptive-point-queries.md) explains why
sorting retains duplicate points and inclusive coordinate boundaries.
"""

from __future__ import annotations

import dataclasses

import numpy as np


MINIMUM_INDEXED_QUERIES = 8


@dataclasses.dataclass(frozen=True, kw_only=True)
class LongitudeIndex:
    """Retain a tile's encoded points in numeric longitude order.

    The contiguous longitude array avoids repeated strided copies during searches.
    Coordinates retain the point store's signed integers in units of 1e-5 degrees.

    Attributes:
        points: Owned, sorted ``(n, 2)`` int32 coordinate pairs, including duplicates.
        longitudes: Contiguous int64 longitudes aligned with the sorted points.
    """

    points: np.ndarray
    longitudes: np.ndarray

    @classmethod
    def build(cls, points: np.ndarray) -> LongitudeIndex:
        """Copy one tile so numeric sorting cannot modify the decoded source array.

        Args:
            points: The tile's ``(n, 2)`` int32 encoded coordinate pairs.

        Returns:
            An owned index preserving every input occurrence.
        """
        ordered = points[np.argsort(points[:, 0])]
        longitudes = ordered[:, 0].astype(np.int64)
        ordered.flags.writeable = False
        longitudes.flags.writeable = False
        return cls(points=ordered, longitudes=longitudes)

    def select(self, box: tuple[int, int, int, int]) -> np.ndarray:
        """Keep both envelope endpoints and every duplicate for exact containment.

        Args:
            box: Encoded minimum longitude, minimum latitude, maximum longitude, and
                maximum latitude, in the point store's integer coordinate units.

        Returns:
            Matching coordinate pairs in longitude order, with original multiplicity.
        """
        minimum_longitude, minimum_latitude, maximum_longitude, maximum_latitude = box
        first = np.searchsorted(self.longitudes, minimum_longitude)
        last = np.searchsorted(self.longitudes, maximum_longitude, side="right")
        window = self.points[first:last]
        return window[
            (window[:, 1] >= minimum_latitude) & (window[:, 1] <= maximum_latitude)
        ]
