"""Publish complete KMZ archives while streaming their document contents."""

from __future__ import annotations

import io
import pathlib
import tempfile
import typing
import zipfile


KMZ_DOCUMENT_FILENAME = "doc.kml"

# DEFLATE is the compression Google Earth expects inside a KMZ. Level 6 is used instead
# of the maximum 9: the output is within 1% of level 9's size but compresses several
# times faster.
KMZ_COMPRESSION = zipfile.ZIP_DEFLATED
KMZ_COMPRESSION_LEVEL = 6

# Raster formats that are already compressed, so passing them through DEFLATE again
# costs time for no size benefit. Everything else the archive carries -- the KML
# document and the SVG plots -- is text, which DEFLATE shrinks by roughly two thirds.
ALREADY_COMPRESSED_IMAGE_SUFFIXES = (".gif", ".jpeg", ".jpg", ".png")


def write_kmz(
    path: pathlib.Path,
    write_document: typing.Callable[[typing.TextIO], object],
    images: typing.Mapping[str, bytes] | None = None,
) -> None:
    """Write the generated document and *images* as a compressed KMZ file at *path*.

    Args:
        path: The KMZ file to write.
        write_document: A renderer that writes XML to the supplied stream.
        images: Each plot image's filename and its bytes, or None for none.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=path.parent) as directory:
        temporary = pathlib.Path(directory) / path.name
        write_archive(temporary, write_document, images)
        temporary.replace(path)


def write_archive(
    path: pathlib.Path,
    write_document: typing.Callable[[typing.TextIO], object],
    images: typing.Mapping[str, bytes] | None,
) -> None:
    """Keep incomplete archive bytes away from the public KMZ path.

    Args:
        path: The temporary archive path, separate from the published KMZ.
        write_document: A renderer that writes XML to the supplied stream.
        images: Plot image filenames and bytes, or None when no images are needed.
    """
    with zipfile.ZipFile(
        path,
        "w",
        compression=KMZ_COMPRESSION,
        compresslevel=KMZ_COMPRESSION_LEVEL,
        allowZip64=False,
    ) as archive:
        with (
            archive.open(KMZ_DOCUMENT_FILENAME, "w") as member,
            io.TextIOWrapper(member, encoding="utf-8", newline="") as stream,
        ):
            write_document(stream)
        if images:
            for filename, content in images.items():
                archive.writestr(
                    filename,
                    content,
                    compress_type=(
                        zipfile.ZIP_STORED
                        if filename.casefold().endswith(
                            ALREADY_COMPRESSED_IMAGE_SUFFIXES,
                        )
                        else KMZ_COMPRESSION
                    ),
                )
