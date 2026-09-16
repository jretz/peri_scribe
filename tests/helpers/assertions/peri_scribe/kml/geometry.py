"""Compare geometry behavior through reusable assertions."""

from __future__ import annotations

import shapely

import peri_scribe.kml.geometry


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
