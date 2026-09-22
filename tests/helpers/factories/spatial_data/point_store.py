"""Exercise reusable spatial operations."""

from __future__ import annotations

import pathlib
import tempfile
import typing

import spatial_data.point_store


if typing.TYPE_CHECKING:
    import numpy as np


def write_database(points: np.ndarray, path: pathlib.Path) -> None:
    """Build a compact point database at *path* holding *points*.

    The points are appended to temporary partition files and processed through the
    production database build, so the resulting file is a real compact database.

    Args:
        points: The ``(n, 2)`` longitude/latitude pairs in degrees.
        path: The database path to write.
    """
    with tempfile.TemporaryDirectory() as temporary_directory:
        partition_directory = pathlib.Path(temporary_directory)
        with spatial_data.point_store.PartitionFiles(
            partition_directory,
        ) as partition_files:
            spatial_data.point_store.append_centroids_to_partitions(
                points,
                partition_files,
            )
        spatial_data.point_store.build_tiles_database(partition_directory, path)


QUANTIZED_ONE_POINT_FIVE_DEGREES = 150_000


QUANTIZED_NEGATIVE_HALF_DEGREE = -50_000


QUANTIZED_FORTY_POINT_TWENTY_FIVE_DEGREES = 4_025_000


QUANTIZED_NEGATIVE_NINETY_DEGREES = -9_000_000


QUANTIZED_HALF_DEGREE = 50_000
