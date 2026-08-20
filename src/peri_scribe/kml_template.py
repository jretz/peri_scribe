"""Building the KML symbolization template.

The template holds a fictional point and a set of fictional perimeters whose styles
the user edits to specify how real fire geography is symbolized. Google Earth (or
another KML editor) is therefore the UI for choosing symbolization.
"""

from __future__ import annotations

import dataclasses
import math
import pathlib

import fastkml
import pyproj
import structlog

import peri_scribe.output


logger = structlog.get_logger()


TEMPLATE_DIRECTORY = peri_scribe.output.DATA_DIRECTORY / "templates"
TEMPLATE_FILENAME = "PeriScribe Template.kml"


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


@dataclasses.dataclass(frozen=True, kw_only=True)
class PerimeterTemplate:
    """A fictional perimeter and the style that symbolizes it."""

    name: str
    style_id: str
    side_length_in_meters: int
    color: str
    hole_side_length_in_meters: int | None = None


FILLED_PERIMETER_TEMPLATE = PerimeterTemplate(
    name="Latest Area",
    style_id="perimeter-fill",
    side_length_in_meters=800,
    color="#FF0000",
)

OUTLINED_PERIMETER_TEMPLATES = (
    PerimeterTemplate(
        name="Latest Outline",
        style_id="perimeter-outline-1",
        side_length_in_meters=800,
        color="#FF0000",
    ),
    PerimeterTemplate(
        name="Penultimate Outline",
        style_id="perimeter-outline-2",
        side_length_in_meters=700,
        color="#FFFF00",
    ),
    PerimeterTemplate(
        name="Antepenultimate Outline",
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


def point_style() -> fastkml.Style:
    """Return the style for the fictional point location.

    Returns:
        The style, holding the point's icon.
    """
    return fastkml.Style(
        id=POINT_STYLE_ID,
        styles=[fastkml.IconStyle(icon_href=POINT_ICON_URL)],
    )


def point_placemark(center: Center) -> fastkml.Placemark:
    """Return the placemark for a point location at *center*.

    Args:
        center: The point location.

    Returns:
        The placemark.
    """
    return fastkml.Placemark(
        name=POINT_LOCATION_NAME,
        style_url=fastkml.StyleUrl(url=f"#{POINT_STYLE_ID}"),
        kml_geometry=fastkml.Point(
            kml_coordinates=fastkml.Coordinates(
                coords=[(center.longitude, center.latitude)],
            ),
        ),
    )


def square_polygon(
    side_length_in_meters: int,
    center: Center,
    hole_side_length_in_meters: int | None = None,
) -> fastkml.Polygon:
    """Return a square KML polygon centered on *center*.

    Args:
        side_length_in_meters: The length of each side of the square.
        center: The center point of the square.
        hole_side_length_in_meters: The length of each side of a centered hole, or
            None for a solid square.

    Returns:
        The polygon.
    """
    outer_boundary = fastkml.OuterBoundaryIs(
        kml_geometry=fastkml.LinearRing(
            kml_coordinates=fastkml.Coordinates(
                coords=square_coordinates(side_length_in_meters, center),
            ),
        ),
    )
    if hole_side_length_in_meters is None:
        return fastkml.Polygon(outer_boundary=outer_boundary)
    hole_ring = fastkml.LinearRing(
        kml_coordinates=fastkml.Coordinates(
            coords=reversed_ring(
                square_coordinates(hole_side_length_in_meters, center),
            ),
        ),
    )
    return fastkml.Polygon(
        outer_boundary=outer_boundary,
        inner_boundaries=[fastkml.InnerBoundaryIs(kml_geometry=hole_ring)],
    )


def filled_perimeter_style(template: PerimeterTemplate) -> fastkml.Style:
    """Return the fill style for *template*.

    Args:
        template: The perimeter the style symbolizes.

    Returns:
        The style, with a filled polygon style.
    """
    return fastkml.Style(
        id=template.style_id,
        styles=[
            fastkml.PolyStyle(
                color=kml_color(template.color, FILL_OPACITY_PERCENT),
                fill=True,
                outline=False,
            ),
        ],
    )


def outlined_perimeter_style(template: PerimeterTemplate) -> fastkml.Style:
    """Return the outline style for *template*.

    Args:
        template: The perimeter the style symbolizes.

    Returns:
        The style, with a line style and a transparently filled polygon style.
    """
    return fastkml.Style(
        id=template.style_id,
        styles=[
            fastkml.LineStyle(
                color=kml_color(template.color, OUTLINE_OPACITY_PERCENT),
                width=OUTLINE_WIDTH,
            ),
            fastkml.PolyStyle(
                color=TRANSPARENT_FILL_COLOR,
                fill=True,
                outline=True,
            ),
        ],
    )


def perimeter_placemark(
    template: PerimeterTemplate,
    center: Center,
) -> fastkml.Placemark:
    """Return the placemark for the fictional perimeter *template* centered on *center*.

    Args:
        template: The perimeter to represent.
        center: The center point of the perimeter.

    Returns:
        The placemark.
    """
    return fastkml.Placemark(
        name=template.name,
        style_url=fastkml.StyleUrl(url=f"#{template.style_id}"),
        kml_geometry=square_polygon(
            template.side_length_in_meters,
            center,
            template.hole_side_length_in_meters,
        ),
    )


def filled_perimeter_folder() -> fastkml.Folder:
    """Return the "Latest Perimeters w/ Progression Outlines" folder.

    The folder's geometry is centered 2 km due west of the point location.

    Returns:
        The folder.
    """
    center = center_west_of(POINT_CENTER, FILLED_PERIMETER_CENTER_DISTANCE_IN_METERS)
    folder = fastkml.Folder(name=LATEST_PERIMETERS_FOLDER_NAME)
    folder.append(point_placemark(center))
    folder.append(perimeter_placemark(FILLED_PERIMETER_TEMPLATE, center))
    for template in OUTLINED_PERIMETER_TEMPLATES:
        folder.append(perimeter_placemark(template, center))
    return folder


def progression_map_folder() -> fastkml.Folder:
    """Return the "Perimeter Progression Maps" folder.

    Returns:
        The folder.
    """
    folder = fastkml.Folder(name="Perimeter Progression Maps")
    folder.append(point_placemark(POINT_CENTER))
    for template in PROGRESSION_FILL_TEMPLATES:
        folder.append(perimeter_placemark(template, POINT_CENTER))
    return folder


def template_kml() -> str:
    """Return the KML symbolization template as a string.

    The template has two folders that each show a fictional point and a set of
    fictional perimeters. The styles attached to those placemarks are the
    symbolization applied to real fire geography.

    Returns:
        The KML template.
    """
    kml = fastkml.KML()
    document = fastkml.Document()
    kml.append(document)

    document.styles.append(point_style())
    document.styles.append(filled_perimeter_style(FILLED_PERIMETER_TEMPLATE))
    for template in OUTLINED_PERIMETER_TEMPLATES:
        document.styles.append(outlined_perimeter_style(template))
    for template in PROGRESSION_FILL_TEMPLATES:
        document.styles.append(filled_perimeter_style(template))

    document.append(filled_perimeter_folder())
    document.append(progression_map_folder())
    return kml.to_string()


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
