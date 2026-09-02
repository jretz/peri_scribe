"""Building the KML styles and draw order for fire placemarks."""

from __future__ import annotations

import simplekml


class Style(simplekml.Style):
    """A style whose id is assigned by the application.

    simplekml otherwise numbers every style's id itself; placemarks need stable ids so
    they can reference styles by URL.
    """

    def __init__(self, style_id: str) -> None:
        super().__init__()
        # simplekml reads this attribute when serializing the style's id.
        self._id = style_id


POINT_ICON_URL = "http://maps.google.com/mapfiles/kml/shapes/firedept.png"


POINT_STYLE_ID = "point-icon"


POINT_LOCATION_NAME = "Point Location"


FILLED_PERIMETER_NAME = "Interior"
FILLED_PERIMETER_STYLE_ID = "perimeter-fill"
FILLED_PERIMETER_COLOR = "#FF0000"


OUTLINED_PERIMETER_NAMES = (
    "Latest Perimeter",
    "Penultimate Perimeter",
    "Antepenultimate Perimeter",
)
OUTLINED_PERIMETER_STYLE_IDS = (
    "perimeter-outline-1",
    "perimeter-outline-2",
    "perimeter-outline-3",
)
OUTLINED_PERIMETER_COLORS = ("#FF0000", "#FFFF00", "#FFFFFF")


PLACEMARK_STYLE_URLS = {
    POINT_LOCATION_NAME: f"#{POINT_STYLE_ID}",
    FILLED_PERIMETER_NAME: f"#{FILLED_PERIMETER_STYLE_ID}",
    **{
        name: f"#{style_id}"
        for name, style_id in zip(
            OUTLINED_PERIMETER_NAMES,
            OUTLINED_PERIMETER_STYLE_IDS,
            strict=True,
        )
    },
}


FILL_OPACITY_PERCENT = 50


OUTLINE_OPACITY_PERCENT = 80


OUTLINE_WIDTH = 1.5


def kml_color(red_green_blue: str, opacity_in_percent: int) -> str:
    """Return the KML ``aabbggrr`` color for *red_green_blue* at an opacity.

    Args:
        red_green_blue: The color as ``#RRGGBB``.
        opacity_in_percent: The opacity from 0 (transparent) to 100 (opaque).

    Returns:
        The KML color string.

    Examples:
        >>> kml_color("#FF0080", 50)
        '7f8000ff'
    """
    red = red_green_blue[1:3]
    green = red_green_blue[3:5]
    blue = red_green_blue[5:7]
    alpha = opacity_in_percent * 255 // 100
    return f"{alpha:02x}{blue}{green}{red}".lower()


def set_draw_order(
    geometry: simplekml.Point | simplekml.Polygon,
    draw_order: int,
) -> None:
    """Set the gx:drawOrder of *geometry* to *draw_order*.

    simplekml exposes gx:drawOrder only on LineString, but every geometry serializes
    from the same internal element map, so the tag is set there for points and polygons
    alike. The application's perimeters are all single polygons, so no multi-geometry
    handling is needed here.

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


def filled_perimeter_style(style_id: str, color: str) -> Style:
    """Return the filled polygon style with *style_id* and *color*.

    Args:
        style_id: The style's identifier.
        color: The fill color as ``#RRGGBB``.

    Returns:
        The style, with a filled polygon style.
    """
    style = Style(style_id)
    style.polystyle.color = kml_color(color, FILL_OPACITY_PERCENT)
    style.polystyle.fill = 1
    style.polystyle.outline = 0
    return style


def outlined_perimeter_style(style_id: str, color: str) -> Style:
    """Return the outline style with *style_id* and *color*.

    The polygon fills in the outline color at zero opacity, so the fill never shows on
    the map while Google Earth's list icon, which reads the fill color, matches the
    outline.

    Args:
        style_id: The style's identifier.
        color: The outline color as ``#RRGGBB``.

    Returns:
        The style, with a line style and a transparently filled polygon style.
    """
    style = Style(style_id)
    style.linestyle.color = kml_color(color, OUTLINE_OPACITY_PERCENT)
    style.linestyle.width = OUTLINE_WIDTH
    style.polystyle.color = kml_color(color, 0)
    style.polystyle.fill = 1
    style.polystyle.outline = 1
    return style


def symbolization_styles() -> tuple[Style, ...]:
    """Return the application's fixed fire-symbolization styles.

    Returns:
        The styles used by every generated KML document.
    """
    return (
        point_style(),
        filled_perimeter_style(FILLED_PERIMETER_STYLE_ID, FILLED_PERIMETER_COLOR),
        *map(
            outlined_perimeter_style,
            OUTLINED_PERIMETER_STYLE_IDS,
            OUTLINED_PERIMETER_COLORS,
            strict=True,
        ),
    )


def progression_ring_style_id(color: str) -> str:
    """Return the style id for the progression ring color *color*.

    The id is derived from the color, so every ring drawn in the same color shares one
    style.

    Args:
        color: The color as ``#RRGGBB``.

    Returns:
        The style id.
    """
    return f"ring-fill-{color[1:]}"


def progression_ring_style(style_id: str, color: str) -> Style:
    """Return the fill style for one progression-ring color.

    The progression rings fill at 50% opacity with no outline, so the newest ring reads
    hottest while the older rings beneath it stay visible.

    Args:
        style_id: The style's id.
        color: The color as ``#RRGGBB``.

    Returns:
        The style, with a filled polygon style.
    """
    style = Style(style_id)
    style.polystyle.color = kml_color(color, FILL_OPACITY_PERCENT)
    style.polystyle.fill = 1
    style.polystyle.outline = 0
    return style
