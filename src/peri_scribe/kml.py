"""Building the KML output for a year's fires.

The output is a compressed KML document (a KMZ file). The symbolization comes from the
KML template file: its styles are copied into the output, and each fire's placemarks
reuse the style URLs the template assigns to the corresponding placemarks.
"""

from __future__ import annotations

import dataclasses
import datetime
import pathlib
import typing
import zipfile

import simplekml

import peri_scribe.fire_differential
import peri_scribe.fire_history
import peri_scribe.fire_index
import peri_scribe.geo_package
import peri_scribe.kml_template
import peri_scribe.kml_template_reader
import peri_scribe.models
import peri_scribe.perimeter_progression


if typing.TYPE_CHECKING:
    import geopandas
    import shapely


MAPS_DIRECTORY_NAME = "maps"

ACTIVE_FIRES_FOLDER_NAME = "Active Fires"
INACTIVE_FIRES_FOLDER_NAME = "Inactive Fires"

KMZ_DOCUMENT_FILENAME = "doc.kml"

MAPPING_NAME = "Perimeter"
UNKNOWN_MAPPING_NAME = "Unknown Mapping"

# DEFLATE is the compression Google Earth expects inside a KMZ, and level 9 is the
# highest compression level it offers.
KMZ_COMPRESSION = zipfile.ZIP_DEFLATED
KMZ_COMPRESSION_LEVEL = 9


@dataclasses.dataclass(frozen=True, kw_only=True)
class Perimeter:
    """One perimeter geometry and the time it was observed."""

    geometry: shapely.Geometry
    observation_time: datetime.datetime | None


@dataclasses.dataclass(frozen=True, kw_only=True)
class FireGeometry:
    """One fire's point, perimeters, and growth rings, ready to symbolize."""

    name: str
    status: peri_scribe.models.FireStatus
    point: shapely.Point | None
    perimeters: tuple[Perimeter, ...]
    progression_rings: tuple[peri_scribe.perimeter_progression.Ring, ...] = ()


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
    dict[str, list[Perimeter]],
    dict[str, list[Perimeter]],
]:
    """Group perimeters by fire, preserving chronological order.

    Each perimeter keeps its geometry and observation time. Fires are keyed by
    identifier when one is known, and by name otherwise.

    Args:
        perimeters: The perimeter history layer.

    Returns:
        Perimeters keyed by identifier and by name.
    """
    by_identifier: dict[str, list[Perimeter]] = {}
    by_name: dict[str, list[Perimeter]] = {}
    for identifier, name, observation_time, geometry in zip(
        perimeters["fire_identifier"],
        perimeters["fire_name"],
        perimeters["observation_time"],
        perimeters.geometry,
        strict=True,
    ):
        perimeter = Perimeter(
            geometry=geometry,
            observation_time=peri_scribe.geo_package.observation_time_from(
                observation_time,
            ),
        )
        if peri_scribe.geo_package.is_missing(identifier):
            by_name.setdefault(str(name), []).append(perimeter)
        else:
            by_identifier.setdefault(str(identifier), []).append(perimeter)
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
        if peri_scribe.geo_package.is_missing(identifier):
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
    perimeters: tuple[Perimeter, ...],
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
        return perimeters[-1].geometry.representative_point()
    return None


def fire_perimeters(
    fire_identifiers: frozenset[str],
    entry_name: str,
    perimeter_by_identifier: dict[str, list[Perimeter]],
    perimeter_by_name: dict[str, list[Perimeter]],
) -> tuple[Perimeter, ...]:
    """Return one fire's perimeters in chronological order.

    Args:
        fire_identifiers: The fire's identifiers.
        entry_name: The fire's name.
        perimeter_by_identifier: Perimeters keyed by identifier.
        perimeter_by_name: Perimeters keyed by name.

    Returns:
        The fire's perimeters, oldest first.
    """
    perimeters: list[Perimeter] = []
    for identifier in sorted(fire_identifiers):
        perimeters.extend(perimeter_by_identifier.get(identifier, []))
    if not fire_identifiers:
        perimeters.extend(perimeter_by_name.get(entry_name, []))
    return tuple(perimeters)


def fire_geometries(
    index: peri_scribe.models.FireIndex,
    perimeters: geopandas.GeoDataFrame,
    points: geopandas.GeoDataFrame,
    differential_perimeters: geopandas.GeoDataFrame,
) -> list[FireGeometry]:
    """Return each indexed fire's geometry, sorted by case-folded name.

    Each fire's point is its last known location, or a representative point of its
    latest perimeter when no location is known. The full perimeters feed the latest
    perimeters folder, and the differential growth rings feed the progression maps.

    Args:
        index: The fire index that names each fire and its status.
        perimeters: The perimeter history layer.
        points: The point history layer.
        differential_perimeters: The differential perimeter history layer.

    Returns:
        One entry per indexed fire, sorted by case-folded name.
    """
    perimeter_by_identifier, perimeter_by_name = perimeter_groups(perimeters)
    ring_by_identifier, ring_by_name = perimeter_groups(differential_perimeters)
    point_by_identifier, point_by_name = point_locations(points)
    fires: list[FireGeometry] = []
    for entry in index.fires:
        fire_identifiers = identifiers(entry)
        perimeter_observations = fire_perimeters(
            fire_identifiers,
            entry.name,
            perimeter_by_identifier,
            perimeter_by_name,
        )
        ring_observations = fire_perimeters(
            fire_identifiers,
            entry.name,
            ring_by_identifier,
            ring_by_name,
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
                    perimeter_observations,
                ),
                perimeters=perimeter_observations,
                progression_rings=tuple(
                    peri_scribe.perimeter_progression.Ring(
                        geometry=ring.geometry,
                        observation_time=ring.observation_time,
                    )
                    for ring in ring_observations
                ),
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


def time_label(observation_time: datetime.datetime | None) -> str | None:
    """Return the California-time label for *observation_time*, or None.

    The label reads like ``08/05 13:30``: month/day, then a 24-hour clock
    time with leading zeros and no am/pm marker.

    Args:
        observation_time: The observation time as an aware UTC datetime, or None.

    Returns:
        The label, or None when *observation_time* is None.
    """
    if observation_time is None:
        return None
    pacific_time = observation_time.astimezone(
        peri_scribe.perimeter_progression.CALIFORNIA_TIME_ZONE,
    )
    return f"{pacific_time:%m/%d %H:%M}"


def interior_placemark_name(observation_time: datetime.datetime | None) -> str:
    """Return the filled-interior placemark name for *observation_time*.

    Args:
        observation_time: The observation time of the latest perimeter, or None.

    Returns:
        The placemark name, ``<date> Interior`` when the time is known and
        ``Interior`` otherwise.
    """
    label = time_label(observation_time)
    if label is None:
        return peri_scribe.kml_template.FILLED_PERIMETER_TEMPLATE.name
    return f"{label} {peri_scribe.kml_template.FILLED_PERIMETER_TEMPLATE.name}"


def mapping_placemark_name(observation_time: datetime.datetime | None) -> str:
    """Return the outline placemark name for *observation_time*.

    Args:
        observation_time: The observation time of the perimeter, or None.

    Returns:
        The placemark name, ``<date> Perimeter`` when the time is known and
        ``Unknown Mapping`` otherwise.
    """
    label = time_label(observation_time)
    if label is None:
        return UNKNOWN_MAPPING_NAME
    return f"{label} {MAPPING_NAME}"


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
        latest_perimeter = fire.perimeters[-1]
        perimeter_placemark(
            folder,
            interior_placemark_name(latest_perimeter.observation_time),
            style_urls[peri_scribe.kml_template.FILLED_PERIMETER_TEMPLATE.name],
            latest_perimeter.geometry,
            peri_scribe.kml_template.LATEST_AREA_DRAW_ORDER,
        )
    for index, template in enumerate(
        peri_scribe.kml_template.OUTLINED_PERIMETER_TEMPLATES,
    ):
        if len(fire.perimeters) <= index:
            break
        perimeter = fire.perimeters[-(index + 1)]
        perimeter_placemark(
            folder,
            mapping_placemark_name(perimeter.observation_time),
            style_urls[template.name],
            perimeter.geometry,
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


def progression_folder(
    container: simplekml.Container,
    fires: list[FireGeometry],
    style_urls: typing.Mapping[str, str],
) -> None:
    """Add the folder holding each fire's progression map to *container*.

    Each fire with growth rings gets a folder holding its point location and one
    growth band per day range it covers; fires with no rings are left out, because
    there is nothing to map. Draw orders put the oldest band on the bottom, stack
    the bands from oldest to newest, and draw the point location last so its icon
    is never covered.

    Args:
        container: The folder that holds the progression maps folder.
        fires: The fires to place in the folder.
        style_urls: The style URL for each template placemark name.
    """
    folder = container.newfolder(
        name=peri_scribe.perimeter_progression.PROGRESSION_MAPS_FOLDER_NAME,
    )
    for fire in fires:
        bands = peri_scribe.perimeter_progression.progression_bands(
            fire.progression_rings,
        )
        if not bands:
            continue
        fire_folder = folder.newfolder(name=fire.name)
        band_count = len(bands)
        if fire.point is not None:
            point_placemark(
                fire_folder,
                fire.name,
                style_urls[peri_scribe.kml_template.POINT_LOCATION_NAME],
                fire.point,
                band_count,
            )
        for index, band in enumerate(bands):
            perimeter_placemark(
                fire_folder,
                band.label,
                style_urls[band.name],
                band.geometry,
                peri_scribe.kml_template.band_draw_order(band_count, index),
            )


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
    status_fires = [fire for fire in fires if fire.status is status]
    latest_perimeters_folder(folder, status_fires, style_urls)
    progression_folder(folder, status_fires, style_urls)


def fire_kml(
    fires: list[FireGeometry],
    template: peri_scribe.kml_template_reader.Template,
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

    The full history GeoPackage is read for geometry, the differential history
    supplies each fire's growth rings, the fire index supplies each fire's name and
    status, and the KML template file supplies the symbolization. The output is
    written under the year's ``maps`` directory.

    Args:
        year_directory: The year directory that holds the ``derived`` directory.

    Returns:
        The path of the written KMZ file.
    """
    index = peri_scribe.fire_index.load_fire_index(year_directory)
    history_path = peri_scribe.fire_history.history_geopackage_path(year_directory)
    perimeters = peri_scribe.geo_package.read_layer(
        history_path,
        peri_scribe.fire_history.PERIMETER_LAYER_NAME,
    )
    points = peri_scribe.geo_package.read_layer(
        history_path,
        peri_scribe.fire_history.POINT_LAYER_NAME,
    )
    differential_path = peri_scribe.fire_differential.differential_geopackage_path(
        year_directory,
    )
    differential_perimeters = peri_scribe.geo_package.read_layer(
        differential_path,
        peri_scribe.fire_history.PERIMETER_LAYER_NAME,
    )
    template = peri_scribe.kml_template_reader.read_template(
        peri_scribe.kml_template.template_path(),
    )
    output_path = kmz_path(year_directory)
    write_kmz(
        output_path,
        fire_kml(
            fire_geometries(
                index,
                perimeters,
                points,
                differential_perimeters,
            ),
            template,
        ),
    )
    return output_path
