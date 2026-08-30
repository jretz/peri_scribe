"""Selecting which fires and perimeters appear in the KML."""

from __future__ import annotations

import typing

import peri_scribe.geo.parsing
import peri_scribe.kml.fire_data
import peri_scribe.kml.plot_rendering
import peri_scribe.models


if typing.TYPE_CHECKING:
    import geopandas
    import shapely


# The smallest computed or reported area that keeps a fire in the KMZ output. Fires
# whose every area indication is missing or below this are the season's long tail of
# tiny incidents, which clutter Google Earth without adding information.


MINIMUM_FIRE_AREA_IN_ACRES = 25.0


PERIMETER_AREA_COLUMN = "area_acres"


POINT_AREA_COLUMNS = ("incident_size", "discovery_acres", "final_acres")


IDENTIFIER_AREA_KEY = "id"


NAME_AREA_KEY = "name"


AreaKey = tuple[str, str]


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
    prefix = peri_scribe.kml.plot_rendering.filename_prefix(identifier, name)
    candidate = prefix
    counter = 2
    while candidate in used_prefixes:
        candidate = f"{prefix}-{counter}"
        counter += 1
    return candidate


def fire_area_key(identifier: object, name: str) -> AreaKey:
    """Return the key that identifies one history row's fire for area qualification.

    A row with an identifier keys by it; a row without one keys by its name. The two
    kinds of keys are tagged so an identifier and a name that look alike stay apart.

    Args:
        identifier: The row's fire identifier, or a missing value.
        name: The row's fire name.

    Returns:
        The row's tagged identity key.
    """
    if peri_scribe.geo.parsing.is_missing(identifier):
        return NAME_AREA_KEY, str(name)
    return IDENTIFIER_AREA_KEY, str(identifier)


def fires_with_qualifying_area(
    perimeters: geopandas.GeoDataFrame,
    points: geopandas.GeoDataFrame,
    minimum_area_in_acres: float,
) -> frozenset[AreaKey]:
    """Return the identity keys of fires with any area indication at least the minimum.

    A fire's computed area is the perimeter history's acreage column; its reported areas
    are the size, discovery, and final acreage columns of the point history. A fire
    qualifies when any one of those values reaches the minimum, so fires whose every
    indication is missing or smaller are absent from the result.

    Args:
        perimeters: The perimeter history layer.
        points: The point history layer.
        minimum_area_in_acres: The smallest area that qualifies a fire.

    Returns:
        The tagged identity keys of the qualifying fires.
    """
    qualifying: set[AreaKey] = set()
    perimeter_area = perimeters.get(PERIMETER_AREA_COLUMN)
    if perimeter_area is not None:
        for identifier, name, value in zip(
            perimeters["fire_identifier"],
            perimeters["fire_name"],
            perimeter_area,
            strict=True,
        ):
            acres = peri_scribe.geo.parsing.numeric_value(value)
            if acres is not None and acres >= minimum_area_in_acres:
                qualifying.add(fire_area_key(identifier, name))
    for column in POINT_AREA_COLUMNS:
        if column not in points.columns:
            continue
        for identifier, name, value in zip(
            points["fire_identifier"],
            points["fire_name"],
            points[column],
            strict=True,
        ):
            acres = peri_scribe.geo.parsing.numeric_value(value)
            if acres is not None and acres >= minimum_area_in_acres:
                qualifying.add(fire_area_key(identifier, name))
    return frozenset(qualifying)


def fire_qualifies(
    fire_identifiers: frozenset[str],
    entry_name: str,
    qualifying_keys: frozenset[AreaKey],
) -> bool:
    """Return whether a fire with *fire_identifiers* and *entry_name* qualifies.

    A fire qualifies when any of its identifiers, or its name when it has no
    identifiers, appears among the qualifying keys.

    Args:
        fire_identifiers: The fire's identifiers.
        entry_name: The fire's name.
        qualifying_keys: The keys of the qualifying fires.

    Returns:
        True when the fire has a qualifying area indication.
    """
    if fire_identifiers:
        return any(
            (IDENTIFIER_AREA_KEY, identifier) in qualifying_keys
            for identifier in fire_identifiers
        )
    return (NAME_AREA_KEY, entry_name) in qualifying_keys


def perimeter_groups(
    perimeters: geopandas.GeoDataFrame,
) -> tuple[
    dict[str, list[peri_scribe.kml.fire_data.Perimeter]],
    dict[str, list[peri_scribe.kml.fire_data.Perimeter]],
]:
    """Group perimeters by fire, preserving chronological order.

    Each perimeter keeps its geometry and observation time. Fires are keyed by
    identifier when one is known, and by name otherwise.

    Args:
        perimeters: The perimeter history layer.

    Returns:
        Perimeters keyed by identifier and by name.
    """
    by_identifier: dict[str, list[peri_scribe.kml.fire_data.Perimeter]] = {}
    by_name: dict[str, list[peri_scribe.kml.fire_data.Perimeter]] = {}
    for identifier, name, observation_time, geometry in zip(
        perimeters["fire_identifier"],
        perimeters["fire_name"],
        perimeters["observation_time"],
        perimeters.geometry,
        strict=True,
    ):
        perimeter = peri_scribe.kml.fire_data.Perimeter(
            geometry=geometry,
            observation_time=peri_scribe.geo.parsing.observation_time_from(
                observation_time,
            ),
        )
        if peri_scribe.geo.parsing.is_missing(identifier):
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
        if peri_scribe.geo.parsing.is_missing(identifier):
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
    perimeters: tuple[peri_scribe.kml.fire_data.Perimeter, ...],
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
