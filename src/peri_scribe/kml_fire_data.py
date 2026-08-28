"""Turning a year's history layers into the geometry each fire symbolizes.

These helpers group perimeters and point locations by fire, derive each fire's
latest state for its balloon description, and assemble one FireGeometry per
indexed fire together with its rendered plot images.
"""

from __future__ import annotations

import dataclasses
import datetime
import typing

import peri_scribe.geo_package
import peri_scribe.kml_descriptions
import peri_scribe.kml_plot_data
import peri_scribe.kml_plot_rendering
import peri_scribe.kml_row_values
import peri_scribe.models
import peri_scribe.perimeter_progression
import peri_scribe.units


if typing.TYPE_CHECKING:
    import geopandas
    import shapely


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
    images: tuple[peri_scribe.kml_plot_rendering.PlotImage, ...] = ()


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
    prefix = peri_scribe.kml_plot_rendering.filename_prefix(identifier, name)
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


def fire_description(
    entry: peri_scribe.models.FireIndexEntry,
    perimeters: geopandas.GeoDataFrame,
    points: geopandas.GeoDataFrame,
) -> peri_scribe.kml_descriptions.FireDescription:
    """Return *entry*'s latest state for its balloon description.

    The latest perimeter supplies the fire's area, containment, cost, and timing; where
    a perimeter has no value for a fact the latest point location is used instead. The
    protecting unit, initial response time, incident type, complexity, fuels, fire
    behavior, landowner category, and personnel count come only from the sources'
    original attributes, which the history preserves verbatim.

    Args:
        entry: One fire index entry.
        perimeters: The perimeter history layer.
        points: The point history layer.

    Returns:
        The fire's latest state.
    """
    fire_identifiers = identifiers(entry)
    perimeter_row = peri_scribe.kml_row_values.latest_matching_row(
        perimeters,
        fire_identifiers,
        entry.name,
    )
    point_row = peri_scribe.kml_row_values.latest_matching_row(
        points,
        fire_identifiers,
        entry.name,
    )

    exterior_perimeter_in_miles = None
    if perimeter_row is not None:
        exterior_perimeter_in_miles = peri_scribe.units.exterior_perimeter_in_miles(
            perimeter_row.geometry,
        )

    area_in_acres = peri_scribe.kml_row_values.float_value(perimeter_row, "area_acres")
    if area_in_acres is None:
        area_in_acres = peri_scribe.kml_row_values.float_value(
            point_row,
            "incident_size",
        )

    percent_contained = peri_scribe.kml_row_values.float_value(
        perimeter_row,
        "percent_contained",
    )
    if percent_contained is None:
        percent_contained = peri_scribe.kml_row_values.float_value(
            point_row,
            "percent_contained",
        )

    estimated_cost_to_date = peri_scribe.kml_row_values.float_value(
        perimeter_row,
        "estimated_cost_to_date",
    )
    if estimated_cost_to_date is None:
        estimated_cost_to_date = peri_scribe.kml_row_values.float_value(
            point_row,
            "estimated_cost_to_date",
        )

    estimated_final_cost = peri_scribe.kml_row_values.float_value(
        perimeter_row,
        "estimated_final_cost",
    )
    if estimated_final_cost is None:
        estimated_final_cost = peri_scribe.kml_row_values.float_value(
            point_row,
            "estimated_final_cost",
        )

    total_personnel = peri_scribe.kml_row_values.first_source_number(
        perimeter_row,
        point_row,
        peri_scribe.kml_plot_data.POINT_PERSONNEL_ATTRIBUTE_KEY,
        peri_scribe.kml_plot_data.PERIMETER_PERSONNEL_ATTRIBUTE_KEY,
    )

    discovery_time = peri_scribe.kml_row_values.datetime_value(
        perimeter_row,
        "discovery_time",
    )
    if discovery_time is None:
        discovery_time = peri_scribe.kml_row_values.datetime_value(
            point_row,
            "discovery_time",
        )

    observation_time = peri_scribe.kml_row_values.datetime_value(
        perimeter_row,
        "observation_time",
    )
    if observation_time is None:
        observation_time = peri_scribe.kml_row_values.datetime_value(
            point_row,
            "observation_time",
        )

    initial_response_time = peri_scribe.kml_row_values.as_datetime(
        peri_scribe.kml_row_values.source_attribute_value(
            perimeter_row,
            "attr_InitialResponseDateTime",
        ),
    )
    if initial_response_time is None:
        initial_response_time = peri_scribe.kml_row_values.as_datetime(
            peri_scribe.kml_row_values.source_attribute_value(
                point_row,
                "InitialResponseDateTime",
            ),
        )

    protecting_unit = peri_scribe.kml_row_values.source_text_value(
        point_row,
        "POOJurisdictionalUnit",
    )
    if protecting_unit is None:
        protecting_unit = peri_scribe.kml_row_values.source_text_value(
            point_row,
            "POOProtectingUnit",
        )
    if protecting_unit is None:
        protecting_unit = peri_scribe.kml_row_values.source_text_value(
            point_row,
            "POOJurisdictionalAgency",
        )

    return peri_scribe.kml_descriptions.FireDescription(
        identifier=entry.identifier,
        source=peri_scribe.kml_row_values.source_label(
            peri_scribe.kml_row_values.column_value(perimeter_row, "source"),
        ),
        mission=peri_scribe.kml_row_values.text_value(perimeter_row, "mission"),
        area_in_acres=area_in_acres,
        exterior_perimeter_in_miles=exterior_perimeter_in_miles,
        percent_contained=percent_contained,
        estimated_cost_to_date_in_dollars=estimated_cost_to_date,
        estimated_final_cost_in_dollars=estimated_final_cost,
        total_personnel=total_personnel,
        protecting_unit=protecting_unit,
        discovery_time=discovery_time,
        observation_time=observation_time,
        initial_response_time=initial_response_time,
        incident_type=peri_scribe.kml_row_values.first_source_text(
            perimeter_row,
            point_row,
            "IncidentTypeCategory",
            None,
        ),
        incident_complexity=peri_scribe.kml_row_values.numbered_source_text(
            perimeter_row,
            point_row,
            INCIDENT_COMPLEXITY_ATTRIBUTE_KEYS,
        ),
        fuel_model=peri_scribe.kml_row_values.numbered_source_text(
            perimeter_row,
            point_row,
            FUEL_MODEL_ATTRIBUTE_KEYS,
        ),
        fire_behavior=peri_scribe.kml_row_values.numbered_source_text(
            perimeter_row,
            point_row,
            FIRE_BEHAVIOR_ATTRIBUTE_KEYS,
        ),
        landowner_category=peri_scribe.kml_row_values.first_source_text(
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
    perimeters folder, the differential growth rings feed the progression maps, and the
    point and perimeter histories feed the line plots embedded in each fire's balloon.
    All of the fires' plots are rendered together, in parallel, in one shared process
    pool.

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
    plot_bundles: list[tuple[str, tuple[peri_scribe.kml_plot_data.FirePlot, ...]]] = []
    pending: list[
        tuple[
            peri_scribe.models.FireIndexEntry,
            frozenset[str],
            tuple[Perimeter, ...],
            tuple[peri_scribe.perimeter_progression.Ring, ...],
        ]
    ] = []
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
        pending.append(
            (
                entry,
                fire_identifiers,
                perimeter_observations,
                tuple(
                    peri_scribe.perimeter_progression.Ring(
                        geometry=ring.geometry,
                        observation_time=ring.observation_time,
                    )
                    for ring in ring_observations
                ),
            ),
        )
        plot_bundles.append(
            (
                prefix,
                peri_scribe.kml_plot_data.fire_plots(
                    fire_identifiers,
                    entry.name,
                    perimeters,
                    points,
                ),
            ),
        )
    image_bundles = peri_scribe.kml_plot_rendering.plot_image_bundles(
        tuple(plot_bundles),
    )
    fires: list[FireGeometry] = []
    for (
        entry,
        fire_identifiers,
        perimeter_observations,
        progression_rings,
    ), images in zip(pending, image_bundles, strict=True):
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
                progression_rings=progression_rings,
                description=peri_scribe.kml_descriptions.description_html(
                    fire_description(entry, perimeters, points),
                    tuple(image.filename for image in images),
                ),
                images=images,
            ),
        )
    return sorted(fires, key=lambda fire: fire.name.casefold())
