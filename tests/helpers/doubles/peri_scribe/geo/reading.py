"""Replace reading dependencies with controlled test doubles."""

from __future__ import annotations

import pathlib
import typing


if typing.TYPE_CHECKING:
    import geopandas


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
