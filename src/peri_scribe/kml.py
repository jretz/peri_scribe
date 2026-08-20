"""Building the KML output for a year's fires.

The output is a compressed KML document (a KMZ file). The symbolization comes from the
KML template file: its styles are copied into the output, and each fire's placemarks
reuse the style URLs the template assigns to the corresponding placemarks.
"""

from __future__ import annotations

import dataclasses
import pathlib
import typing

# The template is a local, user-edited file rather than untrusted input, so the
# stdlib XML parser needs no defusedxml hardening.
import xml.etree.ElementTree as ET  # ruff: ignore[suspicious-xml-etree-import]
import zipfile

import geopandas
import simplekml

import peri_scribe.fire_history
import peri_scribe.fire_index
import peri_scribe.geo_data
import peri_scribe.kml_template
import peri_scribe.models


if typing.TYPE_CHECKING:
    import shapely


KML_NAMESPACE = "http://www.opengis.net/kml/2.2"

MAPS_DIRECTORY_NAME = "maps"

ACTIVE_FIRES_FOLDER_NAME = "Active Fires"
INACTIVE_FIRES_FOLDER_NAME = "Inactive Fires"

KMZ_DOCUMENT_FILENAME = "doc.kml"

# DEFLATE is the compression Google Earth expects inside a KMZ, and level 9 is the
# highest compression level it offers.
KMZ_COMPRESSION = zipfile.ZIP_DEFLATED
KMZ_COMPRESSION_LEVEL = 9


@dataclasses.dataclass(frozen=True, kw_only=True)
class FireGeometry:
    """One fire's point and perimeters, ready to symbolize."""

    name: str
    status: peri_scribe.models.FireStatus
    point: shapely.Point | None
    perimeters: tuple[shapely.Geometry, ...]


@dataclasses.dataclass(frozen=True, kw_only=True)
class Template:
    """The parsed KML template's styles and placemark style URLs."""

    styles: tuple[peri_scribe.kml_template.Style, ...]
    style_urls: dict[str, str]


def kml_tag(name: str) -> str:
    """Return the namespaced element tag for *name*.

    Args:
        name: The KML element name.

    Returns:
        The tag ElementTree uses for the element.
    """
    return f"{{{KML_NAMESPACE}}}{name}"


def year_from(year_directory: pathlib.Path) -> int:
    """Return the year named by *year_directory*.

    Args:
        year_directory: The year directory, whose name is the year.

    Returns:
        The year as an integer.
    """
    return int(year_directory.name)


def kmz_filename(year: int) -> str:
    """Return the KMZ filename for *year*.

    Args:
        year: The year the output describes.

    Returns:
        The filename.
    """
    return f"PeriScribe Fires {year}.kmz"


def kmz_path(year_directory: pathlib.Path) -> pathlib.Path:
    """Return the path of the KMZ output for *year_directory*.

    Args:
        year_directory: The year directory that holds the ``maps`` directory.

    Returns:
        The output KMZ path.
    """
    return (
        year_directory / MAPS_DIRECTORY_NAME / kmz_filename(year_from(year_directory))
    )


def read_history_layer(
    path: pathlib.Path,
    layer_name: str,
) -> geopandas.GeoDataFrame:
    """Read *layer_name* from the GeoPackage at *path*.

    Args:
        path: The GeoPackage to read.
        layer_name: The layer to read.

    Returns:
        The layer as a GeoDataFrame.
    """
    return geopandas.read_file(path, layer=layer_name)


def identifiers(
    entry: peri_scribe.models.FireIndexEntry,
) -> frozenset[str]:
    """Return every identifier known for *entry*.

    Args:
        entry: One fire index entry.

    Returns:
        The entry's canonical identifier and aliases.
    """
    candidates = [entry.identifier, *entry.aliases]
    return frozenset(identifier for identifier in candidates if identifier is not None)


def perimeter_groups(
    perimeters: geopandas.GeoDataFrame,
) -> tuple[
    dict[str, list[shapely.Geometry]],
    dict[str, list[shapely.Geometry]],
]:
    """Group perimeter geometries by fire, preserving chronological order.

    Fires are keyed by identifier when one is known, and by name otherwise.

    Args:
        perimeters: The perimeter history layer.

    Returns:
        Perimeters keyed by identifier and by name.
    """
    by_identifier: dict[str, list[shapely.Geometry]] = {}
    by_name: dict[str, list[shapely.Geometry]] = {}
    for identifier, name, geometry in zip(
        perimeters["fire_identifier"],
        perimeters["fire_name"],
        perimeters.geometry,
        strict=True,
    ):
        if peri_scribe.geo_data.is_missing(identifier):
            by_name.setdefault(str(name), []).append(geometry)
        else:
            by_identifier.setdefault(str(identifier), []).append(geometry)
    return by_identifier, by_name


def point_locations(
    points: geopandas.GeoDataFrame,
) -> tuple[dict[str, shapely.Point], dict[str, shapely.Point]]:
    """Return each fire's last known point location.

    Later rows overwrite earlier ones, so each fire keeps the most recent point. Fires
    are keyed by identifier when one is known, and by name otherwise.

    Args:
        points: The point history layer.

    Returns:
        Points keyed by identifier and by name.
    """
    by_identifier: dict[str, shapely.Point] = {}
    by_name: dict[str, shapely.Point] = {}
    for identifier, name, geometry in zip(
        points["fire_identifier"],
        points["fire_name"],
        points.geometry,
        strict=True,
    ):
        if peri_scribe.geo_data.is_missing(identifier):
            by_name[str(name)] = geometry
        else:
            by_identifier[str(identifier)] = geometry
    return by_identifier, by_name


def fire_point(
    fire_identifiers: frozenset[str],
    entry_name: str,
    point_by_identifier: dict[str, shapely.Point],
    point_by_name: dict[str, shapely.Point],
) -> shapely.Point | None:
    """Return the point location for one fire, or None.

    Args:
        fire_identifiers: The fire's identifiers.
        entry_name: The fire's name.
        point_by_identifier: Points keyed by identifier.
        point_by_name: Points keyed by name.

    Returns:
        The fire's point location, or None when it has none.
    """
    for identifier in sorted(fire_identifiers):
        if identifier in point_by_identifier:
            return point_by_identifier[identifier]
    if not fire_identifiers:
        return point_by_name.get(entry_name)
    return None


def fire_point_location(
    fire_identifiers: frozenset[str],
    entry_name: str,
    point_by_identifier: dict[str, shapely.Point],
    point_by_name: dict[str, shapely.Point],
    perimeters: tuple[shapely.Geometry, ...],
) -> shapely.Point | None:
    """Return the point location to show for one fire, or None.

    The last known point location is used when the fire has one. A fire without a
    known location falls back to a representative point of its latest perimeter,
    because its icon still needs somewhere to draw. The point source drops
    inactive fires while their perimeters remain available, so this fallback
    keeps their icons in the output.

    Args:
        fire_identifiers: The fire's identifiers.
        entry_name: The fire's name.
        point_by_identifier: Points keyed by identifier.
        point_by_name: Points keyed by name.
        perimeters: The fire's perimeters in chronological order.

    Returns:
        The fire's point location, or None when it has neither a known location
        nor any perimeter to derive one from.
    """
    point = fire_point(
        fire_identifiers,
        entry_name,
        point_by_identifier,
        point_by_name,
    )
    if point is not None:
        return point
    if perimeters:
        return perimeters[-1].representative_point()
    return None


def fire_perimeters(
    fire_identifiers: frozenset[str],
    entry_name: str,
    perimeter_by_identifier: dict[str, list[shapely.Geometry]],
    perimeter_by_name: dict[str, list[shapely.Geometry]],
) -> tuple[shapely.Geometry, ...]:
    """Return one fire's perimeters in chronological order.

    Args:
        fire_identifiers: The fire's identifiers.
        entry_name: The fire's name.
        perimeter_by_identifier: Perimeters keyed by identifier.
        perimeter_by_name: Perimeters keyed by name.

    Returns:
        The fire's perimeters, oldest first.
    """
    perimeters: list[shapely.Geometry] = []
    for identifier in sorted(fire_identifiers):
        perimeters.extend(perimeter_by_identifier.get(identifier, []))
    if not fire_identifiers:
        perimeters.extend(perimeter_by_name.get(entry_name, []))
    return tuple(perimeters)


def fire_geometries(
    index: peri_scribe.models.FireIndex,
    perimeters: geopandas.GeoDataFrame,
    points: geopandas.GeoDataFrame,
) -> list[FireGeometry]:
    """Return each indexed fire's geometry, sorted by case-folded name.

    Each fire's point is its last known location, or a representative point of its
    latest perimeter when no location is known.

    Args:
        index: The fire index that names each fire and its status.
        perimeters: The perimeter history layer.
        points: The point history layer.

    Returns:
        One entry per indexed fire, sorted by case-folded name.
    """
    perimeter_by_identifier, perimeter_by_name = perimeter_groups(perimeters)
    point_by_identifier, point_by_name = point_locations(points)
    fires: list[FireGeometry] = []
    for entry in index.fires:
        fire_identifiers = identifiers(entry)
        perimeter_geometries = fire_perimeters(
            fire_identifiers,
            entry.name,
            perimeter_by_identifier,
            perimeter_by_name,
        )
        fires.append(
            FireGeometry(
                name=entry.name,
                status=peri_scribe.models.FireStatus(entry.status),
                point=fire_point_location(
                    fire_identifiers,
                    entry.name,
                    point_by_identifier,
                    point_by_name,
                    perimeter_geometries,
                ),
                perimeters=perimeter_geometries,
            ),
        )
    return sorted(fires, key=lambda fire: fire.name.casefold())


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
) -> None:
    """Add the point placemark for *point* named *name* to *container*.

    Args:
        container: The folder that holds the placemark.
        name: The name to show for the point.
        style_url: The style URL to apply.
        point: The point geometry.
        draw_order: The order in which the point draws; it draws last, above the
            perimeters.
    """
    placemark = container.newpoint(name=name, coords=[(point.x, point.y)])
    placemark.placemark.styleurl = style_url
    peri_scribe.kml_template.set_draw_order(placemark, draw_order)


def polygon_geometry(
    container: simplekml.Container,
    name: str,
    style_url: str,
    polygon: shapely.Polygon,
    draw_order: int,
) -> None:
    """Add the polygon placemark for *polygon* to *container*.

    Args:
        container: The folder that holds the placemark.
        name: The placemark name.
        style_url: The style URL to apply.
        polygon: The shapely polygon to convert.
        draw_order: The order in which the polygon draws.
    """
    placemark = container.newpolygon(
        name=name,
        outerboundaryis=ring_coordinates(polygon.exterior),
    )
    placemark.placemark.styleurl = style_url
    if polygon.interiors:
        placemark.innerboundaryis = [
            ring_coordinates(interior) for interior in polygon.interiors
        ]
    peri_scribe.kml_template.set_draw_order(placemark, draw_order)


def multi_polygon_geometry(
    container: simplekml.Container,
    name: str,
    style_url: str,
    multi_polygon: shapely.MultiPolygon,
    draw_order: int,
) -> None:
    """Add the multi-geometry placemark for *multi_polygon* to *container*.

    Args:
        container: The folder that holds the placemark.
        name: The placemark name.
        style_url: The style URL to apply.
        multi_polygon: The shapely multi-polygon to convert.
        draw_order: The order in which the multi-geometry draws.
    """
    geometry = container.newmultigeometry(name=name)
    geometry.placemark.styleurl = style_url
    for polygon in multi_polygon.geoms:
        polygon = typing.cast("shapely.Polygon", polygon)
        geometry.newpolygon(
            outerboundaryis=ring_coordinates(polygon.exterior),
            innerboundaryis=[
                ring_coordinates(interior) for interior in polygon.interiors
            ],
        )
    peri_scribe.kml_template.set_draw_order(geometry, draw_order)


def perimeter_geometry(
    container: simplekml.Container,
    name: str,
    style_url: str,
    geometry: shapely.Geometry,
    draw_order: int,
) -> None:
    """Add the placemark for *geometry* to *container*.

    Args:
        container: The folder that holds the placemark.
        name: The placemark name.
        style_url: The style URL to apply.
        geometry: A shapely polygon or multi-polygon.
        draw_order: The order in which the geometry draws.
    """
    if geometry.geom_type == "Polygon":
        polygon_geometry(
            container,
            name,
            style_url,
            typing.cast("shapely.Polygon", geometry),
            draw_order,
        )
    else:
        multi_polygon_geometry(
            container,
            name,
            style_url,
            typing.cast("shapely.MultiPolygon", geometry),
            draw_order,
        )


def perimeter_placemark(
    container: simplekml.Container,
    name: str,
    style_url: str,
    geometry: shapely.Geometry,
    draw_order: int,
) -> None:
    """Add the perimeter placemark for *geometry* to *container*.

    Args:
        container: The folder that holds the placemark.
        name: The placemark name.
        style_url: The style URL to apply.
        geometry: The perimeter geometry.
        draw_order: The order in which the perimeter draws.
    """
    perimeter_geometry(container, name, style_url, geometry, draw_order)


def fire_folder(
    container: simplekml.Container,
    fire: FireGeometry,
    style_urls: typing.Mapping[str, str],
) -> None:
    """Add the folder symbolizing *fire* to *container*.

    The folder holds the fire's point location and its latest, penultimate, and
    antepenultimate perimeters, each shown when the fire's history has one. Draw
    orders put the filled latest area on the bottom, stack the outline perimeters
    from oldest to newest, and draw the point location last so its icon is never
    covered.

    Args:
        container: The folder that holds the fire's folder.
        fire: The fire to symbolize.
        style_urls: The style URL for each template placemark name.
    """
    folder = container.newfolder(name=fire.name)
    outline_count = min(
        len(fire.perimeters),
        len(peri_scribe.kml_template.OUTLINED_PERIMETER_TEMPLATES),
    )
    if fire.point is not None:
        point_placemark(
            folder,
            fire.name,
            style_urls[peri_scribe.kml_template.POINT_LOCATION_NAME],
            fire.point,
            peri_scribe.kml_template.point_draw_order(outline_count),
        )
    if fire.perimeters:
        perimeter_placemark(
            folder,
            peri_scribe.kml_template.FILLED_PERIMETER_TEMPLATE.name,
            style_urls[peri_scribe.kml_template.FILLED_PERIMETER_TEMPLATE.name],
            fire.perimeters[-1],
            peri_scribe.kml_template.LATEST_AREA_DRAW_ORDER,
        )
    for index, template in enumerate(
        peri_scribe.kml_template.OUTLINED_PERIMETER_TEMPLATES,
    ):
        if len(fire.perimeters) <= index:
            break
        perimeter_placemark(
            folder,
            template.name,
            style_urls[template.name],
            fire.perimeters[-(index + 1)],
            peri_scribe.kml_template.outline_draw_order(outline_count, index),
        )


def latest_perimeters_folder(
    container: simplekml.Container,
    fires: list[FireGeometry],
    style_urls: typing.Mapping[str, str],
) -> None:
    """Add the folder holding each fire's symbolized geometry to *container*.

    Args:
        container: The folder that holds the perimeters folder.
        fires: The fires to place in the folder.
        style_urls: The style URL for each template placemark name.
    """
    folder = container.newfolder(
        name=peri_scribe.kml_template.LATEST_PERIMETERS_FOLDER_NAME,
    )
    for fire in fires:
        fire_folder(folder, fire, style_urls)


def status_folder_name(status: peri_scribe.models.FireStatus) -> str:
    """Return the top-level folder name for *status*.

    Args:
        status: The fire status.

    Returns:
        The folder name.
    """
    if status is peri_scribe.models.FireStatus.ACTIVE:
        return ACTIVE_FIRES_FOLDER_NAME
    return INACTIVE_FIRES_FOLDER_NAME


def status_folder(
    container: simplekml.Container,
    fires: list[FireGeometry],
    status: peri_scribe.models.FireStatus,
    style_urls: typing.Mapping[str, str],
) -> None:
    """Add the top-level folder for fires of *status* to *container*.

    Args:
        container: The document that holds the status folder.
        fires: Every fire.
        status: The status whose fires belong in the folder.
        style_urls: The style URL for each template placemark name.
    """
    folder = container.newfolder(name=status_folder_name(status))
    latest_perimeters_folder(
        folder,
        [fire for fire in fires if fire.status is status],
        style_urls,
    )


def style_from(element: ET.Element) -> peri_scribe.kml_template.Style:
    """Return the template style that *element* defines.

    The template's styles are icon, line, and polygon styles, so those are the
    sub-styles read from *element*.

    Args:
        element: The parsed ``Style`` element.

    Returns:
        The style, holding the sub-styles *element* defines.

    Raises:
        ValueError: When *element* has no id attribute.
    """
    style_id = element.get("id")
    if style_id is None:
        message = "KML Style element has no id attribute"
        raise ValueError(message)
    style = peri_scribe.kml_template.Style(style_id)
    icon_style = element.find(kml_tag("IconStyle"))
    if icon_style is not None:
        icon_href = icon_style.findtext(
            f"{kml_tag('Icon')}/{kml_tag('href')}",
        )
        if icon_href is not None:
            style.iconstyle.icon.href = icon_href
    line_style = element.find(kml_tag("LineStyle"))
    if line_style is not None:
        line_color = line_style.findtext(kml_tag("color"))
        if line_color is not None:
            style.linestyle.color = line_color
        line_width = line_style.findtext(kml_tag("width"))
        if line_width is not None:
            style.linestyle.width = float(line_width)
    poly_style = element.find(kml_tag("PolyStyle"))
    if poly_style is not None:
        poly_color = poly_style.findtext(kml_tag("color"))
        if poly_color is not None:
            style.polystyle.color = poly_color
        fill = poly_style.findtext(kml_tag("fill"))
        if fill is not None:
            style.polystyle.fill = int(fill)
        outline = poly_style.findtext(kml_tag("outline"))
        if outline is not None:
            style.polystyle.outline = int(outline)
    return style


def placemark_style_urls(document: ET.Element) -> dict[str, str]:
    """Return each template placemark's style URL, keyed by name.

    Args:
        document: The parsed template document element.

    Returns:
        The style URL for each placemark name.
    """
    urls: dict[str, str] = {}
    collect_placemark_style_urls(document, urls)
    return urls


def collect_placemark_style_urls(
    element: ET.Element,
    urls: dict[str, str],
) -> None:
    """Record each named placemark's style URL into *urls*.

    Args:
        element: The element to search, descending into folders.
        urls: The mapping being built.
    """
    for child in element:
        if child.tag == kml_tag("Folder"):
            collect_placemark_style_urls(child, urls)
        elif child.tag == kml_tag("Placemark"):
            name = child.findtext(kml_tag("name"))
            style_url = child.findtext(kml_tag("styleUrl"))
            if name is not None and style_url is not None:
                urls[name] = style_url


def template_from(kml_text: str) -> Template:
    """Parse *kml_text* into the template's styles and style URLs.

    Args:
        kml_text: The KML template document.

    Returns:
        The template.

    Raises:
        ValueError: When *kml_text* has no Document element.
    """
    root = ET.fromstring(kml_text)  # ruff: ignore[suspicious-xml-element-tree-usage]
    document = root.find(kml_tag("Document"))
    if document is None:
        message = "KML template has no Document element"
        raise ValueError(message)
    return Template(
        styles=tuple(
            style_from(style) for style in document if style.tag == kml_tag("Style")
        ),
        style_urls=placemark_style_urls(document),
    )


def read_template(path: pathlib.Path) -> Template:
    """Read and parse the KML template at *path*.

    Args:
        path: The KML template file.

    Returns:
        The template.
    """
    return template_from(path.read_text(encoding="utf-8"))


def fire_kml(
    fires: list[FireGeometry],
    template: Template,
) -> str:
    """Return the KML document string for *fires*.

    The document holds the template's styles and one top-level folder each for active
    and inactive fires.

    Args:
        fires: The fires to symbolize.
        template: The template supplying styles and style URLs.

    Returns:
        The KML document.
    """
    kml = simplekml.Kml()
    document = kml.document

    for style in template.styles:
        document.styles.append(style)

    status_folder(
        document,
        fires,
        peri_scribe.models.FireStatus.ACTIVE,
        template.style_urls,
    )
    status_folder(
        document,
        fires,
        peri_scribe.models.FireStatus.INACTIVE,
        template.style_urls,
    )
    return kml.kml()


def write_kmz(path: pathlib.Path, kml_text: str) -> None:
    """Write *kml_text* as a compressed KMZ file at *path*.

    Args:
        path: The KMZ file to write.
        kml_text: The KML document to compress.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        path,
        "w",
        compression=KMZ_COMPRESSION,
        compresslevel=KMZ_COMPRESSION_LEVEL,
    ) as archive:
        archive.writestr(KMZ_DOCUMENT_FILENAME, kml_text)


def create_kmz(year_directory: pathlib.Path) -> pathlib.Path:
    """Build and write the KMZ output for *year_directory*.

    The full history GeoPackage is read for geometry, the fire index supplies each
    fire's name and status, and the KML template file supplies the symbolization. The
    output is written under the year's ``maps`` directory.

    Args:
        year_directory: The year directory that holds the ``derived`` directory.

    Returns:
        The path of the written KMZ file.
    """
    index = peri_scribe.fire_index.load_fire_index(year_directory)
    history_path = peri_scribe.fire_history.history_geopackage_path(year_directory)
    perimeters = read_history_layer(
        history_path,
        peri_scribe.fire_history.PERIMETER_LAYER_NAME,
    )
    points = read_history_layer(
        history_path,
        peri_scribe.fire_history.POINT_LAYER_NAME,
    )
    template = read_template(peri_scribe.kml_template.template_path())
    output_path = kmz_path(year_directory)
    write_kmz(
        output_path,
        fire_kml(fire_geometries(index, perimeters, points), template),
    )
    return output_path
