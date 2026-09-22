"""Interrupt archive writes to verify complete outputs survive failures."""

from __future__ import annotations

import pathlib
import typing


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
        _write_document: typing.Callable[[typing.TextIO], object],
        _images: object,
    ) -> None:
        """Simulate a disk failure while the archive is incomplete.

        Args:
            path: The temporary archive path where the partial write occurs.
            _write_document: The renderer accepted to match the writer's signature.
            _images: The plot images accepted to match the writer's signature; unused.

        Raises:
            OSError: After the incomplete archive is written.
        """
        path.write_bytes(b"partial archive")
        assert output.read_bytes() == previous
        message = "disk failure"
        raise OSError(message)

    return fail_after_partial_write


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
