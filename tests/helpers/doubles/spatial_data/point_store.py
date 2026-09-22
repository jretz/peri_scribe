"""Exercise reusable spatial operations."""

from __future__ import annotations

import sqlite3
import typing


if typing.TYPE_CHECKING:
    import numpy as np


def make_tile_read_recorder(
    *,
    identifiers: list[int],
    read_tile_points: typing.Callable[..., np.ndarray | None],
) -> typing.Callable[..., np.ndarray | None]:
    """Create a callback with controlled dependencies.

    Count tile reads while preserving real point coordinates.

    Args:
        identifiers: Shared list recording point tiles read from storage.
        read_tile_points: Original tile reader used to preserve stored point
            coordinates.

    Returns:
        The callback bound to the supplied dependencies.
    """

    def read(connection: sqlite3.Connection, tile_id: int) -> np.ndarray | None:
        """Count tile reads while preserving real point coordinates.

        Args:
            connection: Open point-database connection used for the tile read.
            tile_id: Identifier of the point tile to read.

        Returns:
            The point coordinates stored in the selected tile.
        """
        identifiers.append(tile_id)
        return read_tile_points(connection, tile_id)

    return read
