"""Serializing fire geometry into KML placemark text.

Each helper appends the KML text for one fire geometry to a shared :class:`KmlWriter`.
The writer caches each geometry's serialized rings so a fire's geometry, which the
folder hierarchy shows in several places, is formatted only once.
"""

from __future__ import annotations

import contextlib
import html
import typing
from collections.abc import Iterator


if typing.TYPE_CHECKING:
    import shapely


KML_NAMESPACE = "http://www.opengis.net/kml/2.2"
GX_NAMESPACE = "http://www.google.com/kml/ext/2.2"


def escape_text(text: str) -> str:
    """Return *text* with XML special characters escaped, leaving CDATA intact.

    The fire descriptions are wrapped in CDATA sections so their HTML survives as
    markup; everything outside a CDATA section is escaped the same way simplekml escapes
    placemark text.

    Args:
        text: The text to escape.

    Returns:
        The escaped text.
    """
    result: list[str] = []
    start = 0
    while True:
        cdata_start = text.find("<![CDATA[", start)
        if cdata_start == -1:
            result.append(html.escape(text[start:]))
            return "".join(result)
        cdata_end = text.find("]]>", cdata_start)
        result.extend([
            html.escape(text[start:cdata_start]),
            text[cdata_start : cdata_end + 3],
        ])
        start = cdata_end + 3


def ring_coordinates(ring: shapely.LinearRing) -> list[tuple[float, float]]:
    """Return the KML coordinates of *ring*.

    Args:
        ring: The shapely ring to convert.

    Returns:
        The ring's (longitude, latitude) coordinates.
    """
    return [(float(x), float(y)) for x, y in ring.coords]


def ring_coordinates_text(ring: shapely.LinearRing) -> str:
    """Return the KML coordinate text of *ring*.

    Args:
        ring: The shapely ring to convert.

    Returns:
        The ring's ``longitude,latitude,0.0`` tuples joined by spaces.
    """
    return " ".join(f"{x},{y},0.0" for x, y in ring.coords)


class KmlWriter:
    """Accumulates KML text and caches repeated geometry serialization.

    The parts list holds the document as it is assembled; :meth:`text` joins it. Each
    unique geometry's rings are serialized once and cached, keyed by the geometry object
    itself, which the folder builders share across the several views that show the same
    fire.
    """

    def __init__(self) -> None:
        self.parts: list[str] = []
        self._geometry_cache: dict[int, tuple[str, ...]] = {}
        self._next_folder_id = 0

    def text(self) -> str:
        """Return the assembled KML document.

        Returns:
            The KML document text.
        """
        return "".join(self.parts)

    @contextlib.contextmanager
    def folder(
        self,
        name: str,
        *,
        visible: bool = True,
        list_item_type: str | None = None,
        item_icon: str | None = None,
    ) -> Iterator[str]:
        """Open a folder and yield its unique id, closing it on exit.

        Args:
            name: The folder's name.
            visible: Whether the folder and its children are visible. Hidden folders
                and every feature beneath them carry a zero visibility.
            list_item_type: The folder's list item type, or None for none.
            item_icon: The folder's list item icon href, or None for none.

        Yields:
            The folder's document-unique id string, used to name its tour targets.
        """
        folder_id = str(self._next_folder_id)
        self._next_folder_id += 1
        parts = self.parts
        parts.append("<Folder>")
        parts.append(f"<name>{escape_text(name)}</name>")
        if not visible:
            parts.append("<visibility>0</visibility>")
        if list_item_type is not None or item_icon is not None:
            parts.append("<Style><ListStyle>")
            parts.append(f"<listItemType>{list_item_type or 'check'}</listItemType>")
            if item_icon is not None:
                parts.append(
                    f"<ItemIcon><href>{escape_text(item_icon)}</href></ItemIcon>",
                )
            parts.append("</ListStyle></Style>")
        try:
            yield folder_id
        finally:
            parts.append("</Folder>")

    def geometry_xml(
        self,
        geometry: shapely.Geometry,
        draw_order: int,
    ) -> str:
        """Return *geometry* as a KML geometry element with *draw_order* applied.

        A polygon carries its draw order directly; a multi-geometry carries none of its
        own, so the order is applied to each polygon it contains, matching how Google
        Earth reads the tag. Each unique geometry's boundaries are serialized once and
        cached.

        Args:
            geometry: The shapely polygon or multi-polygon to serialize.
            draw_order: Lower values draw first, underneath later features.

        Returns:
            The geometry element's KML text.
        """
        cached = self._geometry_cache.get(id(geometry))
        if cached is None:
            if geometry.geom_type == "Polygon":
                polygons = [geometry]
            else:
                polygons = list(geometry.geoms)
            cached = tuple(_polygon_boundaries(polygon) for polygon in polygons)
            self._geometry_cache[id(geometry)] = cached
        if geometry.geom_type == "Polygon":
            return (
                f"<Polygon>{cached[0]}"
                f"<gx:drawOrder>{draw_order}</gx:drawOrder></Polygon>"
            )
        inner = "".join(
            f"<Polygon>{ring}<gx:drawOrder>{draw_order}</gx:drawOrder></Polygon>"
            for ring in cached
        )
        return f"<MultiGeometry>{inner}</MultiGeometry>"


def _polygon_boundaries(polygon: shapely.Polygon) -> str:
    """Return *polygon*'s outer and inner boundary KML text.

    Args:
        polygon: The polygon to serialize.

    Returns:
        The polygon's boundary KML text.
    """
    parts = [
        "<outerBoundaryIs><LinearRing><coordinates>",
        ring_coordinates_text(polygon.exterior),
        "</coordinates></LinearRing></outerBoundaryIs>",
    ]
    for interior in polygon.interiors:
        parts.extend([
            "<innerBoundaryIs><LinearRing><coordinates>",
            ring_coordinates_text(interior),
            "</coordinates></LinearRing></innerBoundaryIs>",
        ])
    return "".join(parts)


def _open_placemark(
    writer: KmlWriter,
    name: str,
    style_url: str,
    *,
    description: str | None,
    visible: bool,
    placemark_id: str | None,
) -> None:
    """Append a placemark's opening tag and metadata to *writer*."""
    parts = writer.parts
    parts.append("<Placemark")
    if placemark_id is not None:
        parts.append(f' id="{placemark_id}"')
    parts.append(">")
    parts.append(f"<name>{escape_text(name)}</name>")
    parts.append(f"<styleUrl>{style_url}</styleUrl>")
    if not visible:
        parts.append("<visibility>0</visibility>")
    if description is not None:
        parts.append(f"<description>{escape_text(description)}</description>")


def point_placemark(
    writer: KmlWriter,
    name: str,
    style_url: str,
    point: shapely.Point,
    draw_order: int,
    *,
    description: str | None = None,
    visible: bool = True,
) -> None:
    """Append the point placemark for *point* named *name* to *writer*.

    Args:
        writer: The writer to append to.
        name: The name to show for the point.
        style_url: The style URL to apply.
        point: The point geometry.
        draw_order: The order in which the point draws; it draws last, above the
            perimeters.
        description: The balloon description, or None for none.
        visible: Whether the placemark is visible.
    """
    _open_placemark(
        writer,
        name,
        style_url,
        description=description,
        visible=visible,
        placemark_id=None,
    )
    writer.parts.append(
        f"<Point><coordinates>{point.x},{point.y},0.0</coordinates>"
        f"<gx:drawOrder>{draw_order}</gx:drawOrder></Point>",
    )
    writer.parts.append("</Placemark>")


def polygon_geometry(
    writer: KmlWriter,
    name: str,
    style_url: str,
    polygon: shapely.Polygon,
    draw_order: int,
    *,
    description: str | None = None,
    visible: bool = True,
    placemark_id: str | None = None,
) -> None:
    """Append the polygon placemark for *polygon* to *writer*.

    Args:
        writer: The writer to append to.
        name: The placemark name.
        style_url: The style URL to apply.
        polygon: The shapely polygon to convert.
        draw_order: The order in which the polygon draws.
        description: The balloon description, or None for none.
        visible: Whether the placemark is visible.
        placemark_id: The placemark id, or None for none.
    """
    _open_placemark(
        writer,
        name,
        style_url,
        description=description,
        visible=visible,
        placemark_id=placemark_id,
    )
    writer.parts.append(writer.geometry_xml(polygon, draw_order))
    writer.parts.append("</Placemark>")


def multi_polygon_geometry(
    writer: KmlWriter,
    name: str,
    style_url: str,
    multi_polygon: shapely.MultiPolygon,
    draw_order: int,
    *,
    description: str | None = None,
    visible: bool = True,
    placemark_id: str | None = None,
) -> None:
    """Append the multi-geometry placemark for *multi_polygon* to *writer*.

    Args:
        writer: The writer to append to.
        name: The placemark name.
        style_url: The style URL to apply.
        multi_polygon: The shapely multi-polygon to convert.
        draw_order: The order in which the multi-geometry draws.
        description: The balloon description, or None for none.
        visible: Whether the placemark is visible.
        placemark_id: The placemark id, or None for none.
    """
    _open_placemark(
        writer,
        name,
        style_url,
        description=description,
        visible=visible,
        placemark_id=placemark_id,
    )
    writer.parts.append(writer.geometry_xml(multi_polygon, draw_order))
    writer.parts.append("</Placemark>")


def perimeter_geometry(
    writer: KmlWriter,
    name: str,
    style_url: str,
    geometry: shapely.Geometry,
    draw_order: int,
    *,
    description: str | None = None,
    visible: bool = True,
    placemark_id: str | None = None,
) -> None:
    """Append the placemark for *geometry* to *writer*.

    Args:
        writer: The writer to append to.
        name: The placemark name.
        style_url: The style URL to apply.
        geometry: A shapely polygon or multi-polygon.
        draw_order: The order in which the geometry draws.
        description: The balloon description, or None for none.
        visible: Whether the placemark is visible.
        placemark_id: The placemark id, or None for none.
    """
    if geometry.geom_type == "Polygon":
        polygon_geometry(
            writer,
            name,
            style_url,
            typing.cast("shapely.Polygon", geometry),
            draw_order,
            description=description,
            visible=visible,
            placemark_id=placemark_id,
        )
    else:
        multi_polygon_geometry(
            writer,
            name,
            style_url,
            typing.cast("shapely.MultiPolygon", geometry),
            draw_order,
            description=description,
            visible=visible,
            placemark_id=placemark_id,
        )


def perimeter_placemark(
    writer: KmlWriter,
    name: str,
    style_url: str,
    geometry: shapely.Geometry,
    draw_order: int,
    *,
    description: str | None = None,
    visible: bool = True,
    placemark_id: str | None = None,
) -> None:
    """Append the perimeter placemark for *geometry* to *writer*.

    Args:
        writer: The writer to append to.
        name: The placemark name.
        style_url: The style URL to apply.
        geometry: The perimeter geometry.
        draw_order: The order in which the perimeter draws.
        description: The balloon description, or None for none.
        visible: Whether the placemark is visible.
        placemark_id: The placemark id, or None for none.
    """
    perimeter_geometry(
        writer,
        name,
        style_url,
        geometry,
        draw_order,
        description=description,
        visible=visible,
        placemark_id=placemark_id,
    )
