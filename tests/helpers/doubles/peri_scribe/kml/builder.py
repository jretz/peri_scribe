"""Replace builder dependencies with controlled test doubles."""

from __future__ import annotations

import io
import pathlib
import typing


if typing.TYPE_CHECKING:
    import geopandas


def make_history_layer_reader(
    *,
    perimeters: geopandas.GeoDataFrame,
    points: geopandas.GeoDataFrame,
) -> typing.Callable[..., geopandas.GeoDataFrame]:
    """Create a callback to isolate derived-layer reads from persistent geography.

    Args:
        perimeters: Perimeter history returned for the perimeter layer.
        points: Point history returned for the point layer.

    Returns:
        The callback bound to the supplied dependencies.
    """

    def read_layer(_path: pathlib.Path, layer_name: str) -> geopandas.GeoDataFrame:
        """Isolate derived-layer reads from persistent geography.

        Args:
            _path: The requested path, without reading its contents.
            layer_name: The requested history layer.

        Returns:
            The synthetic history frame used by this scenario.
        """
        return perimeters if layer_name == "perimeter_history" else points

    return read_layer


def render_document(write: typing.Callable[[typing.TextIO], object]) -> str:
    """Inspect a lazy document callback without writing a public archive.

    Args:
        write: The renderer handed to the archive boundary.

    Returns:
        Its generated document text.
    """
    with io.StringIO() as stream:
        write(stream)
        return stream.getvalue()
