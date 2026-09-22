"""Stable style identifiers let streamed placemarks share their symbolization."""

from __future__ import annotations

import typing

import simplekml


if typing.TYPE_CHECKING:
    import pint


class Style(simplekml.Style):
    """A caller-assigned identifier keeps style references stable across documents."""

    def __init__(self, style_id: str) -> None:
        """Give placemarks a stable identifier for referencing this style.

        Args:
            style_id: The identifier serialized with the style.
        """
        super().__init__()
        # simplekml reads this attribute when serializing the style's id.
        self._id = style_id


def kml_color(red_green_blue: str, opacity: pint.Quantity[float]) -> str:
    """Keep RGB input compatible with KML's alpha-first, reversed channel order.

    Args:
        red_green_blue: The color as ``#RRGGBB``.
        opacity: The opacity from zero to one, or an equivalent percentage.

    Returns:
        The KML ``aabbggrr`` color.
    """
    red = red_green_blue[1:3]
    green = red_green_blue[3:5]
    blue = red_green_blue[5:7]
    alpha = int(opacity.m_as("percent") * 255 // 100)
    return f"{alpha:02x}{blue}{green}{red}".lower()


def icon_style(style_id: str, icon_url: str) -> Style:
    """Let point placemarks share one icon reference.

    Args:
        style_id: The identifier referenced by placemarks.
        icon_url: The icon's URL or archive member path.

    Returns:
        The point icon style.
    """
    style = Style(style_id)
    style.iconstyle.icon.href = icon_url
    return style


def filled_polygon_style(
    style_id: str,
    color: str,
    opacity: pint.Quantity[float],
) -> Style:
    """Keep polygon fill independent of any outline symbolization.

    Args:
        style_id: The identifier referenced by placemarks.
        color: The fill color as ``#RRGGBB``.
        opacity: The fill opacity as a dimensionless quantity.

    Returns:
        A filled polygon style with no outline.
    """
    style = Style(style_id)
    style.polystyle.color = kml_color(color, opacity)
    style.polystyle.fill = 1
    style.polystyle.outline = 0
    return style


def outlined_polygon_style(
    style_id: str,
    color: str,
    opacity: pint.Quantity[float],
    width: float,
) -> Style:
    """Draw polygon boundaries with no interior fill.

    Args:
        style_id: The identifier referenced by placemarks.
        color: The outline color as ``#RRGGBB``.
        opacity: The outline opacity as a dimensionless quantity.
        width: The KML line width.

    Returns:
        An outlined polygon style with filling disabled.
    """
    style = Style(style_id)
    style.linestyle.color = kml_color(color, opacity)
    style.linestyle.width = width
    style.polystyle.fill = 0
    style.polystyle.outline = 1
    return style
