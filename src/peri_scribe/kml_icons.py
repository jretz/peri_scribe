"""Generating the folder icons embedded in the KMZ output.

Each folder in the output carries a small square icon colored to match the geometry it
holds. The icons are generated in memory as PNG bytes on every KMZ build.
"""

from __future__ import annotations

import struct
import zlib

import peri_scribe.kml_template
import peri_scribe.kml_template_reader
import peri_scribe.perimeter_progression


# Each progression-map subfolder's icon is a square of this many pixels on a side.
PROGRESSION_ICON_SIDE_LENGTH_IN_PIXELS = 16

# The "Perimeters" folder icon's background color.
PERIMETERS_ICON_BACKGROUND_COLOR = (0x32, 0x4B, 0x32)


def progression_icon_filename(band_index: int) -> str:
    """Return the filename of the icon for the band at *band_index*.

    Args:
        band_index: The band's position in the shared band set, newest first.

    Returns:
        The icon filename.
    """
    return f"progression-band-{band_index + 1}.png"


def interior_icon_filename() -> str:
    """Return the filename of the interior folder's icon.

    Returns:
        The icon filename.
    """
    return "interior.png"


def perimeters_icon_filename() -> str:
    """Return the filename of the "Perimeters" folder's icon.

    Returns:
        The icon filename.
    """
    return "perimeters.png"


def kml_color_rgb(kml_color: str) -> tuple[int, int, int]:
    """Return the RGB triple of the KML ``aabbggrr`` *kml_color*.

    Args:
        kml_color: The color as ``aabbggrr``.

    Returns:
        The (red, green, blue) components.
    """
    red = int(kml_color[6:8], 16)
    green = int(kml_color[4:6], 16)
    blue = int(kml_color[2:4], 16)
    return (red, green, blue)


def template_style(
    template: peri_scribe.kml_template_reader.Template,
    placemark_name: str,
) -> peri_scribe.kml_template.Style:
    """Return the template style *placemark_name* references.

    Args:
        template: The parsed KML template.
        placemark_name: The template placemark whose style to read.

    Returns:
        The style the placemark references.
    """
    styles = {style.id: style for style in template.styles}
    return styles[template.style_urls[placemark_name].lstrip("#")]


def template_fill_color_rgb(
    template: peri_scribe.kml_template_reader.Template,
    placemark_name: str,
) -> tuple[int, int, int]:
    """Return the polygon fill color for *placemark_name* as an RGB triple.

    The color is read from the template style the placemark references, so an icon
    filled with it matches the polygons the placemark symbolizes.

    Args:
        template: The parsed KML template.
        placemark_name: The template placemark whose fill style to read.

    Returns:
        The (red, green, blue) components.
    """
    return kml_color_rgb(template_style(template, placemark_name).polystyle.color)


def template_line_color_rgb(
    template: peri_scribe.kml_template_reader.Template,
    placemark_name: str,
) -> tuple[int, int, int]:
    """Return the line color for *placemark_name* as an RGB triple.

    The color is read from the template style the placemark references, so an icon
    using it matches the lines the placemark symbolizes.

    Args:
        template: The parsed KML template.
        placemark_name: The template placemark whose line style to read.

    Returns:
        The (red, green, blue) components.
    """
    return kml_color_rgb(template_style(template, placemark_name).linestyle.color)


def progression_icon_colors(
    template: peri_scribe.kml_template_reader.Template,
) -> tuple[tuple[int, int, int], ...]:
    """Return each progression band's polygon fill color as an RGB triple.

    A band's icon is filled with the same color the band's polygons are styled with,
    read from the template's fill styles.

    Args:
        template: The parsed KML template.

    Returns:
        One RGB triple per shared progression band, newest band first.
    """
    return tuple(
        template_fill_color_rgb(template, band.name)
        for band in peri_scribe.perimeter_progression.PROGRESSION_BANDS
    )


def interior_icon_color(
    template: peri_scribe.kml_template_reader.Template,
) -> tuple[int, int, int]:
    """Return the interior polygons' fill color as an RGB triple.

    The interior folder's icon is filled with the same color the interior polygons are
    styled with, read from the template's fill style.

    Args:
        template: The parsed KML template.

    Returns:
        The (red, green, blue) components.
    """
    return template_fill_color_rgb(
        template,
        peri_scribe.kml_template.FILLED_PERIMETER_TEMPLATE.name,
    )


def perimeters_icon_colors(
    template: peri_scribe.kml_template_reader.Template,
) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    """Return the "Perimeters" folder icon's line colors as RGB triples.

    The icon's top line is colored like the latest perimeter outline and its bottom line
    like the penultimate perimeter outline, read from the template's line styles, so the
    icon matches the outlines it symbolizes.

    Args:
        template: The parsed KML template.

    Returns:
        The (top line, bottom line) (red, green, blue) components.
    """
    return (
        template_line_color_rgb(
            template,
            peri_scribe.kml_template.OUTLINED_PERIMETER_TEMPLATES[0].name,
        ),
        template_line_color_rgb(
            template,
            peri_scribe.kml_template.OUTLINED_PERIMETER_TEMPLATES[1].name,
        ),
    )


def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    """Return one PNG chunk with its length, type, data, and CRC.

    Args:
        chunk_type: The chunk's four-byte type.
        data: The chunk's payload.

    Returns:
        The serialized chunk.
    """
    crc = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", crc)


def solid_color_png(
    red: int,
    green: int,
    blue: int,
    side_in_pixels: int,
) -> bytes:
    """Return a PNG for a square *side_in_pixels* on a side in the given color.

    Args:
        red: The red component, 0 through 255.
        green: The green component, 0 through 255.
        blue: The blue component, 0 through 255.
        side_in_pixels: The square's side length in pixels.

    Returns:
        The PNG bytes.
    """
    signature = b"\x89PNG\r\n\x1a\n"
    header = struct.pack(">IIBBBBB", side_in_pixels, side_in_pixels, 8, 2, 0, 0, 0)
    row = b"\x00" + bytes((red, green, blue)) * side_in_pixels
    raw = row * side_in_pixels
    return (
        signature
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", zlib.compress(raw, zlib.Z_BEST_COMPRESSION))
        + _png_chunk(b"IEND", b"")
    )


def progression_icons(
    template: peri_scribe.kml_template_reader.Template,
) -> dict[str, bytes]:
    """Return the progression band icons for *template*, keyed by filename.

    Each icon is a square filled with the color its band's polygons are styled with,
    generated in memory on every KMZ build.

    Args:
        template: The parsed KML template.

    Returns:
        The icon filename for each shared progression band, mapped to its PNG
        bytes.
    """
    colors = progression_icon_colors(template)
    return {
        progression_icon_filename(index): solid_color_png(
            *color,
            PROGRESSION_ICON_SIDE_LENGTH_IN_PIXELS,
        )
        for index, color in enumerate(colors)
    }


def interior_icon(
    template: peri_scribe.kml_template_reader.Template,
) -> bytes:
    """Return the interior folder icon for *template*.

    The icon is a square filled with the color the interior polygons are styled with,
    generated in memory on every KMZ build.

    Args:
        template: The parsed KML template.

    Returns:
        The icon's PNG bytes.
    """
    return solid_color_png(
        *interior_icon_color(template),
        PROGRESSION_ICON_SIDE_LENGTH_IN_PIXELS,
    )


def perimeters_icon(
    template: peri_scribe.kml_template_reader.Template,
) -> bytes:
    """Return the "Perimeters" folder icon for *template* as a PNG.

    The icon is a square with a #324B32 background and two horizontal, one-pixel-thick
    lines spanning its full width: a line a third of the way down from the top colored
    like the latest perimeter outline and a line a third of the way up from the bottom
    colored like the penultimate perimeter outline. The colors are read from the
    template's line styles, so the folder reads as holding the fire's perimeter
    outlines. The icon is generated in memory on every KMZ build.

    Args:
        template: The parsed KML template.

    Returns:
        The icon's PNG bytes.
    """
    top_line_color, bottom_line_color = perimeters_icon_colors(template)
    side_in_pixels = PROGRESSION_ICON_SIDE_LENGTH_IN_PIXELS
    top_line_row = side_in_pixels // 3
    bottom_line_row = side_in_pixels - 1 - top_line_row
    background_pixel = bytes((*PERIMETERS_ICON_BACKGROUND_COLOR, 255))
    rows: list[bytes] = []
    for row_index in range(side_in_pixels):
        if row_index == top_line_row:
            row = b"\x00" + bytes((*top_line_color, 255)) * side_in_pixels
        elif row_index == bottom_line_row:
            row = b"\x00" + bytes((*bottom_line_color, 255)) * side_in_pixels
        else:
            row = b"\x00" + background_pixel * side_in_pixels
        rows.append(row)
    signature = b"\x89PNG\r\n\x1a\n"
    header = struct.pack(">IIBBBBB", side_in_pixels, side_in_pixels, 8, 6, 0, 0, 0)
    return (
        signature
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", zlib.compress(b"".join(rows), zlib.Z_BEST_COMPRESSION))
        + _png_chunk(b"IEND", b"")
    )
