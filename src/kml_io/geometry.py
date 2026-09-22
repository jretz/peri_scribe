"""Stream geometry into KML while sharing serialization work across views.

The writer caches serialized rings so geometry appearing in several folders is formatted
only once. Callers own the destination stream and choose the document's presentation.
"""

from __future__ import annotations

import contextlib
import html
import itertools
import typing


if typing.TYPE_CHECKING:
    import shapely


KML_NAMESPACE = "http://www.opengis.net/kml/2.2"
GX_NAMESPACE = "http://www.google.com/kml/ext/2.2"

# Decimal places kept on every coordinate written to KML. Five places are about 1.1
# meters, below the detail these ground-level maps display. Rounding shrinks repeated
# coordinate text. The altitude component is omitted entirely: KML coordinates default
# it to zero, and every geometry here draws clampToGround, which ignores it.
COORDINATE_DECIMALS = 5


def coordinate_pair(longitude: float, latitude: float) -> str:
    """Return *longitude* and *latitude* as KML coordinate text.

    Args:
        longitude: The longitude to format.
        latitude: The latitude to format.

    Returns:
        ``longitude,latitude`` with each value rounded to :data:`COORDINATE_DECIMALS`
        decimal places.

    Examples:
        >>> coordinate_pair(-121.123456, 38.987654)
        '-121.12346,38.98765'
    """
    return f"{longitude:.{COORDINATE_DECIMALS}f},{latitude:.{COORDINATE_DECIMALS}f}"


def escape_text(text: str) -> str:
    """Return *text* with XML special characters escaped, leaving CDATA intact.

    Descriptions can use CDATA sections so their HTML survives as markup; everything
    outside a CDATA section is escaped the same way simplekml escapes placemark text.

    Args:
        text: The text to escape.

    Returns:
        The escaped text.

    Examples:
        >>> escape_text("A & B")
        'A &amp; B'

        >>> escape_text("<![CDATA[<b>Fire</b>]]>")
        '<![CDATA[<b>Fire</b>]]>'
    """
    result: list[str] = []
    start = 0
    while True:
        cdata_start = text.find("<![CDATA[", start)
        if cdata_start == -1:
            break
        cdata_end = text.find("]]>", cdata_start)
        if cdata_end == -1:
            break
        result.extend([
            html.escape(text[start:cdata_start]),
            text[cdata_start : cdata_end + 3],
        ])
        start = cdata_end + 3
    result.append(html.escape(text[start:]))
    return "".join(result)


def ring_coordinates_text(ring: shapely.LinearRing) -> str:
    """Return the KML coordinate text of *ring*.

    Args:
        ring: The shapely ring to convert.

    Returns:
        The ring's ``longitude,latitude`` pairs joined by spaces, rounded to
        :data:`COORDINATE_DECIMALS` decimal places and carrying no altitude.
    """
    return " ".join(itertools.starmap(coordinate_pair, ring.coords))


class KmlWriter:
    """Write nested KML directly while sharing geometry text and tour identifiers.

    Folder scopes keep opening and closing tags together. The geometry cache avoids
    repeating coordinate formatting across several views of the same geometry.
    """

    def __init__(self, stream: typing.TextIO) -> None:
        """Keep document state separate from the caller-owned output stream.

        Args:
            stream: The text destination, buffered by the caller when appropriate.
        """
        self.stream = stream
        self.geometry_cache: dict[int, tuple[shapely.Geometry, tuple[str, ...]]] = {}
        self.next_folder_id = 0

    def write(self, text: str) -> None:
        """Release each fragment to the destination without retaining the document.

        Args:
            text: An already escaped XML fragment.
        """
        self.stream.write(text)

    @contextlib.contextmanager
    def document(
        self,
        name: str,
        styles: typing.Iterable[str],
        *,
        description: str | None = None,
    ) -> typing.Generator[None]:
        """Keep the document envelope and its namespaces consistent for every caller.

        Args:
            name: The document's display name.
            styles: Serialized styles referenced by the document's features.
            description: Optional description text, permitting HTML inside CDATA.

        Yields:
            Control while the caller writes document features.
        """
        self.write(f'<kml xmlns="{KML_NAMESPACE}" xmlns:gx="{GX_NAMESPACE}"><Document>')
        try:
            for style in styles:
                self.write(style)
            self.write(f"<name>{escape_text(name)}</name>")
            if description is not None:
                self.write(f"<description>{escape_text(description)}</description>")
            yield
        finally:
            self.write("</Document></kml>")

    @contextlib.contextmanager
    def folder(
        self,
        name: str,
        *,
        visible: bool = True,
        list_item_type: str | None = None,
        item_icon: str | None = None,
    ) -> typing.Generator[str]:
        """Open a folder and yield its unique id, closing it on exit.

        Args:
            name: The folder's name.
            visible: Whether the folder and its children are visible. Hidden folders and
                every feature beneath them carry a zero visibility.
            list_item_type: The folder's list item type, or None for none.
            item_icon: The folder's list item icon href, or None for none.

        Yields:
            The folder's document-unique id string, used to name its tour targets.
        """
        folder_id = str(self.next_folder_id)
        self.next_folder_id += 1
        self.write("<Folder>")
        self.write(f"<name>{escape_text(name)}</name>")
        if not visible:
            self.write("<visibility>0</visibility>")
        if list_item_type is not None or item_icon is not None:
            self.write("<Style><ListStyle>")
            self.write(f"<listItemType>{list_item_type or 'check'}</listItemType>")
            if item_icon is not None:
                self.write(
                    f"<ItemIcon><href>{escape_text(item_icon)}</href></ItemIcon>",
                )
            self.write("</ListStyle></Style>")
        try:
            yield folder_id
        finally:
            self.write("</Folder>")

    def geometry_xml(self, geometry: shapely.Geometry, draw_order: int) -> str:
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
        entry = self.geometry_cache.get(id(geometry))
        if entry is None:
            if geometry.geom_type == "Polygon":
                polygons = [geometry]
            else:
                polygons = list(geometry.geoms)
            entry = (
                geometry,
                tuple(polygon_boundaries(polygon) for polygon in polygons),
            )
            self.geometry_cache[id(geometry)] = entry
        cached = entry[1]
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


def polygon_boundaries(polygon: shapely.Polygon) -> str:
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


def open_placemark(
    writer: KmlWriter,
    name: str,
    style_url: str,
    *,
    description: str | None,
    visible: bool,
    placemark_id: str | None,
) -> None:
    """Append a placemark's opening tag and metadata to *writer*.

    Args:
        writer: The KML writer to append to.
        name: The name to display for the placemark.
        style_url: The style URL to apply.
        description: The balloon description, or None to omit it.
        visible: Whether the placemark is initially visible.
        placemark_id: The placemark's XML identifier, or None to omit it.
    """
    writer.write("<Placemark")
    if placemark_id is not None:
        writer.write(f' id="{placemark_id}"')
    writer.write(">")
    writer.write(f"<name>{escape_text(name)}</name>")
    writer.write(f"<styleUrl>{style_url}</styleUrl>")
    if not visible:
        writer.write("<visibility>0</visibility>")
    if description is not None:
        writer.write(f"<description>{escape_text(description)}</description>")


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
    open_placemark(
        writer,
        name,
        style_url,
        description=description,
        visible=visible,
        placemark_id=None,
    )
    writer.write(
        f"<Point><coordinates>{coordinate_pair(point.x, point.y)}</coordinates>"
        f"<gx:drawOrder>{draw_order}</gx:drawOrder></Point>",
    )
    writer.write("</Placemark>")


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
    open_placemark(
        writer,
        name,
        style_url,
        description=description,
        visible=visible,
        placemark_id=placemark_id,
    )
    writer.write(writer.geometry_xml(polygon, draw_order))
    writer.write("</Placemark>")


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
    open_placemark(
        writer,
        name,
        style_url,
        description=description,
        visible=visible,
        placemark_id=placemark_id,
    )
    writer.write(writer.geometry_xml(multi_polygon, draw_order))
    writer.write("</Placemark>")


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
