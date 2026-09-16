"""Build inputs for reading tests."""

from __future__ import annotations

import pathlib

import numpy as np
import shapely

import tests.helpers.factories.geography


def write_sparse_layer(path: pathlib.Path, identifiers: list[int]) -> None:
    """Create real GeoPackage rows whose primary keys need not be contiguous.

    Args:
        path: The isolated GeoPackage path to write.
        identifiers: Unique positive feature ids, potentially in arbitrary order.
    """
    frame = tests.helpers.factories.geography.geo_frame(
        {
            "fid": np.asarray(identifiers, dtype=np.int64),
            "value": np.asarray(identifiers, dtype=np.int64),
        },
        [shapely.Point(identifier / 1000, 0) for identifier in identifiers],
    )
    frame.to_file(path, layer="features")
