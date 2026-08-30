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

import peri_scribe.kml.styles
import peri_scribe.output
import peri_scribe.perimeters.progression


logger = structlog.get_logger()


TEMPLATE_DIRECTORY = peri_scribe.output.DATA_DIRECTORY / "templates"


TEMPLATE_FILENAME = "PeriScribe Template.kml"


TEMPLATE_TITLE = pathlib.Path(TEMPLATE_FILENAME).stem


@dataclasses.dataclass(frozen=True, kw_only=True)
class Center:
    """A point that template geometry is centered on."""

    longitude: float
    latitude: float


POINT_CENTER = Center(longitude=10.869791666666667, latitude=45.66499166666667)


POINT_LOCATION_NAME = "Point Location"


LATEST_PERIMETERS_FOLDER_NAME = "Latest Perimeters w/ Progression Outlines"


FILLED_PERIMETER_CENTER_DISTANCE_IN_METERS = 2_000


LATEST_AREA_DRAW_ORDER = 0


SQUARE_CORNER_AZIMUTHS = (315.0, 45.0, 135.0, 225.0)


DUE_WEST_AZIMUTH = 270.0


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
        name="Latest Perimeter",
        style_id="perimeter-outline-1",
        side_length_in_meters=800,
        color="#FF0000",
    ),
    PerimeterTemplate(
        name="Penultimate Perimeter",
        style_id="perimeter-outline-2",
        side_length_in_meters=700,
        color="#FFFF00",
    ),
    PerimeterTemplate(
        name="Antepenultimate Perimeter",
        style_id="perimeter-outline-3",
        side_length_in_meters=600,
        color="#FFFFFF",
    ),
)


@dataclasses.dataclass(frozen=True, kw_only=True)
class ProgressionRendering:
    """The fictional geometry and color for one progression band in the template."""

    side_length_in_meters: int
    hole_side_length_in_meters: int | None = None
    color: str


PROGRESSION_BAND_RENDERINGS = (
    ProgressionRendering(
        side_length_in_meters=800,
        hole_side_length_in_meters=700,
        color="#FF2A00",
    ),
    ProgressionRendering(
        side_length_in_meters=700,
        hole_side_length_in_meters=600,
        color="#FF7300",
    ),
    ProgressionRendering(
        side_length_in_meters=600,
        hole_side_length_in_meters=500,
        color="#FFAA00",
    ),
    ProgressionRendering(
        side_length_in_meters=500,
        hole_side_length_in_meters=400,
        color="#B35933",
    ),
    ProgressionRendering(
        side_length_in_meters=400,
        hole_side_length_in_meters=300,
        color="#6E473B",
    ),
    ProgressionRendering(
        side_length_in_meters=300,
        hole_side_length_in_meters=200,
        color="#4A4A4A",
    ),
    ProgressionRendering(
        side_length_in_meters=200,
        hole_side_length_in_meters=100,
        color="#7A828A",
    ),
    ProgressionRendering(
        side_length_in_meters=100,
        color="#B0B7BD",
    ),
)


PROGRESSION_FILL_TEMPLATES = tuple(
    PerimeterTemplate(
        name=band.name,
        style_id=f"days-fill-{index + 1}",
        side_length_in_meters=rendering.side_length_in_meters,
        hole_side_length_in_meters=rendering.hole_side_length_in_meters,
        color=rendering.color,
    )
    for index, (band, rendering) in enumerate(
        zip(
            peri_scribe.perimeters.progression.PROGRESSION_BANDS,
            PROGRESSION_BAND_RENDERINGS,
            strict=True,
        ),
    )
)


def template_path() -> pathlib.Path:
    """Return the path where the KML template is written.

    Returns:
        The path to ``data/templates/PeriScribe Template.kml``.
    """
    return TEMPLATE_DIRECTORY / TEMPLATE_FILENAME


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
    for azimuth in SQUARE_CORNER_AZIMUTHS:
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
        DUE_WEST_AZIMUTH,
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


def point_placemark(
    container: simplekml.Container,
    center: Center,
    draw_order: int | None = None,
) -> None:
    """Add the point location placemark at *center* to *container*.

    Args:
        container: The folder that holds the placemark.
        center: The point location.
        draw_order: The order in which the point draws, or None to leave it un-ordered.
    """
    point = container.newpoint(
        name=POINT_LOCATION_NAME,
        coords=[(center.longitude, center.latitude)],
    )
    point.placemark.styleurl = f"#{peri_scribe.kml.styles.POINT_STYLE_ID}"
    if draw_order is not None:
        peri_scribe.kml.styles.set_draw_order(point, draw_order)


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
        peri_scribe.kml.styles.set_draw_order(polygon, draw_order)


def filled_perimeter_folder(document: simplekml.Document) -> None:
    """Add the "Latest Perimeters w/ Progression Outlines" folder to *document*.

    The folder's geometry is centered 2 km due west of the point location. Draw orders
    put the filled latest area on the bottom, stack the outline perimeters from oldest
    to newest, and draw the point location last so its icon is never covered.

    Args:
        document: The template's document.
    """
    folder = document.newfolder(name=LATEST_PERIMETERS_FOLDER_NAME)
    center = center_west_of(
        POINT_CENTER,
        FILLED_PERIMETER_CENTER_DISTANCE_IN_METERS,
    )
    outline_count = len(OUTLINED_PERIMETER_TEMPLATES)
    point_placemark(
        folder,
        center,
        peri_scribe.kml.styles.point_draw_order(outline_count),
    )
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
            peri_scribe.kml.styles.outline_draw_order(outline_count, index),
        )


def progression_map_folder(document: simplekml.Document) -> None:
    """Add the "Perimeter Progression Maps" folder to *document*.

    Draw orders put the oldest growth band on the bottom, stack the bands from oldest to
    newest, and draw the point location last, above the newest band, so its icon is
    never covered.

    Args:
        document: The template's document.
    """
    folder = document.newfolder(
        name=peri_scribe.perimeters.progression.PROGRESSION_MAPS_FOLDER_NAME,
    )
    band_count = len(PROGRESSION_FILL_TEMPLATES)
    point_placemark(folder, POINT_CENTER, band_count)
    for index, template in enumerate(PROGRESSION_FILL_TEMPLATES):
        perimeter_placemark(
            folder,
            template,
            POINT_CENTER,
            peri_scribe.kml.styles.band_draw_order(band_count, index),
        )


def template_kml() -> str:
    """Return the KML symbolization template as a string.

    The template has two folders that each show a fictional point and a set of fictional
    perimeters. The styles attached to those placemarks are the symbolization applied to
    real fire geography.

    Returns:
        The KML template.
    """
    # simplekml numbers every element's id from a process-wide counter; resetting it
    # keeps the template byte-for-byte reproducible across calls.
    simplekml.Kml.resetidcounter()
    kml = simplekml.Kml(name=TEMPLATE_TITLE)
    document = kml.document

    document.styles.append(peri_scribe.kml.styles.point_style())
    document.styles.append(
        peri_scribe.kml.styles.filled_perimeter_style(FILLED_PERIMETER_TEMPLATE),
    )
    for template in OUTLINED_PERIMETER_TEMPLATES:
        document.styles.append(
            peri_scribe.kml.styles.outlined_perimeter_style(template),
        )
    for template in PROGRESSION_FILL_TEMPLATES:
        document.styles.append(peri_scribe.kml.styles.filled_perimeter_style(template))

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
        The path of the written template, or None when the template already exists and
        *force* is False.
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
