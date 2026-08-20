"""Building the KML symbolization template.

The template holds a fictional point and a set of fictional perimeters whose styles
the user edits to specify how real fire geography is symbolized. Google Earth (or
another KML editor) is therefore the UI for choosing symbolization.
"""

from __future__ import annotations

import dataclasses
import math
import pathlib

import pyproj
import simplekml
import structlog

import peri_scribe.output


logger = structlog.get_logger()


TEMPLATE_DIRECTORY = peri_scribe.output.DATA_DIRECTORY / "templates"
TEMPLATE_FILENAME = "PeriScribe Template.kml"


class Style(simplekml.Style):
    """A style whose id the template assigns.

    simplekml otherwise numbers every style's id itself; the template's styles need
    stable ids so placemarks can reference them by URL.
    """

    def __init__(self, style_id: str) -> None:
        super().__init__()
        self._id = style_id


@dataclasses.dataclass(frozen=True, kw_only=True)
class Center:
    """A point that template geometry is centered on."""

    longitude: float
    latitude: float


# Near Peri, Italy
POINT_CENTER = Center(longitude=10.869791666666667, latitude=45.66499166666667)

POINT_ICON_URL = "http://maps.google.com/mapfiles/kml/shapes/firedept.png"
POINT_STYLE_ID = "point-icon"
POINT_LOCATION_NAME = "Point Location"

# Opacity and outline values shared by every perimeter style in the template.
FILL_OPACITY_PERCENT = 50
OUTLINE_OPACITY_PERCENT = 100
OUTLINE_WIDTH = 1.5

# The folder that holds each fire's point and perimeter progression outlines.
LATEST_PERIMETERS_FOLDER_NAME = "Latest Perimeters w/ Progression Outlines"

# The distance the "Latest Perimeters w/ Progression Outlines" folder's geometry is
# centered west of the point location.
FILLED_PERIMETER_CENTER_DISTANCE_IN_METERS = 2_000

# Google Earth draws overlapping features in a nondeterministic order unless each
# geometry states its place in the stack. Draw orders put the filled latest area on
# the bottom, stack the outline perimeters from oldest to newest, and draw the point
# location last so its icon is never covered. Lower values draw first.
LATEST_AREA_DRAW_ORDER = 0


@dataclasses.dataclass(frozen=True, kw_only=True)
class PerimeterTemplate:
    """A fictional perimeter and the style that symbolizes it."""

    name: str
    style_id: str
    side_length_in_meters: int
    color: str
    hole_side_length_in_meters: int | None = None


FILLED_PERIMETER_TEMPLATE = PerimeterTemplate(
    name="Interior",
    style_id="perimeter-fill",
    side_length_in_meters=800,
    color="#FF0000",
)

OUTLINED_PERIMETER_TEMPLATES = (
    PerimeterTemplate(
        name="Latest Mapping",
        style_id="perimeter-outline-1",
        side_length_in_meters=800,
        color="#FF0000",
    ),
    PerimeterTemplate(
        name="Penultimate Mapping",
        style_id="perimeter-outline-2",
        side_length_in_meters=700,
        color="#FFFF00",
    ),
    PerimeterTemplate(
        name="Antepenultimate Mapping",
        style_id="perimeter-outline-3",
        side_length_in_meters=600,
        color="#FFFFFF",
    ),
)

# Each polygon is a growth band: it fills only the area added in its day range, so
# it has a hole where the next smaller polygon sits.
PROGRESSION_FILL_TEMPLATES = (
    PerimeterTemplate(
        name="Latest Day",
        style_id="days-fill-1",
        side_length_in_meters=800,
        hole_side_length_in_meters=700,
        color="#FF2A00",
    ),
    PerimeterTemplate(
        name="2 Days Before That",
        style_id="days-fill-2",
        side_length_in_meters=700,
        hole_side_length_in_meters=600,
        color="#FF7300",
    ),
    PerimeterTemplate(
        name="4 Days Before That",
        style_id="days-fill-3",
        side_length_in_meters=600,
        hole_side_length_in_meters=500,
        color="#FFAA00",
    ),
    PerimeterTemplate(
        name="8 Days Before That",
        style_id="days-fill-4",
        side_length_in_meters=500,
        hole_side_length_in_meters=400,
        color="#B35933",
    ),
    PerimeterTemplate(
        name="16 Days Before That",
        style_id="days-fill-5",
        side_length_in_meters=400,
        hole_side_length_in_meters=300,
        color="#6E473B",
    ),
    PerimeterTemplate(
        name="32 Days Before That",
        style_id="days-fill-6",
        side_length_in_meters=300,
        hole_side_length_in_meters=200,
        color="#4A4A4A",
    ),
    PerimeterTemplate(
        name="64 Days Before That",
        style_id="days-fill-7",
        side_length_in_meters=200,
        hole_side_length_in_meters=100,
        color="#7A828A",
    ),
    PerimeterTemplate(
        name="128+ Days Before That",
        style_id="days-fill-8",
        side_length_in_meters=100,
        color="#B0B7BD",
    ),
)


def template_path() -> pathlib.Path:
    """Return the path where the KML template is written.

    Returns:
        The path to ``data/templates/PeriScribe Template.kml``.
    """
    return TEMPLATE_DIRECTORY / TEMPLATE_FILENAME


def kml_color(red_green_blue: str, opacity_percent: int) -> str:
    """Return the KML ``aabbggrr`` color for *red_green_blue* at an opacity.

    Args:
        red_green_blue: The color as ``#RRGGBB``.
        opacity_percent: The opacity from 0 (transparent) to 100 (opaque).

    Returns:
        The KML color string.
    """
    red = red_green_blue[1:3]
    green = red_green_blue[3:5]
    blue = red_green_blue[5:7]
    alpha = opacity_percent * 255 // 100
    return f"{alpha:02x}{blue}{green}{red}".lower()


# Outline polygons get a transparent white fill because Google Earth does not drape
# an unfilled polygon on the terrain, so its border would not follow the ground
# contour.
TRANSPARENT_FILL_COLOR = kml_color("#FFFFFF", 0)


def square_coordinates(
    side_length_in_meters: int,
    center: Center,
) -> list[tuple[float, float]]:
    """Return the corner coordinates of a square centered on *center*.

    Args:
        side_length_in_meters: The length of each side of the square.
        center: The center point of the square.

    Returns:
        The four (longitude, latitude) corners, closed so the first coordinate is
        repeated at the end.
    """
    geodesic = pyproj.Geod(ellps="WGS84")
    half_diagonal_in_meters = side_length_in_meters * math.sqrt(2) / 2
    corners: list[tuple[float, float]] = []
    for azimuth in (315.0, 45.0, 135.0, 225.0):
        longitude, latitude, _ = geodesic.fwd(
            center.longitude,
            center.latitude,
            azimuth,
            half_diagonal_in_meters,
        )
        corners.append((longitude, latitude))
    corners.append(corners[0])
    return corners


def center_west_of(center: Center, distance_in_meters: int) -> Center:
    """Return the point *distance_in_meters* due west of *center*.

    Args:
        center: The point to move west from.
        distance_in_meters: The distance to move due west.

    Returns:
        The point due west of *center*.
    """
    geodesic = pyproj.Geod(ellps="WGS84")
    longitude, latitude, _ = geodesic.fwd(
        center.longitude,
        center.latitude,
        270.0,
        distance_in_meters,
    )
    return Center(longitude=longitude, latitude=latitude)


def reversed_ring(coordinates: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Return *coordinates* in reverse order, keeping the ring closed.

    The ring is reversed so a polygon's hole winds opposite to its outer boundary,
    which is how renderers tell a hole apart from a filled area.

    Args:
        coordinates: A closed ring of (longitude, latitude) coordinates.

    Returns:
        The ring traversed in the opposite direction.
    """
    return [coordinates[0], *reversed(coordinates[1:-1]), coordinates[0]]


def set_draw_order(
    geometry: simplekml.Point | simplekml.Polygon | simplekml.MultiGeometry,
    draw_order: int,
) -> None:
    """Set the gx:drawOrder of *geometry* to *draw_order*.

    simplekml exposes gx:drawOrder only on LineString, but every geometry
    serializes from the same internal element map, so the tag is set there for
    points and polygons alike. A multi-geometry carries no draw order of its
    own: the order goes on each geometry it contains, because Google Earth
    ignores the tag on the MultiGeometry element itself.

    Args:
        geometry: The geometry to order.
        draw_order: Lower values draw first, underneath later features.
    """
    if isinstance(geometry, simplekml.MultiGeometry):
        for contained_geometry in geometry._geometries:  # ruff: ignore[private-member-access]
            set_draw_order(contained_geometry, draw_order)
    else:
        geometry._kml["gx:drawOrder"] = draw_order  # ruff: ignore[private-member-access]


def outline_draw_order(outline_count: int, newest_first_index: int) -> int:
    """Return the draw order of the outline at *newest_first_index*.

    Outlines draw from oldest to newest, so the oldest outline draws first and
    the newest draws last, above the others.

    Args:
        outline_count: The number of outlines drawn for the fire.
        newest_first_index: The outline's position counting from the newest
            outline first, where 0 is the newest.

    Returns:
        The draw order, from 1 for the oldest outline to outline_count for the
        newest.
    """
    return outline_count - newest_first_index


def band_draw_order(band_count: int, newest_first_index: int) -> int:
    """Return the draw order of the growth band at *newest_first_index*.

    Bands draw from oldest to newest, so the oldest band draws first, at the
    bottom of the stack, and the newest draws last, above the others.

    Args:
        band_count: The number of bands drawn in the progression map.
        newest_first_index: The band's position counting from the newest band
            first, where 0 is the newest.

    Returns:
        The draw order, from 0 for the oldest band to band_count - 1 for the
        newest.
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


def filled_perimeter_style(template: PerimeterTemplate) -> Style:
    """Return the fill style for *template*.

    Args:
        template: The perimeter the style symbolizes.

    Returns:
        The style, with a filled polygon style.
    """
    style = Style(template.style_id)
    style.polystyle.color = kml_color(template.color, FILL_OPACITY_PERCENT)
    style.polystyle.fill = 1
    style.polystyle.outline = 0
    return style


def outlined_perimeter_style(template: PerimeterTemplate) -> Style:
    """Return the outline style for *template*.

    Args:
        template: The perimeter the style symbolizes.

    Returns:
        The style, with a line style and a transparently filled polygon style.
    """
    style = Style(template.style_id)
    style.linestyle.color = kml_color(template.color, OUTLINE_OPACITY_PERCENT)
    style.linestyle.width = OUTLINE_WIDTH
    style.polystyle.color = TRANSPARENT_FILL_COLOR
    style.polystyle.fill = 1
    style.polystyle.outline = 1
    return style


def point_placemark(
    container: simplekml.Container,
    center: Center,
    draw_order: int | None = None,
) -> None:
    """Add the point location placemark at *center* to *container*.

    Args:
        container: The folder that holds the placemark.
        center: The point location.
        draw_order: The order in which the point draws, or None to leave it
            un-ordered.
    """
    point = container.newpoint(
        name=POINT_LOCATION_NAME,
        coords=[(center.longitude, center.latitude)],
    )
    point.placemark.styleurl = f"#{POINT_STYLE_ID}"
    if draw_order is not None:
        set_draw_order(point, draw_order)


def perimeter_placemark(
    container: simplekml.Container,
    template: PerimeterTemplate,
    center: Center,
    draw_order: int | None = None,
) -> None:
    """Add the fictional perimeter *template* centered on *center* to *container*.

    The perimeter is a square; the square inside its hole is cut out of it.

    Args:
        container: The folder that holds the placemark.
        template: The perimeter to represent.
        center: The center point of the perimeter.
        draw_order: The order in which the perimeter draws, or None to leave it
            un-ordered.
    """
    polygon = container.newpolygon(
        name=template.name,
        outerboundaryis=square_coordinates(
            template.side_length_in_meters,
            center,
        ),
    )
    polygon.placemark.styleurl = f"#{template.style_id}"
    if template.hole_side_length_in_meters is not None:
        polygon.innerboundaryis = [
            reversed_ring(
                square_coordinates(
                    template.hole_side_length_in_meters,
                    center,
                ),
            ),
        ]
    if draw_order is not None:
        set_draw_order(polygon, draw_order)


def filled_perimeter_folder(document: simplekml.Document) -> None:
    """Add the "Latest Perimeters w/ Progression Outlines" folder to *document*.

    The folder's geometry is centered 2 km due west of the point location. Draw
    orders put the filled latest area on the bottom, stack the outline perimeters
    from oldest to newest, and draw the point location last so its icon is never
    covered.

    Args:
        document: The template's document.
    """
    folder = document.newfolder(name=LATEST_PERIMETERS_FOLDER_NAME)
    center = center_west_of(
        POINT_CENTER,
        FILLED_PERIMETER_CENTER_DISTANCE_IN_METERS,
    )
    outline_count = len(OUTLINED_PERIMETER_TEMPLATES)
    point_placemark(folder, center, point_draw_order(outline_count))
    perimeter_placemark(
        folder,
        FILLED_PERIMETER_TEMPLATE,
        center,
        LATEST_AREA_DRAW_ORDER,
    )
    for index, template in enumerate(OUTLINED_PERIMETER_TEMPLATES):
        perimeter_placemark(
            folder,
            template,
            center,
            outline_draw_order(outline_count, index),
        )


def progression_map_folder(document: simplekml.Document) -> None:
    """Add the "Perimeter Progression Maps" folder to *document*.

    Draw orders put the oldest growth band on the bottom, stack the bands from
    oldest to newest, and draw the point location last, above the newest band,
    so its icon is never covered.

    Args:
        document: The template's document.
    """
    folder = document.newfolder(name="Perimeter Progression Maps")
    band_count = len(PROGRESSION_FILL_TEMPLATES)
    point_placemark(folder, POINT_CENTER, band_count)
    for index, template in enumerate(PROGRESSION_FILL_TEMPLATES):
        perimeter_placemark(
            folder,
            template,
            POINT_CENTER,
            band_draw_order(band_count, index),
        )


def template_kml() -> str:
    """Return the KML symbolization template as a string.

    The template has two folders that each show a fictional point and a set of
    fictional perimeters. The styles attached to those placemarks are the
    symbolization applied to real fire geography.

    Returns:
        The KML template.
    """
    # simplekml numbers every element's id from a process-wide counter; resetting it
    # keeps the template byte-for-byte reproducible across calls.
    simplekml.Kml.resetidcounter()
    kml = simplekml.Kml()
    document = kml.document

    document.styles.append(point_style())
    document.styles.append(filled_perimeter_style(FILLED_PERIMETER_TEMPLATE))
    for template in OUTLINED_PERIMETER_TEMPLATES:
        document.styles.append(outlined_perimeter_style(template))
    for template in PROGRESSION_FILL_TEMPLATES:
        document.styles.append(filled_perimeter_style(template))

    filled_perimeter_folder(document)
    progression_map_folder(document)
    return kml.kml()


def write_template(path: pathlib.Path) -> None:
    """Write the KML symbolization template to *path*.

    Args:
        path: The KML file to write.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        file.write(template_kml())


def create_template(*, force: bool = False) -> pathlib.Path | None:
    """Build and write the KML symbolization template.

    Args:
        force: Overwrite the template when it already exists.

    Returns:
        The path of the written template, or None when the template already
        exists and *force* is False.
    """
    output_path = template_path()
    if output_path.exists() and not force:
        logger.error(
            "KML template already exists; not overwriting",
            path=output_path,
        )
        return None
    write_template(output_path)
    return output_path
