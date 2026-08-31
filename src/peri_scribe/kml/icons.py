"""Generating the folder icons embedded in the KMZ output.

Each folder in the output carries a small square icon colored to match the geometry it
holds. The icons are generated in memory as PNG bytes on every KMZ build.
"""

from __future__ import annotations

import struct
import zlib

import peri_scribe.kml.colormap


# Each "Interior" folder's icon is a square of this many pixels on a side.
PROGRESSION_ICON_SIDE_LENGTH_IN_PIXELS = 16

# The "Perimeters" folder icon's background color.
PERIMETERS_ICON_BACKGROUND_COLOR = (0x32, 0x4B, 0x32)

# The "Perimeters" folder icon's line colors: the latest perimeter outline's color on
# top and the penultimate's below. The template's outline perimeters are generated in
# these same colors, so the icon matches the outlines it symbolizes.
LATEST_PERIMETER_COLOR = (0xFF, 0x00, 0x00)
PENULTIMATE_PERIMETER_COLOR = (0xFF, 0xFF, 0x00)


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


def interior_progression_icon() -> bytes:
    """Return the "Interior" folder icon as a PNG.

    The icon is a vertical Turbo gradient: sixteen horizontal one-pixel lines, the top
    line in Turbo's last (hottest) color and the bottom line in Turbo's first (coolest)
    color, with the lines in between linearly interpolated across the full colormap. The
    icon is generated in memory on every KMZ build.

    Returns:
        The icon's PNG bytes.
    """
    side_in_pixels = PROGRESSION_ICON_SIDE_LENGTH_IN_PIXELS
    colors = peri_scribe.kml.colormap.sample_turbo(side_in_pixels)[::-1]
    rows: list[bytes] = []
    for rgb in colors:
        pixel = bytes((*[round(component * 255) for component in rgb], 255))
        rows.append(b"\x00" + pixel * side_in_pixels)
    signature = b"\x89PNG\r\n\x1a\n"
    header = struct.pack(">IIBBBBB", side_in_pixels, side_in_pixels, 8, 6, 0, 0, 0)
    return (
        signature
        + png_chunk(b"IHDR", header)
        + png_chunk(b"IDAT", zlib.compress(b"".join(rows), zlib.Z_BEST_COMPRESSION))
        + png_chunk(b"IEND", b"")
    )


def perimeters_icon() -> bytes:
    """Return the "Perimeters" folder icon as a PNG.

    The icon is a square with a #324B32 background and two horizontal, one-pixel-thick
    lines spanning its full width: a line a third of the way down from the top colored
    like the latest perimeter outline and a line a third of the way up from the bottom
    colored like the penultimate perimeter outline. The icon is generated in memory on
    every KMZ build.

    Returns:
        The icon's PNG bytes.
    """
    side_in_pixels = PROGRESSION_ICON_SIDE_LENGTH_IN_PIXELS
    top_line_row = side_in_pixels // 3
    bottom_line_row = side_in_pixels - 1 - top_line_row
    background_pixel = bytes((*PERIMETERS_ICON_BACKGROUND_COLOR, 255))
    rows: list[bytes] = []
    for row_index in range(side_in_pixels):
        if row_index == top_line_row:
            row = b"\x00" + bytes((*LATEST_PERIMETER_COLOR, 255)) * side_in_pixels
        elif row_index == bottom_line_row:
            row = b"\x00" + bytes((*PENULTIMATE_PERIMETER_COLOR, 255)) * side_in_pixels
        else:
            row = b"\x00" + background_pixel * side_in_pixels
        rows.append(row)
    signature = b"\x89PNG\r\n\x1a\n"
    header = struct.pack(">IIBBBBB", side_in_pixels, side_in_pixels, 8, 6, 0, 0, 0)
    return (
        signature
        + png_chunk(b"IHDR", header)
        + png_chunk(b"IDAT", zlib.compress(b"".join(rows), zlib.Z_BEST_COMPRESSION))
        + png_chunk(b"IEND", b"")
    )
