"""Provide data builders and stand-ins for reading tests."""

from __future__ import annotations

import pathlib
import typing

import numpy as np
import shapely

import tests.factories


if typing.TYPE_CHECKING:
    import geopandas


def write_sparse_layer(path: pathlib.Path, identifiers: list[int]) -> None:
    """Create real GeoPackage rows whose primary keys need not be contiguous.

    Args:
        path: The isolated GeoPackage path to write.
        identifiers: Unique positive feature ids, potentially in arbitrary order.
    """
    frame = tests.factories.geo_frame(
        {
            "fid": np.asarray(identifiers, dtype=np.int64),
            "value": np.asarray(identifiers, dtype=np.int64),
        },
        [shapely.Point(identifier / 1000, 0) for identifier in identifiers],
    )
    frame.to_file(path, layer="features")


def make_recording_layer_reader(
    *,
    calls: list[tuple[pathlib.Path, str]],
    frame: geopandas.GeoDataFrame,
) -> typing.Callable[..., geopandas.GeoDataFrame]:
    """Create a callback to capture the selected GeoPackage path and layer.

    Args:
        calls: Shared list recording dependency calls for assertions.
        frame: Dataframe returned by the layer reader.

    Returns:
        The callback bound to the supplied dependencies.
    """

    def read_file(read_path: pathlib.Path, *, layer: str) -> geopandas.GeoDataFrame:
        """Capture the selected GeoPackage path and layer.

        Args:
            read_path: GeoPackage path requested by the layer reader.
            layer: Layer name requested within the GeoPackage.

        Returns:
            The dataframe configured for this reader test.
        """
        calls.append((read_path, layer))
        return frame

    return read_file
