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


def make_interrupted_archive_writer(
    *,
    output: pathlib.Path,
    previous: bytes,
) -> typing.Callable[..., None]:
    """Create a callback to simulate a disk failure while the archive is incomplete.

    Args:
        output: Output path used by the controlled write or renderer.
        previous: Complete archive contents that must survive a failed replacement.

    Returns:
        The callback bound to the supplied dependencies.
    """

    def fail_after_partial_write(
        path: pathlib.Path,
        _text: str,
        _images: object,
    ) -> None:
        """Simulate a disk failure while the archive is incomplete.

        Args:
            path: The temporary archive path where the partial write occurs.
            _text: The KML document accepted to match the writer's signature; unused.
            _images: The plot images accepted to match the writer's signature; unused.

        Raises:
            OSError: After the incomplete archive is written.
        """
        path.write_bytes(b"partial archive")
        assert output.read_bytes() == previous
        message = "disk failure"
        raise OSError(message)

    return fail_after_partial_write


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


def interrupted_document(stream: typing.TextIO) -> None:
    """Fail after emitting XML to exercise cleanup of an open ZIP member.

    Args:
        stream: The actual streaming archive member.

    Raises:
        ValueError: After part of the XML has been emitted.
    """
    stream.write("<kml><Document>")
    message = "serialization failed"
    raise ValueError(message)
