"""Building the KML styles and draw order for fire placemarks."""

from __future__ import annotations

import kml_io.styles
from measurement_units import units


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


FILL_OPACITY = 50 * units.percent


OUTLINE_OPACITY = 80 * units.percent


OUTLINE_WIDTH = 1.5


def outline_draw_order(outline_count: int, newest_first_index: int) -> int:
    """Return the draw order of the outline at *newest_first_index*.

    Outlines draw from oldest to newest, so the oldest outline draws first and the
    newest draws last, above the others.

    Args:
        outline_count: The number of outlines drawn for the fire.
        newest_first_index: The outline's position counting from the newest outline
            first, where 0 is the newest.

    Returns:
        The draw order, from 1 for the oldest outline to outline_count for the newest.
    """
    return outline_count - newest_first_index


def point_draw_order(outline_count: int) -> int:
    """Return the draw order that draws the point location above every outline.

    Args:
        outline_count: The number of outlines drawn for the fire.

    Returns:
        The draw order, one above the newest outline's.
    """
    return outline_count + 1


def point_style() -> kml_io.styles.Style:
    """Return the style for the fictional point location.

    Returns:
        The style, holding the point's icon.
    """
    return kml_io.styles.icon_style(POINT_STYLE_ID, POINT_ICON_URL)


def filled_polygon_style(style_id: str, color: str) -> kml_io.styles.Style:
    """Return the polygon fill style with *style_id* and *color*.

    The polygon fills at :data:`FILL_OPACITY` with no outline, so wherever fills overlap
    each one shows through the next and the newest reads hottest.

    Args:
        style_id: The style's identifier.
        color: The fill color as ``#RRGGBB``.

    Returns:
        The style, with a filled polygon style.
    """
    return kml_io.styles.filled_polygon_style(style_id, color, FILL_OPACITY)


def outlined_perimeter_style(style_id: str, color: str) -> kml_io.styles.Style:
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
    return kml_io.styles.outlined_polygon_style(
        style_id,
        color,
        OUTLINE_OPACITY,
        OUTLINE_WIDTH,
    )


def symbolization_styles() -> tuple[kml_io.styles.Style, ...]:
    """Return the application's fixed fire-symbolization styles.

    Returns:
        The styles used by every generated KML document.
    """
    return (
        point_style(),
        filled_polygon_style(FILLED_PERIMETER_STYLE_ID, FILLED_PERIMETER_COLOR),
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
