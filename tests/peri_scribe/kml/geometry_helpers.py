"""Provide data builders and stand-ins for geometry tests."""

from __future__ import annotations

import typing

import hypothesis.strategies
import pytest
import shapely

import peri_scribe.kml.geometry
import tests.peri_scribe.kml.kml_helpers


if typing.TYPE_CHECKING:
    import xml.etree.ElementTree as ET


def xml_text() -> hypothesis.strategies.SearchStrategy[str]:
    """Allow XML punctuation without accidentally creating CDATA delimiters.

    Returns:
        XML-compatible text with varied Unicode characters and no square brackets.
    """
    return hypothesis.strategies.text(
        alphabet=hypothesis.strategies.characters(
            exclude_categories=("Cc", "Cs"),
            exclude_characters=("[", "]", "\ufffe", "\uffff"),
        ),
        max_size=100,
    )


def assert_temporary_geometry_serialization(
    geometries: list[shapely.Polygon | shapely.MultiPolygon],
) -> None:
    """Check that sharing a writer cannot substitute another geometry's coordinates.

    Args:
        geometries: Footprints to serialize through temporary decoded copies.
    """
    writer = peri_scribe.kml.geometry.KmlWriter()
    for draw_order, geometry in enumerate([*geometries, *geometries]):
        actual = writer.geometry_xml(shapely.from_wkb(geometry.wkb), draw_order)
        expected = peri_scribe.kml.geometry.KmlWriter().geometry_xml(
            geometry,
            draw_order,
        )
        assert actual == expected


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
            tests.peri_scribe.kml.kml_helpers.kml_tag("coordinates"),
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
        if polygon.tag != tests.peri_scribe.kml.kml_helpers.kml_tag("Polygon"):
            continue
        text = polygon.findtext(tests.peri_scribe.kml.kml_helpers.gx_tag("drawOrder"))
        if text is None:
            pytest.fail("MultiGeometry polygon has no gx:drawOrder")
        orders.append(int(text))
    return orders
