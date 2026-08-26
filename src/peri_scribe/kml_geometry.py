"""Serializing fire geometry into KML placemarks.

Each helper converts one shapely geometry into a KML placemark and applies the style and
draw order the template assigns to it.
"""

from __future__ import annotations

import typing

import peri_scribe.kml_template


if typing.TYPE_CHECKING:
    import shapely
    import simplekml


def ring_coordinates(ring: shapely.LinearRing) -> list[tuple[float, float]]:
    """Return the KML coordinates of *ring*.

    Args:
        ring: The shapely ring to convert.

    Returns:
        The ring's (longitude, latitude) coordinates.
    """
    return [(float(x), float(y)) for x, y in ring.coords]


def point_placemark(
    container: simplekml.Container,
    name: str,
    style_url: str,
    point: shapely.Point,
    draw_order: int,
    *,
    description: str | None,
) -> None:
    """Add the point placemark for *point* named *name* to *container*.

    Args:
        container: The folder that holds the placemark.
        name: The name to show for the point.
        style_url: The style URL to apply.
        point: The point geometry.
        draw_order: The order in which the point draws; it draws last, above the
            perimeters.
        description: The balloon description, or None for none.
    """
    placemark = container.newpoint(name=name, coords=[(point.x, point.y)])
    placemark.placemark.styleurl = style_url
    if description is not None:
        placemark.placemark.description = description
    peri_scribe.kml_template.set_draw_order(placemark, draw_order)


def polygon_geometry(
    container: simplekml.Container,
    name: str,
    style_url: str,
    polygon: shapely.Polygon,
    draw_order: int,
    *,
    description: str | None,
) -> simplekml.Polygon:
    """Add the polygon placemark for *polygon* to *container*.

    Args:
        container: The folder that holds the placemark.
        name: The placemark name.
        style_url: The style URL to apply.
        polygon: The shapely polygon to convert.
        draw_order: The order in which the polygon draws.
        description: The balloon description, or None for none.

    Returns:
        The polygon placemark.
    """
    placemark = container.newpolygon(
        name=name,
        outerboundaryis=ring_coordinates(polygon.exterior),
    )
    placemark.placemark.styleurl = style_url
    if description is not None:
        placemark.placemark.description = description
    if polygon.interiors:
        placemark.innerboundaryis = [
            ring_coordinates(interior) for interior in polygon.interiors
        ]
    peri_scribe.kml_template.set_draw_order(placemark, draw_order)
    return placemark


def multi_polygon_geometry(
    container: simplekml.Container,
    name: str,
    style_url: str,
    multi_polygon: shapely.MultiPolygon,
    draw_order: int,
    *,
    description: str | None,
) -> simplekml.MultiGeometry:
    """Add the multi-geometry placemark for *multi_polygon* to *container*.

    Args:
        container: The folder that holds the placemark.
        name: The placemark name.
        style_url: The style URL to apply.
        multi_polygon: The shapely multi-polygon to convert.
        draw_order: The order in which the multi-geometry draws.
        description: The balloon description, or None for none.

    Returns:
        The multi-geometry placemark.
    """
    geometry = container.newmultigeometry(name=name)
    geometry.placemark.styleurl = style_url
    if description is not None:
        geometry.placemark.description = description
    for polygon in multi_polygon.geoms:
        polygon = typing.cast("shapely.Polygon", polygon)
        geometry.newpolygon(
            outerboundaryis=ring_coordinates(polygon.exterior),
            innerboundaryis=[
                ring_coordinates(interior) for interior in polygon.interiors
            ],
        )
    peri_scribe.kml_template.set_draw_order(geometry, draw_order)
    return geometry


def perimeter_geometry(
    container: simplekml.Container,
    name: str,
    style_url: str,
    geometry: shapely.Geometry,
    draw_order: int,
    *,
    description: str | None,
) -> simplekml.Polygon | simplekml.MultiGeometry:
    """Add the placemark for *geometry* to *container*.

    Args:
        container: The folder that holds the placemark.
        name: The placemark name.
        style_url: The style URL to apply.
        geometry: A shapely polygon or multi-polygon.
        draw_order: The order in which the geometry draws.
        description: The balloon description, or None for none.

    Returns:
        The polygon or multi-geometry placemark.
    """
    if geometry.geom_type == "Polygon":
        return polygon_geometry(
            container,
            name,
            style_url,
            typing.cast("shapely.Polygon", geometry),
            draw_order,
            description=description,
        )
    return multi_polygon_geometry(
        container,
        name,
        style_url,
        typing.cast("shapely.MultiPolygon", geometry),
        draw_order,
        description=description,
    )


def perimeter_placemark(
    container: simplekml.Container,
    name: str,
    style_url: str,
    geometry: shapely.Geometry,
    draw_order: int,
    *,
    description: str | None,
) -> simplekml.Polygon | simplekml.MultiGeometry:
    """Add the perimeter placemark for *geometry* to *container*.

    Args:
        container: The folder that holds the placemark.
        name: The placemark name.
        style_url: The style URL to apply.
        geometry: The perimeter geometry.
        draw_order: The order in which the perimeter draws.
        description: The balloon description, or None for none.

    Returns:
        The perimeter placemark.
    """
    return perimeter_geometry(
        container,
        name,
        style_url,
        geometry,
        draw_order,
        description=description,
    )
