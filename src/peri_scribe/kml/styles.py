"""Building the KML styles and draw order for template placemarks."""

from __future__ import annotations

import typing

import simplekml


if typing.TYPE_CHECKING:
    import peri_scribe.kml.template


class Style(simplekml.Style):
    """A style whose id the template assigns.

    simplekml otherwise numbers every style's id itself; the template's styles need
    stable ids so placemarks can reference them by URL.
    """

    def __init__(self, style_id: str) -> None:
        super().__init__()
        # simplekml reads this attribute when serializing the style's id.
        self._id = style_id


POINT_ICON_URL = "http://maps.google.com/mapfiles/kml/shapes/firedept.png"


POINT_STYLE_ID = "point-icon"


FILL_OPACITY_PERCENT = 50


OUTLINE_OPACITY_PERCENT = 100


OUTLINE_WIDTH = 1.5


def kml_color(red_green_blue: str, opacity_in_percent: int) -> str:
    """Return the KML ``aabbggrr`` color for *red_green_blue* at an opacity.

    Args:
        red_green_blue: The color as ``#RRGGBB``.
        opacity_in_percent: The opacity from 0 (transparent) to 100 (opaque).

    Returns:
        The KML color string.
    """
    red = red_green_blue[1:3]
    green = red_green_blue[3:5]
    blue = red_green_blue[5:7]
    alpha = opacity_in_percent * 255 // 100
    return f"{alpha:02x}{blue}{green}{red}".lower()


TRANSPARENT_FILL_COLOR = kml_color("#FFFFFF", 0)


def set_draw_order(
    geometry: simplekml.Point | simplekml.Polygon,
    draw_order: int,
) -> None:
    """Set the gx:drawOrder of *geometry* to *draw_order*.

    simplekml exposes gx:drawOrder only on LineString, but every geometry serializes
    from the same internal element map, so the tag is set there for points and polygons
    alike. The template's fictional perimeters are all single polygons, so no
    multi-geometry handling is needed here.

    Args:
        geometry: The geometry to order.
        draw_order: Lower values draw first, underneath later features.
    """
    # The tag map is a plain instance attribute, reached through vars() because
    # simplekml keeps it private (``_kml``).
    vars(geometry)["_kml"]["gx:drawOrder"] = draw_order


def outline_draw_order(outline_count: int, newest_first_index: int) -> int:
    """Return the draw order of the outline at *newest_first_index*.

    Outlines draw from oldest to newest, so the oldest outline draws first and the
    newest draws last, above the others.

    Args:
        outline_count: The number of outlines drawn for the fire.
        newest_first_index: The outline's position counting from the newest
            outline first, where 0 is the newest.

    Returns:
        The draw order, from 1 for the oldest outline to outline_count for the newest.
    """
    return outline_count - newest_first_index


def band_draw_order(band_count: int, newest_first_index: int) -> int:
    """Return the draw order of the growth band at *newest_first_index*.

    Bands draw from oldest to newest, so the oldest band draws first, at the bottom of
    the stack, and the newest draws last, above the others.

    Args:
        band_count: The number of bands drawn in the progression map.
        newest_first_index: The band's position counting from the newest band first,
            where 0 is the newest.

    Returns:
        The draw order, from 0 for the oldest band to band_count - 1 for the newest.
    """
    return band_count - 1 - newest_first_index


def point_draw_order(outline_count: int) -> int:
    """Return the draw order that draws the point location above every outline.

    Args:
        outline_count: The number of outlines drawn for the fire.

    Returns:
        The draw order, one above the newest outline's.
    """
    return outline_count + 1


def point_style() -> Style:
    """Return the style for the fictional point location.

    Returns:
        The style, holding the point's icon.
    """
    style = Style(POINT_STYLE_ID)
    style.iconstyle.icon.href = POINT_ICON_URL
    return style


def filled_perimeter_style(
    template: peri_scribe.kml.template.PerimeterTemplate,
) -> Style:
    """Return the fill style for *template*.

    Args:
        template: The perimeter the style symbolizes.

    Returns:
        The style, with a filled polygon style.
    """
    style = Style(template.style_id)
    style.polystyle.color = kml_color(template.color, FILL_OPACITY_PERCENT)
    style.polystyle.fill = 1
    style.polystyle.outline = 0
    return style


def outlined_perimeter_style(
    template: peri_scribe.kml.template.PerimeterTemplate,
) -> Style:
    """Return the outline style for *template*.

    Args:
        template: The perimeter the style symbolizes.

    Returns:
        The style, with a line style and a transparently filled polygon style.
    """
    style = Style(template.style_id)
    style.linestyle.color = kml_color(template.color, OUTLINE_OPACITY_PERCENT)
    style.linestyle.width = OUTLINE_WIDTH
    style.polystyle.color = TRANSPARENT_FILL_COLOR
    style.polystyle.fill = 1
    style.polystyle.outline = 1
    return style
