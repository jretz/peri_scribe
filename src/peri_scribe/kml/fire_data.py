"""Turning a year's history layers into the geometry each fire symbolizes.

These helpers group perimeters and point locations by fire, derive each fire's
latest state for its balloon description, and assemble one FireGeometry per
indexed fire together with its rendered plot images.
"""

from __future__ import annotations

import dataclasses
import datetime
import typing

import peri_scribe.kml.descriptions
import peri_scribe.kml.plot_data
import peri_scribe.kml.plot_rendering
import peri_scribe.kml.selection
import peri_scribe.kml.text
import peri_scribe.models
import peri_scribe.perimeters.progression
import peri_scribe.units


if typing.TYPE_CHECKING:
    import geopandas
    import shapely


# The smallest computed or reported area that keeps a fire in the KMZ output. Fires
# whose every area indication is missing or below this are the season's long tail of
# tiny incidents, which clutter Google Earth without adding information.


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
    progression_rings: tuple[peri_scribe.perimeters.progression.Ring, ...] = ()
    description: str | None = None
    images: tuple[peri_scribe.kml.plot_rendering.PlotImage, ...] = ()
    identifiers: frozenset[str] = frozenset()


# A differential ring smaller than this adds nothing visible to the map, so it is
# dropped rather than carried into the KMZ.
MINIMUM_RING_AREA_IN_SQUARE_METERS = 1.0


def progression_ring(
    perimeter: Perimeter,
) -> peri_scribe.perimeters.progression.Ring | None:
    """Return *perimeter* as a growth ring, or None when it is too small.

    The ring's area is measured geodesically from its geometry so the growth-window and
    color logic later work in true map area rather than whatever acreage the source
    reported.

    Args:
        perimeter: The differential perimeter to turn into a ring.

    Returns:
        The ring, or None when its area is at most one square meter.
    """
    area_in_square_meters = peri_scribe.units.area_in_square_meters(perimeter.geometry)
    if area_in_square_meters <= MINIMUM_RING_AREA_IN_SQUARE_METERS:
        return None
    return peri_scribe.perimeters.progression.Ring(
        geometry=perimeter.geometry,
        observation_time=perimeter.observation_time,
        area=area_in_square_meters,
    )


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
    scores: peri_scribe.models.FireScores | None = None,
) -> list[FireGeometry]:
    """Return each indexed fire's geometry and plots, sorted by case-folded name.

    Each fire's point is its last known location, or a representative point of its
    latest perimeter when no location is known. The full perimeters feed the latest
    perimeters folder, the differential growth rings feed the progression maps, and the
    point and perimeter histories feed the line plots embedded in each fire's balloon.
    All of the fires' plots are rendered together, in parallel, in one shared process
    pool. When scores are supplied, each fire's score explanation is shown as the final
    row of its balloon, matched by identifier and falling back to name.

    Args:
        index: The fire index that names each fire and its status.
        perimeters: The perimeter history layer.
        points: The point history layer.
        differential_perimeters: The differential perimeter history layer.
        scores: The saved score for each fire, or None.

    Returns:
        One entry per indexed fire, sorted by case-folded name.
    """
    notes_by_identifier = (
        {
            entry.identifier: entry.explanation
            for entry in scores.fires
            if entry.identifier is not None
        }
        if scores is not None
        else {}
    )
    notes_by_name = (
        {
            entry.name: entry.explanation
            for entry in scores.fires
            if entry.identifier is None
        }
        if scores is not None
        else {}
    )
    perimeter_by_identifier, perimeter_by_name = (
        peri_scribe.kml.selection.perimeter_groups(perimeters)
    )
    ring_by_identifier, ring_by_name = peri_scribe.kml.selection.perimeter_groups(
        differential_perimeters,
    )
    point_by_identifier, point_by_name = peri_scribe.kml.selection.point_locations(
        points,
    )
    plot_bundles: list[tuple[str, tuple[peri_scribe.kml.plot_data.FirePlot, ...]]] = []
    pending: list[
        tuple[
            peri_scribe.models.FireIndexEntry,
            frozenset[str],
            tuple[Perimeter, ...],
            tuple[peri_scribe.perimeters.progression.Ring, ...],
        ]
    ] = []
    used_prefixes: set[str] = set()
    for entry in index.fires:
        fire_identifiers = peri_scribe.kml.selection.identifiers(entry)
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
        prefix = peri_scribe.kml.selection.unique_filename_prefix(
            entry.identifier,
            entry.name,
            frozenset(used_prefixes),
        )
        used_prefixes.add(prefix)
        progression_rings = tuple(
            ring
            for observation in ring_observations
            if (ring := progression_ring(observation)) is not None
        )
        pending.append(
            (
                entry,
                fire_identifiers,
                perimeter_observations,
                progression_rings,
            ),
        )
        plot_bundles.append(
            (
                prefix,
                peri_scribe.kml.plot_data.fire_plots(
                    fire_identifiers,
                    entry.name,
                    perimeters,
                    points,
                ),
            ),
        )
    image_bundles = peri_scribe.kml.plot_rendering.plot_image_bundles(
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
                point=peri_scribe.kml.selection.fire_point_location(
                    fire_identifiers,
                    entry.name,
                    point_by_identifier,
                    point_by_name,
                    perimeter_observations,
                ),
                perimeters=perimeter_observations,
                progression_rings=progression_rings,
                identifiers=fire_identifiers,
                description=peri_scribe.kml.descriptions.description_html(
                    peri_scribe.kml.text.fire_description(
                        entry,
                        perimeters,
                        points,
                        of_note=peri_scribe.kml.text.score_explanation_for(
                            notes_by_identifier,
                            notes_by_name,
                            fire_identifiers,
                            entry.name,
                        ),
                    ),
                    tuple(image.filename for image in images),
                ),
                images=images,
            ),
        )
    return sorted(fires, key=lambda fire: fire.name.casefold())
