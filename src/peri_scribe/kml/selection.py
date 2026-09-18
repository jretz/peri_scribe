"""Selecting which fires and perimeters appear in the KML."""

from __future__ import annotations

import typing

import peri_scribe.areas
import peri_scribe.geo.measurements
import peri_scribe.geo.parsing
import peri_scribe.kml.perimeters
import peri_scribe.kml.plot_rendering
import peri_scribe.models
import peri_scribe.perimeters.progression
from peri_scribe.units import units


if typing.TYPE_CHECKING:
    import geopandas
    import pint
    import shapely


# The smallest computed or reported area that keeps a fire in the KMZ output. Fires
# whose every area indication is missing or below this are the season's long tail of
# tiny incidents, which clutter Google Earth without adding information.


MINIMUM_FIRE_AREA = 25.0 * units.acres


IDENTIFIER_AREA_KEY = "id"


NAME_AREA_KEY = "name"


AreaKey = tuple[str, str]


def identifiers(entry: peri_scribe.models.FireIndexEntry) -> frozenset[str]:
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

    The fire's canonical identifier is preferred, with its name as a fallback; when that
    base prefix is already taken, a numeric suffix is appended until the result is
    unused, so every fire's plot images land in distinct files.

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


def area_groups(
    frame: geopandas.GeoDataFrame,
    aliases: typing.Mapping[str, str],
) -> dict[AreaKey, geopandas.GeoDataFrame]:
    """Keep each fire's complete evidence together across its identifier aliases.

    Args:
        frame: History rows carrying fire identity columns.
        aliases: Known identifiers mapped to the fire's canonical identifier.

    Returns:
        History slices keyed by canonical identity, with unnamed identities separate.
    """
    positions: dict[AreaKey, list[int]] = {}
    if not frame.empty:
        for position, (identifier, name) in enumerate(
            zip(frame["fire_identifier"], frame["fire_name"], strict=True),
        ):
            key = fire_area_key(identifier, name)
            if key[0] == IDENTIFIER_AREA_KEY:
                key = IDENTIFIER_AREA_KEY, aliases.get(key[1], key[1])
            positions.setdefault(key, []).append(position)
    return {key: frame.iloc[rows] for key, rows in positions.items()}


def prepare_histories(
    perimeters: geopandas.GeoDataFrame,
    points: geopandas.GeoDataFrame,
    incident_rows: geopandas.GeoDataFrame | None = None,
    *,
    aliases: typing.Mapping[str, str] | None = None,
) -> dict[AreaKey, peri_scribe.areas.PreparedHistory]:
    """Share complete fire histories across qualification and presentation.

    Args:
        perimeters: Full perimeter history with measured geometry.
        points: Incident location history with fallback measurements.
        incident_rows: The optional independent reporting history.
        aliases: Known identifiers mapped to their canonical fire identifier.

    Returns:
        One prepared history per canonical fire identity.
    """
    frames = (
        perimeters,
        points,
        perimeters.iloc[0:0] if incident_rows is None else incident_rows,
    )
    groups = tuple(area_groups(frame, aliases or {}) for frame in frames)
    return {
        key: peri_scribe.areas.prepare_history(
            *(
                group.get(key, frame.iloc[0:0])
                for group, frame in zip(groups, frames, strict=True)
            ),
        )
        for key in set().union(*groups)
    }


def fires_with_qualifying_area(
    perimeters: geopandas.GeoDataFrame,
    points: geopandas.GeoDataFrame,
    minimum_area: pint.Quantity[float],
    incident_rows: geopandas.GeoDataFrame | None = None,
    *,
    aliases: typing.Mapping[str, str] | None = None,
    histories: typing.Mapping[AreaKey, peri_scribe.areas.PreparedHistory] | None = None,
) -> frozenset[AreaKey]:
    """Include fires whose selected area reached the minimum anywhere in history.

    Fresh mapping, report takeovers, and sparse-record fallbacks follow the shared area
    policy. A later downward correction does not erase historical qualification.

    Args:
        perimeters: The perimeter history layer.
        points: The point history layer.
        minimum_area: The smallest historical estimate that qualifies a fire.
        incident_rows: The optional independent incident history.
        aliases: Known identifiers mapped to their canonical fire identifier.
        histories: Already prepared histories, or None to prepare them.

    Returns:
        The tagged identity keys of the qualifying fires.
    """
    if histories is None:
        histories = prepare_histories(
            perimeters,
            points,
            incident_rows,
            aliases=aliases,
        )
    return frozenset(
        key
        for key, history in histories.items()
        if history.historical_area is not None
        and history.historical_area >= minimum_area
    )


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
    dict[str, list[peri_scribe.kml.perimeters.Perimeter]],
    dict[str, list[peri_scribe.kml.perimeters.Perimeter]],
]:
    """Group perimeters by fire, preserving chronological order.

    Each perimeter keeps its geometry and observation time. Missing and empty shapes
    cannot supply mapped growth or drawable outlines, so they are excluded from these
    groups. Their history rows remain available for reported incident information. Fires
    are keyed by identifier when one is known, and by name otherwise.

    Args:
        perimeters: The perimeter history layer.

    Returns:
        Perimeters keyed by identifier and by name.
    """
    by_identifier: dict[str, list[peri_scribe.kml.perimeters.Perimeter]] = {}
    by_name: dict[str, list[peri_scribe.kml.perimeters.Perimeter]] = {}
    areas = perimeters.get(
        peri_scribe.geo.measurements.AREA_COLUMN,
        [None] * len(perimeters),
    )
    additions = perimeters.get(
        peri_scribe.perimeters.progression.ADDED_AREA_COLUMN,
        [None] * len(perimeters),
    )
    sequences = perimeters.get(
        peri_scribe.perimeters.progression.SEQUENCE_COLUMN,
        [None] * len(perimeters),
    )
    for (
        identifier,
        name,
        observation_time,
        geometry,
        stored_area,
        stored_added,
        sequence,
    ) in zip(
        perimeters["fire_identifier"],
        perimeters["fire_name"],
        perimeters["observation_time"],
        perimeters.geometry,
        areas,
        additions,
        sequences,
        strict=True,
    ):
        if geometry is None or geometry.is_empty:
            continue
        area = peri_scribe.geo.parsing.numeric_value(stored_area)
        added = peri_scribe.geo.parsing.numeric_value(stored_added)
        perimeter = peri_scribe.kml.perimeters.Perimeter(
            geometry=geometry,
            observation_time=peri_scribe.geo.parsing.observation_time_from(
                observation_time,
            ),
            area=None if area is None else area * units.Unit("meters ** 2"),
            added_area=None if added is None else added * units.Unit("meters ** 2"),
            sequence_digest=sequence if isinstance(sequence, str) else None,
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


def first_identifier_match[Value](
    fire_identifiers: frozenset[str],
    by_identifier: typing.Mapping[str, Value],
) -> Value | None:
    """Return the value *by_identifier* holds for the fire's first matching identifier.

    A fire may carry several identifiers, so they are scanned in sorted order: the value
    a fire resolves to is then the same on every run, rather than depending on the order
    a set happens to iterate in.

    Args:
        fire_identifiers: The fire's identifiers.
        by_identifier: Values keyed by identifier.

    Returns:
        The first matching value, or None when no identifier matches.

    Examples:
        >>> first_identifier_match(frozenset({"b", "a"}), {"a": 1, "b": 2})
        1
    """
    for identifier in sorted(fire_identifiers):
        if identifier in by_identifier:
            return by_identifier[identifier]
    return None


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
    point = first_identifier_match(fire_identifiers, point_by_identifier)
    if point is None and not fire_identifiers:
        return point_by_name.get(entry_name)
    return point


def fire_point_location(
    fire_identifiers: frozenset[str],
    entry_name: str,
    point_by_identifier: dict[str, shapely.Point],
    point_by_name: dict[str, shapely.Point],
    perimeters: tuple[peri_scribe.kml.perimeters.Perimeter, ...],
) -> shapely.Point | None:
    """Return the point location to show for one fire, or None.

    The last known point location is used when the fire has one. A fire without a known
    location falls back to a representative point of its latest perimeter, because its
    icon still needs somewhere to draw. The point source drops inactive fires while
    their perimeters remain available, so this fallback keeps their icons in the output.

    Args:
        fire_identifiers: The fire's identifiers.
        entry_name: The fire's name.
        point_by_identifier: Points keyed by identifier.
        point_by_name: Points keyed by name.
        perimeters: The fire's perimeters in chronological order.

    Returns:
        The fire's point location, or None when it has neither a known location nor any
        perimeter to derive one from.
    """
    point = fire_point(fire_identifiers, entry_name, point_by_identifier, point_by_name)
    if point is not None:
        return point
    if perimeters:
        return perimeters[-1].geometry.representative_point()
    return None
