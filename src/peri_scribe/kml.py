"""Building the KML output for a year's fires.

The output is a compressed KML document (a KMZ file). The symbolization comes from the
KML template file: its styles are copied into the output, and each fire's placemarks
reuse the style URLs the template assigns to the corresponding placemarks.
"""

from __future__ import annotations

import dataclasses
import pathlib
import typing
import zipfile

import fastkml
import geopandas

import peri_scribe.fire_history
import peri_scribe.fire_index
import peri_scribe.geo_data
import peri_scribe.kml_template
import peri_scribe.models


if typing.TYPE_CHECKING:
    import shapely


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

    styles: tuple[fastkml.Style | fastkml.StyleMap, ...]
    style_urls: dict[str, str]


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
        year_directory
        / MAPS_DIRECTORY_NAME
        / kmz_filename(year_from(year_directory))
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
    return frozenset(
        identifier for identifier in candidates if identifier is not None
    )


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
        fires.append(
            FireGeometry(
                name=entry.name,
                status=peri_scribe.models.FireStatus(entry.status),
                point=fire_point(
                    fire_identifiers,
                    entry.name,
                    point_by_identifier,
                    point_by_name,
                ),
                perimeters=fire_perimeters(
                    fire_identifiers,
                    entry.name,
                    perimeter_by_identifier,
                    perimeter_by_name,
                ),
            ),
        )
    return sorted(fires, key=lambda fire: fire.name.casefold())


def linear_ring(ring: shapely.LinearRing) -> fastkml.LinearRing:
    """Return the KML linear ring for *ring*.

    Args:
        ring: The shapely ring to convert.

    Returns:
        The KML linear ring.
    """
    return fastkml.LinearRing(
        kml_coordinates=fastkml.Coordinates(
            coords=[(float(x), float(y)) for x, y in ring.coords],
        ),
    )


def polygon_geometry(polygon: shapely.Polygon) -> fastkml.Polygon:
    """Return the KML polygon for *polygon*.

    Args:
        polygon: The shapely polygon to convert.

    Returns:
        The KML polygon, including any holes.
    """
    outer_boundary = fastkml.OuterBoundaryIs(
        kml_geometry=linear_ring(polygon.exterior),
    )
    inner_boundaries = [
        fastkml.InnerBoundaryIs(kml_geometry=linear_ring(interior))
        for interior in polygon.interiors
    ]
    return fastkml.Polygon(
        outer_boundary=outer_boundary,
        inner_boundaries=inner_boundaries,
    )


def multi_polygon_geometry(
    multi_polygon: shapely.MultiPolygon,
) -> fastkml.MultiGeometry:
    """Return the KML multi-geometry for *multi_polygon*.

    Args:
        multi_polygon: The shapely multi-polygon to convert.

    Returns:
        The KML multi-geometry holding each polygon.
    """
    return fastkml.MultiGeometry(
        kml_geometries=[
            polygon_geometry(typing.cast("shapely.Polygon", polygon))
            for polygon in multi_polygon.geoms
        ],
    )


def perimeter_geometry(
    geometry: shapely.Geometry,
) -> fastkml.Polygon | fastkml.MultiGeometry:
    """Return the KML geometry for *geometry*.

    Args:
        geometry: A shapely polygon or multi-polygon.

    Returns:
        The KML polygon or multi-geometry.
    """
    if geometry.geom_type == "Polygon":
        return polygon_geometry(typing.cast("shapely.Polygon", geometry))
    return multi_polygon_geometry(
        typing.cast("shapely.MultiPolygon", geometry),
    )


def point_placemark(
    name: str,
    style_url: str,
    point: shapely.Point,
) -> fastkml.Placemark:
    """Return the point placemark for *point* named *name*.

    Args:
        name: The name to show for the point.
        style_url: The style URL to apply.
        point: The point geometry.

    Returns:
        The placemark.
    """
    return fastkml.Placemark(
        name=name,
        style_url=fastkml.StyleUrl(url=style_url),
        kml_geometry=fastkml.Point(
            kml_coordinates=fastkml.Coordinates(coords=[(point.x, point.y)]),
        ),
    )


def perimeter_placemark(
    name: str,
    style_url: str,
    geometry: shapely.Geometry,
) -> fastkml.Placemark:
    """Return the perimeter placemark for *geometry*.

    Args:
        name: The placemark name.
        style_url: The style URL to apply.
        geometry: The perimeter geometry.

    Returns:
        The placemark.
    """
    return fastkml.Placemark(
        name=name,
        style_url=fastkml.StyleUrl(url=style_url),
        kml_geometry=perimeter_geometry(geometry),
    )


def fire_folder(
    fire: FireGeometry,
    style_urls: typing.Mapping[str, str],
) -> fastkml.Folder:
    """Return the folder symbolizing *fire*.

    The folder holds the fire's point location and its latest, penultimate, and
    antepenultimate perimeters, each shown when the fire's history has one.

    Args:
        fire: The fire to symbolize.
        style_urls: The style URL for each template placemark name.

    Returns:
        The fire's folder.
    """
    folder = fastkml.Folder(name=fire.name)
    if fire.point is not None:
        folder.append(
            point_placemark(
                fire.name,
                style_urls[peri_scribe.kml_template.POINT_LOCATION_NAME],
                fire.point,
            ),
        )
    if fire.perimeters:
        folder.append(
            perimeter_placemark(
                peri_scribe.kml_template.FILLED_PERIMETER_TEMPLATE.name,
                style_urls[
                    peri_scribe.kml_template.FILLED_PERIMETER_TEMPLATE.name
                ],
                fire.perimeters[-1],
            ),
        )
    for index, template in enumerate(
        peri_scribe.kml_template.OUTLINED_PERIMETER_TEMPLATES,
    ):
        if len(fire.perimeters) <= index:
            break
        folder.append(
            perimeter_placemark(
                template.name,
                style_urls[template.name],
                fire.perimeters[-(index + 1)],
            ),
        )
    return folder


def latest_perimeters_folder(
    fires: list[FireGeometry],
    style_urls: typing.Mapping[str, str],
) -> fastkml.Folder:
    """Return the folder holding each fire's symbolized geometry.

    Args:
        fires: The fires to place in the folder.
        style_urls: The style URL for each template placemark name.

    Returns:
        The folder.
    """
    folder = fastkml.Folder(
        name=peri_scribe.kml_template.LATEST_PERIMETERS_FOLDER_NAME,
    )
    for fire in fires:
        folder.append(fire_folder(fire, style_urls))
    return folder


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
    fires: list[FireGeometry],
    status: peri_scribe.models.FireStatus,
    style_urls: typing.Mapping[str, str],
) -> fastkml.Folder:
    """Return the top-level folder for fires of *status*.

    Args:
        fires: Every fire.
        status: The status whose fires belong in the folder.
        style_urls: The style URL for each template placemark name.

    Returns:
        The folder holding the matching fires' geometry.
    """
    folder = fastkml.Folder(name=status_folder_name(status))
    folder.append(
        latest_perimeters_folder(
            [fire for fire in fires if fire.status is status],
            style_urls,
        ),
    )
    return folder


def placemark_style_urls(document: fastkml.Document) -> dict[str, str]:
    """Return each template placemark's style URL, keyed by name.

    Args:
        document: The parsed template document.

    Returns:
        The style URL for each placemark name.
    """
    urls: dict[str, str] = {}
    collect_placemark_style_urls(document.features, urls)
    return urls


def collect_placemark_style_urls(
    features: typing.Iterable[object],
    urls: dict[str, str],
) -> None:
    """Record each placemark's style URL into *urls*.

    Args:
        features: The features to search, descending into folders.
        urls: The mapping being built.
    """
    for feature in features:
        if isinstance(feature, fastkml.Folder):
            collect_placemark_style_urls(feature.features, urls)
        elif isinstance(feature, fastkml.Placemark):
            if feature.name is None:
                continue
            style_url = feature.style_url
            if style_url is not None and style_url.url is not None:
                urls[feature.name] = style_url.url


def template_from(kml_text: str) -> Template:
    """Parse *kml_text* into the template's styles and style URLs.

    Args:
        kml_text: The KML template document.

    Returns:
        The template.
    """
    kml = fastkml.KML.from_string(kml_text)
    document = typing.cast("fastkml.Document", kml.features[0])
    return Template(
        styles=tuple(document.styles),
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
    kml = fastkml.KML()
    document = fastkml.Document()
    kml.append(document)

    for style in template.styles:
        document.styles.append(style)

    document.append(
        status_folder(
            fires,
            peri_scribe.models.FireStatus.ACTIVE,
            template.style_urls,
        ),
    )
    document.append(
        status_folder(
            fires,
            peri_scribe.models.FireStatus.INACTIVE,
            template.style_urls,
        ),
    )
    return kml.to_string()


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
