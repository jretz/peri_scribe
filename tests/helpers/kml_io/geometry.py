"""Inspect geometry behavior with shared test utilities."""

from __future__ import annotations

import typing

import pytest

import tests.helpers.peri_scribe.kml.parsing


if typing.TYPE_CHECKING:
    import xml.etree.ElementTree as ET


def coordinate_rings(polygon: ET.Element) -> list[list[tuple[float, ...]]]:
    """Read each polygon's complete shell and hole coordinates from generated KML.

    Args:
        polygon: The polygon element to inspect.

    Returns:
        Coordinate sequences in document order, with the shell first.
    """
    return [
        [tuple(map(float, pair.split(","))) for pair in (element.text or "").split()]
        for element in polygon.iter(
            tests.helpers.peri_scribe.kml.parsing.kml_tag("coordinates"),
        )
    ]


def polygon_draw_orders(multi_geometry: ET.Element) -> list[int]:
    """Return the gx:drawOrder of each polygon in *multi_geometry*.

    Args:
        multi_geometry: The MultiGeometry element to inspect.

    Returns:
        The polygons' draw orders, in order.
    """
    orders: list[int] = []
    for polygon in multi_geometry:
        if polygon.tag != tests.helpers.peri_scribe.kml.parsing.kml_tag("Polygon"):
            continue
        text = polygon.findtext(
            tests.helpers.peri_scribe.kml.parsing.gx_tag("drawOrder"),
        )
        if text is None:
            pytest.fail("MultiGeometry polygon has no gx:drawOrder")
        orders.append(int(text))
    return orders
