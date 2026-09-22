"""Supply folder and perimeter icons embedded in the KMZ output.

Each folder in the output carries a small square icon colored to match the geometry it
holds. All icons are generated in memory on every KMZ build. Perimeter icons use
four-pixel diagonal lines, one-pixel black outlines, and transparent backgrounds.
"""

from __future__ import annotations

import dataclasses
import struct
import typing
import zlib

import numpy as np

import peri_scribe.kml.colormap
from measurement_units import units


if typing.TYPE_CHECKING:
    import pint


# Each "Interior" folder's icon is a square of this many pixels on a side.
PROGRESSION_ICON_SIDE_LENGTH = 16 * units.pixels

PERIMETER_ICON_SIDE_LENGTH = 16 * units.pixels
PERIMETER_ICON_LINE_WIDTH = 4 * units.pixels
PERIMETER_ICON_OUTLINE_WIDTH = 1 * units.pixels

# Subpixel sampling preserves smooth edges at list-icon sizes.
ICON_SAMPLES_PER_PIXEL_SIDE = 16

# The eight bytes every PNG file starts with.
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


@dataclasses.dataclass(frozen=True, kw_only=True)
class DiagonalLine:
    """Keep each icon stroke's color and placement together.

    Attributes:
        color: The stroke color as ``#RRGGBB``.
        center: The midpoint's shared horizontal and vertical coordinate.
        half_span: The horizontal and vertical offset from the midpoint to either end.
    """

    color: str
    center: pint.Quantity[float]
    half_span: pint.Quantity[float]


def interior_progression_icon_filename() -> str:
    """Return the filename of the "Interior" folder's icon.

    Returns:
        The icon filename.
    """
    return "interior-progression.png"


def perimeters_icon_filename() -> str:
    """Return the filename of the "Perimeters" folder's icon.

    Returns:
        The icon filename.
    """
    return "perimeters.png"


def outlined_perimeter_icon_filename(color: str) -> str:
    """Keep each outline's list icon reference stable across KMZ builds.

    Args:
        color: The outline color as ``#RRGGBB``.

    Returns:
        The matching PNG filename in the archive.
    """
    return f"perimeter-outline-{color[1:].lower()}.png"


def outlined_perimeter_icon(color: str) -> bytes:
    """Match a perimeter's list entry to its outline color.

    Args:
        color: The outline color as ``#RRGGBB``.

    Returns:
        The icon's PNG bytes.
    """
    return diagonal_lines_icon((
        DiagonalLine(
            color=color,
            center=PERIMETER_ICON_SIDE_LENGTH / 2,
            half_span=5 * units.pixels,
        ),
    ))


def diagonal_lines_icon(lines: tuple[DiagonalLine, ...]) -> bytes:
    """Keep colored strokes visible on any background with smooth black borders.

    Args:
        lines: Diagonal strokes in back-to-front drawing order.

    Returns:
        A transparent PNG with round-ended, outlined strokes.
    """
    side = int(PERIMETER_ICON_SIDE_LENGTH.m_as("pixels"))
    samples = ICON_SAMPLES_PER_PIXEL_SIDE
    rows, columns = (np.indices((side * samples, side * samples)) + 0.5) / samples
    image = np.zeros((side * samples, side * samples, 4), dtype=np.uint8)
    radius = PERIMETER_ICON_LINE_WIDTH.m_as("pixels") / 2
    outer_radius = radius + PERIMETER_ICON_OUTLINE_WIDTH.m_as("pixels")
    for line in lines:
        center = line.center.m_as("pixels")
        half_span = line.half_span.m_as("pixels")
        position = np.clip((columns - rows) / 2, -half_span, half_span)
        distance_squared = (columns - center - position) ** 2 + (
            rows - center + position
        ) ** 2
        image[distance_squared <= outer_radius**2] = (0, 0, 0, 255)
        image[distance_squared <= radius**2] = (*bytes.fromhex(line.color[1:]), 255)

    totals = image.reshape(side, samples, side, samples, 4).sum(axis=(1, 3))
    covered = totals[:, :, 3:4] / 255
    # Unpremultiplied channels let partially covered pixels blend on any background.
    colors = np.divide(
        totals[:, :, :3],
        covered,
        out=np.zeros((side, side, 3)),
        where=covered > 0,
    )
    pixels = np.concatenate((colors, 255 * covered / samples**2), axis=2)
    pixels = np.rint(pixels).astype(np.uint8)
    return png_from_rows([b"\x00" + row.tobytes() for row in pixels], side)


def png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    """Return one PNG chunk with its length, type, data, and CRC.

    Args:
        chunk_type: The chunk's four-byte type.
        data: The chunk's payload.

    Returns:
        The serialized chunk.
    """
    crc = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", crc)


def png_from_rows(rows: list[bytes], side_in_pixels: int) -> bytes:
    """Return an eight-bit RGBA PNG holding *rows* as its scanlines.

    Args:
        rows: One scanline per row, each a filter byte followed by the row's pixels.
        side_in_pixels: The icon's width and height in pixels.

    Returns:
        The icon's PNG bytes.
    """
    header = struct.pack(">IIBBBBB", side_in_pixels, side_in_pixels, 8, 6, 0, 0, 0)
    return (
        PNG_SIGNATURE
        + png_chunk(b"IHDR", header)
        + png_chunk(b"IDAT", zlib.compress(b"".join(rows), zlib.Z_BEST_COMPRESSION))
        + png_chunk(b"IEND", b"")
    )


def interior_progression_icon() -> bytes:
    """Return the "Interior" folder icon as a PNG.

    The icon is a vertical Turbo gradient: sixteen horizontal one-pixel lines, the top
    line in Turbo's last (hottest) color and the bottom line in Turbo's first (coolest)
    color, with the lines in between linearly interpolated across the full colormap. The
    icon is generated in memory on every KMZ build.

    Returns:
        The icon's PNG bytes.
    """
    side_in_pixels = int(PROGRESSION_ICON_SIDE_LENGTH.magnitude)
    colors = peri_scribe.kml.colormap.sample_turbo(side_in_pixels)[::-1]
    rows: list[bytes] = []
    for rgb in colors:
        pixel = bytes((*[round(component * 255) for component in rgb], 255))
        rows.append(b"\x00" + pixel * side_in_pixels)
    return png_from_rows(rows, side_in_pixels)


def perimeters_icon() -> bytes:
    """Return the "Perimeters" folder icon as a PNG.

    Red and yellow diagonal lines match the latest and penultimate perimeters. Each
    four-pixel line has a one-pixel black outline so it remains visible against any
    background.

    Returns:
        The icon's PNG bytes.
    """
    return diagonal_lines_icon((
        DiagonalLine(
            color="#FF0000",
            center=5.25 * units.pixels,
            half_span=2.25 * units.pixels,
        ),
        DiagonalLine(
            color="#FFFF00",
            center=10.75 * units.pixels,
            half_span=2.25 * units.pixels,
        ),
    ))
