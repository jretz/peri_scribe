"""Building the KML output for a year's fires.

The output is a compressed KML document (a KMZ file). The symbolization comes from the
KML template file: its styles are copied into the output, and each fire's placemarks
reuse the style URLs the template assigns to the corresponding placemarks.
"""

from __future__ import annotations

import dataclasses
import datetime
import json
import pathlib
import typing
import zipfile

import simplekml

import peri_scribe.fire_differential
import peri_scribe.fire_history
import peri_scribe.fire_index
import peri_scribe.geo_package
import peri_scribe.kml_descriptions
import peri_scribe.kml_plots
import peri_scribe.kml_template
import peri_scribe.kml_template_reader
import peri_scribe.models
import peri_scribe.perimeter_progression
import peri_scribe.units


if typing.TYPE_CHECKING:
    import geopandas
    import pandas as pd
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
    """One fire's point, perimeters, growth rings, and plots, ready to symbolize."""

    name: str
    status: peri_scribe.models.FireStatus
    point: shapely.Point | None
    perimeters: tuple[Perimeter, ...]
    progression_rings: tuple[peri_scribe.perimeter_progression.Ring, ...] = ()
    description: str | None = None
    images: tuple[peri_scribe.kml_plots.PlotImage, ...] = ()


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


def unique_filename_prefix(
    identifier: str | None,
    name: str,
    used_prefixes: frozenset[str],
) -> str:
    """Return a filename prefix for a fire that avoids *used_prefixes*.

    The fire's canonical identifier is preferred, with its name as a fallback; when
    that base prefix is already taken, a numeric suffix is appended until the result
    is unused, so every fire's plot images land in distinct files.

    Args:
        identifier: The fire's canonical identifier, or None.
        name: The fire's name.
        used_prefixes: Every prefix already assigned in the output.

    Returns:
        A prefix not present in *used_prefixes*.
    """
    prefix = peri_scribe.kml_plots.filename_prefix(identifier, name)
    candidate = prefix
    counter = 2
    while candidate in used_prefixes:
        candidate = f"{prefix}-{counter}"
        counter += 1
    return candidate


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


def latest_matching_row(
    frame: geopandas.GeoDataFrame,
    fire_identifiers: frozenset[str],
    entry_name: str,
) -> pd.Series | None:
    """Return the chronologically latest row of *frame* for one fire, or None.

    A fire with identifiers is matched by those identifiers; a fire without any is
    matched by name. The layer's rows are already in chronological order, so the
    last matching row is the latest.

    Args:
        frame: The history layer to search.
        fire_identifiers: The fire's identifiers.
        entry_name: The fire's name, used when it has no identifiers.

    Returns:
        The latest matching row, or None when the fire has none.
    """
    if fire_identifiers:
        matched = frame[frame["fire_identifier"].isin(sorted(fire_identifiers))]
    else:
        matched = frame[frame["fire_name"] == entry_name]
    if matched.empty:
        return None
    return matched.iloc[-1]


def column_value(row: pd.Series | None, column: str) -> object:
    """Return *row*'s value in *column*, or None when it is missing.

    Args:
        row: A history row, or None.
        column: The column to read.

    Returns:
        The column's value, or None when the row or value is missing.
    """
    if row is None or column not in row.index:
        return None
    value = row[column]
    if peri_scribe.geo_package.is_missing(value):
        return None
    return value


def text_value(row: pd.Series | None, column: str) -> str | None:
    """Return *row*'s text value in *column*, or None when it is blank.

    Args:
        row: A history row, or None.
        column: The column to read.

    Returns:
        The column's text, or None when it is missing or whitespace only.
    """
    value = column_value(row, column)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def float_value(row: pd.Series | None, column: str) -> float | None:
    """Return *row*'s numeric value in *column*, or None when it is missing.

    Args:
        row: A history row, or None.
        column: The column to read.

    Returns:
        The column's numeric value, or None when it cannot be read as a number.
    """
    value = column_value(row, column)
    if value is None:
        return None
    return peri_scribe.geo_package.numeric_value(value)


def as_datetime(value: object) -> datetime.datetime | None:
    """Return *value* as an aware datetime, or None when it is not one.

    Args:
        value: Any timestamp value.

    Returns:
        The value as an aware UTC datetime, or None when it cannot be parsed.
    """
    return peri_scribe.geo_package.observation_time_from(value)


def datetime_value(row: pd.Series | None, column: str) -> datetime.datetime | None:
    """Return *row*'s datetime value in *column*, or None when it is missing.

    Args:
        row: A history row, or None.
        column: The column to read.

    Returns:
        The column's value as an aware datetime, or None.
    """
    return as_datetime(column_value(row, column))


def source_attribute_value(row: pd.Series | None, key: str) -> object:
    """Return *key* from *row*'s preserved source attributes, or None.

    The history layers keep each row's original source attributes as a JSON string,
    which is where fields that have no derived column (such as the protecting unit)
    still live.

    Args:
        row: A history row, or None.
        key: The source attribute to read.

    Returns:
        The attribute's value, or None when it is absent.
    """
    raw = column_value(row, "source_attributes")
    if raw is None:
        return None
    if isinstance(raw, str):
        try:
            attributes = json.loads(raw)
        except json.JSONDecodeError:
            return None
    else:
        attributes = raw
    if not isinstance(attributes, dict):
        return None
    return attributes.get(key)


def source_text_value(row: pd.Series | None, key: str) -> str | None:
    """Return *key* from *row*'s source attributes as text, or None when blank.

    Args:
        row: A history row, or None.
        key: The source attribute to read.

    Returns:
        The attribute's text, or None when it is missing or whitespace only.
    """
    value = source_attribute_value(row, key)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def first_source_text(
    perimeter_row: pd.Series | None,
    point_row: pd.Series | None,
    point_key: str | None,
    perimeter_key: str | None,
) -> str | None:
    """Return the first present attribute value among *point_key* and *perimeter_key*.

    The point feed's value wins when both feeds carry the same attribute; the
    perimeter feed's ``attr_``-prefixed value is the fallback.

    Args:
        perimeter_row: A perimeter history row, or None.
        point_row: A point history row, or None.
        point_key: The attribute key in the point row's source attributes, or
            None.
        perimeter_key: The attribute key in the perimeter row's source
            attributes, or None.

    Returns:
        The first present value, or None when both are missing.
    """
    if point_key is not None:
        value = source_text_value(point_row, point_key)
        if value is not None:
            return value
    if perimeter_key is not None:
        return source_text_value(perimeter_row, perimeter_key)
    return None


def numbered_source_text(
    perimeter_row: pd.Series | None,
    point_row: pd.Series | None,
    slot_keys: dict[int, tuple[str, str]],
) -> str | None:
    """Return the distinct present attribute values, ordered by slot number.

    Each numbered slot pairs the point feed's attribute with the perimeter feed's
    ``attr_``-prefixed counterpart. Values are kept in slot order, and a value
    that already appeared in an earlier slot is not repeated.

    Args:
        perimeter_row: A perimeter history row, or None.
        point_row: A point history row, or None.
        slot_keys: The point and perimeter attribute keys for each slot number.

    Returns:
        The distinct values joined with ``; ``, or None when all slots are
        missing.
    """
    values: list[str] = []
    for number in sorted(slot_keys):
        point_key, perimeter_key = slot_keys[number]
        for row, key in ((point_row, point_key), (perimeter_row, perimeter_key)):
            value = source_text_value(row, key)
            if value is not None and value not in values:
                values.append(value)
    return "; ".join(values) if values else None


# Fire behavior reports one free-text label per slot, from the general description
# through the numbered specific slots. The point feed stores the plain key name
# and the perimeter feed prefixes the same attribute with ``attr_``.
FIRE_BEHAVIOR_ATTRIBUTE_KEYS: dict[int, tuple[str, str]] = {
    0: ("FireBehaviorGeneral", "attr_FireBehaviorGeneral"),
    1: ("FireBehaviorGeneral1", "attr_FireBehaviorGeneral1"),
    2: ("FireBehaviorGeneral2", "attr_FireBehaviorGeneral2"),
    3: ("FireBehaviorGeneral3", "attr_FireBehaviorGeneral3"),
}


# The incident complexity entry combines the reported complexity level, the fire
# management complexity, and the organizational assessment, in that order.
INCIDENT_COMPLEXITY_ATTRIBUTE_KEYS: dict[int, tuple[str, str]] = {
    1: ("IncidentComplexityLevel", "attr_IncidentComplexityLevel"),
    2: ("FireMgmtComplexity", "attr_FireMgmtComplexity"),
    3: ("OrganizationalAssessment", "attr_OrganizationalAssessment"),
}


# The fuel model entry combines the primary, secondary, predominant fuel model,
# and predominant fuel group values, in that order.
FUEL_MODEL_ATTRIBUTE_KEYS: dict[int, tuple[str, str]] = {
    1: ("PrimaryFuelModel", "attr_PrimaryFuelModel"),
    2: ("SecondaryFuelModel", "attr_SecondaryFuelModel"),
    3: ("PredominantFuelModel", "attr_PredominantFuelModel"),
    4: ("PredominantFuelGroup", "attr_PredominantFuelGroup"),
}


def source_label(source: object) -> str | None:
    """Return the human-readable name of a perimeter source kind.

    Args:
        source: The ``source`` column value of a perimeter row.

    Returns:
        The source's display name, or None when *source* is missing or unknown.
    """
    if peri_scribe.geo_package.is_missing(source):
        return None
    return {
        "firis_perimeter": "FIRIS / NIFC",
        "wfigs_perimeter": "WFIGS",
    }.get(str(source))


def fire_description(
    entry: peri_scribe.models.FireIndexEntry,
    perimeters: geopandas.GeoDataFrame,
    points: geopandas.GeoDataFrame,
) -> peri_scribe.kml_descriptions.FireDescription:
    """Return *entry*'s latest state for its balloon description.

    The latest perimeter supplies the fire's area, containment, cost, and timing;
    where a perimeter has no value for a fact the latest point location is used
    instead. The protecting unit, initial response time, incident type,
    complexity, fuels, fire behavior, and landowner category come only from the
    sources' original attributes, which the history preserves verbatim.

    Args:
        entry: One fire index entry.
        perimeters: The perimeter history layer.
        points: The point history layer.

    Returns:
        The fire's latest state.
    """
    fire_identifiers = identifiers(entry)
    perimeter_row = latest_matching_row(perimeters, fire_identifiers, entry.name)
    point_row = latest_matching_row(points, fire_identifiers, entry.name)

    exterior_perimeter_in_miles = None
    if perimeter_row is not None:
        exterior_perimeter_in_miles = peri_scribe.units.exterior_perimeter_in_miles(
            perimeter_row.geometry,
        )

    area_in_acres = float_value(perimeter_row, "area_acres")
    if area_in_acres is None:
        area_in_acres = float_value(point_row, "incident_size")

    percent_contained = float_value(perimeter_row, "percent_contained")
    if percent_contained is None:
        percent_contained = float_value(point_row, "percent_contained")

    estimated_cost_to_date = float_value(perimeter_row, "estimated_cost_to_date")
    if estimated_cost_to_date is None:
        estimated_cost_to_date = float_value(point_row, "estimated_cost_to_date")

    estimated_final_cost = float_value(perimeter_row, "estimated_final_cost")
    if estimated_final_cost is None:
        estimated_final_cost = float_value(point_row, "estimated_final_cost")

    discovery_time = datetime_value(perimeter_row, "discovery_time")
    if discovery_time is None:
        discovery_time = datetime_value(point_row, "discovery_time")

    observation_time = datetime_value(perimeter_row, "observation_time")
    if observation_time is None:
        observation_time = datetime_value(point_row, "observation_time")

    initial_response_time = as_datetime(
        source_attribute_value(perimeter_row, "attr_InitialResponseDateTime"),
    )
    if initial_response_time is None:
        initial_response_time = as_datetime(
            source_attribute_value(point_row, "InitialResponseDateTime"),
        )

    protecting_unit = source_text_value(point_row, "POOJurisdictionalUnit")
    if protecting_unit is None:
        protecting_unit = source_text_value(point_row, "POOProtectingUnit")
    if protecting_unit is None:
        protecting_unit = source_text_value(point_row, "POOJurisdictionalAgency")

    return peri_scribe.kml_descriptions.FireDescription(
        name=entry.name,
        status=peri_scribe.models.FireStatus(entry.status),
        identifier=entry.identifier,
        source=source_label(column_value(perimeter_row, "source")),
        mission=text_value(perimeter_row, "mission"),
        area_in_acres=area_in_acres,
        exterior_perimeter_in_miles=exterior_perimeter_in_miles,
        percent_contained=percent_contained,
        estimated_cost_to_date_in_dollars=estimated_cost_to_date,
        estimated_final_cost_in_dollars=estimated_final_cost,
        protecting_unit=protecting_unit,
        discovery_time=discovery_time,
        observation_time=observation_time,
        initial_response_time=initial_response_time,
        incident_type=first_source_text(
            perimeter_row,
            point_row,
            "IncidentTypeCategory",
            None,
        ),
        incident_complexity=numbered_source_text(
            perimeter_row,
            point_row,
            INCIDENT_COMPLEXITY_ATTRIBUTE_KEYS,
        ),
        fuel_model=numbered_source_text(
            perimeter_row,
            point_row,
            FUEL_MODEL_ATTRIBUTE_KEYS,
        ),
        fire_behavior=numbered_source_text(
            perimeter_row,
            point_row,
            FIRE_BEHAVIOR_ATTRIBUTE_KEYS,
        ),
        landowner_category=first_source_text(
            perimeter_row,
            point_row,
            None,
            "attr_POOLandownerCategory",
        ),
    )


def fire_geometries(
    index: peri_scribe.models.FireIndex,
    perimeters: geopandas.GeoDataFrame,
    points: geopandas.GeoDataFrame,
    differential_perimeters: geopandas.GeoDataFrame,
) -> list[FireGeometry]:
    """Return each indexed fire's geometry and plots, sorted by case-folded name.

    Each fire's point is its last known location, or a representative point of its
    latest perimeter when no location is known. The full perimeters feed the latest
    perimeters folder, the differential growth rings feed the progression maps, and
    the point and perimeter histories feed the line plots embedded in each fire's
    balloon.

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
    used_prefixes: set[str] = set()
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
        prefix = unique_filename_prefix(
            entry.identifier,
            entry.name,
            frozenset(used_prefixes),
        )
        used_prefixes.add(prefix)
        images = peri_scribe.kml_plots.plot_images(
            peri_scribe.kml_plots.fire_plots(
                fire_identifiers,
                entry.name,
                perimeters,
                points,
            ),
            prefix,
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
                description=peri_scribe.kml_descriptions.description_html(
                    fire_description(entry, perimeters, points),
                    tuple(image.filename for image in images),
                ),
                images=images,
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
) -> None:
    """Add the polygon placemark for *polygon* to *container*.

    Args:
        container: The folder that holds the placemark.
        name: The placemark name.
        style_url: The style URL to apply.
        polygon: The shapely polygon to convert.
        draw_order: The order in which the polygon draws.
        description: The balloon description, or None for none.
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


def multi_polygon_geometry(
    container: simplekml.Container,
    name: str,
    style_url: str,
    multi_polygon: shapely.MultiPolygon,
    draw_order: int,
    *,
    description: str | None,
) -> None:
    """Add the multi-geometry placemark for *multi_polygon* to *container*.

    Args:
        container: The folder that holds the placemark.
        name: The placemark name.
        style_url: The style URL to apply.
        multi_polygon: The shapely multi-polygon to convert.
        draw_order: The order in which the multi-geometry draws.
        description: The balloon description, or None for none.
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


def perimeter_geometry(
    container: simplekml.Container,
    name: str,
    style_url: str,
    geometry: shapely.Geometry,
    draw_order: int,
    *,
    description: str | None,
) -> None:
    """Add the placemark for *geometry* to *container*.

    Args:
        container: The folder that holds the placemark.
        name: The placemark name.
        style_url: The style URL to apply.
        geometry: A shapely polygon or multi-polygon.
        draw_order: The order in which the geometry draws.
        description: The balloon description, or None for none.
    """
    if geometry.geom_type == "Polygon":
        polygon_geometry(
            container,
            name,
            style_url,
            typing.cast("shapely.Polygon", geometry),
            draw_order,
            description=description,
        )
    else:
        multi_polygon_geometry(
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
) -> None:
    """Add the perimeter placemark for *geometry* to *container*.

    Args:
        container: The folder that holds the placemark.
        name: The placemark name.
        style_url: The style URL to apply.
        geometry: The perimeter geometry.
        draw_order: The order in which the perimeter draws.
        description: The balloon description, or None for none.
    """
    perimeter_geometry(
        container,
        name,
        style_url,
        geometry,
        draw_order,
        description=description,
    )


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
            description=fire.description,
        )
    if fire.perimeters:
        latest_perimeter = fire.perimeters[-1]
        perimeter_placemark(
            folder,
            interior_placemark_name(latest_perimeter.observation_time),
            style_urls[peri_scribe.kml_template.FILLED_PERIMETER_TEMPLATE.name],
            latest_perimeter.geometry,
            peri_scribe.kml_template.LATEST_AREA_DRAW_ORDER,
            description=fire.description,
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
            description=fire.description,
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
                description=fire.description,
            )
        for index, band in enumerate(bands):
            perimeter_placemark(
                fire_folder,
                band.label,
                style_urls[band.name],
                band.geometry,
                peri_scribe.kml_template.band_draw_order(band_count, index),
                description=fire.description,
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


def write_kmz(
    path: pathlib.Path,
    kml_text: str,
    images: typing.Mapping[str, bytes] | None = None,
) -> None:
    """Write *kml_text* and *images* as a compressed KMZ file at *path*.

    Args:
        path: The KMZ file to write.
        kml_text: The KML document to compress.
        images: Each plot image's filename and PNG bytes, or None for none.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        path,
        "w",
        compression=KMZ_COMPRESSION,
        compresslevel=KMZ_COMPRESSION_LEVEL,
    ) as archive:
        archive.writestr(KMZ_DOCUMENT_FILENAME, kml_text)
        if images:
            for filename, content in images.items():
                archive.writestr(filename, content)


def create_kmz(year_directory: pathlib.Path) -> pathlib.Path:
    """Build and write the KMZ output for *year_directory*.

    The full history GeoPackage is read for geometry, the differential history
    supplies each fire's growth rings, the fire index supplies each fire's name and
    status, and the KML template file supplies the symbolization. Each fire's plot
    images are written into the archive beside the KML document. The output is
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
    geometries = fire_geometries(
        index,
        perimeters,
        points,
        differential_perimeters,
    )
    images = {
        image.filename: image.content for fire in geometries for image in fire.images
    }
    output_path = kmz_path(year_directory)
    write_kmz(output_path, fire_kml(geometries, template), images)
    return output_path
