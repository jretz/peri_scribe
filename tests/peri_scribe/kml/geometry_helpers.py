"""Provide data builders and stand-ins for geometry tests."""

from __future__ import annotations

import typing

import pytest

import tests.peri_scribe.kml.kml_helpers


if typing.TYPE_CHECKING:
    import xml.etree.ElementTree as ET


def polygon_draw_orders(multi_geometry: ET.Element) -> list[int]:
    """Return the gx:drawOrder of each polygon in *multi_geometry*.

    Args:
        multi_geometry: The MultiGeometry element to inspect.

    Returns:
        The polygons' draw orders, in order.
    """
    orders: list[int] = []
    for polygon in multi_geometry:
        if polygon.tag != tests.peri_scribe.kml.kml_helpers.kml_tag("Polygon"):
            continue
        text = polygon.findtext(tests.peri_scribe.kml.kml_helpers.gx_tag("drawOrder"))
        if text is None:
            pytest.fail("MultiGeometry polygon has no gx:drawOrder")
        orders.append(int(text))
    return orders
