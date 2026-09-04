"""Turning a year's history layers into the geometry each fire symbolizes.

These helpers group perimeters and point locations by fire, derive each fire's
latest state for its balloon description, and assemble one FireGeometry per
indexed fire together with its rendered plot images.
"""

from __future__ import annotations

import dataclasses
import datetime
import typing

import shapely

import peri_scribe.kml.descriptions
import peri_scribe.kml.history_index
import peri_scribe.kml.plot_data
import peri_scribe.kml.plot_rendering
import peri_scribe.kml.selection
import peri_scribe.kml.text
import peri_scribe.models
import peri_scribe.perimeters.progression
import peri_scribe.units


if typing.TYPE_CHECKING:
    import geopandas


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
    description: peri_scribe.kml.descriptions.FireDescription | None = None
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


def ring_added_areas_in_acres(
    rings: typing.Sequence[peri_scribe.perimeters.progression.Ring],
) -> tuple[float, ...]:
    """Return each ring's added area in acres, in chronological order.

    A ring's added area is the area of the fire once that ring is included minus the
    area of the fire with only the earlier rings, measured from the ring geometries as
    the KMZ draws them. The interior ring balloons show each ring's added area so a
    reader can see how much new ground that ring's observation added; measuring the
    unions rather than trusting each ring's own area keeps that figure honest when a
    ring re-covers ground an earlier ring already claimed.

    Args:
        rings: The fire's growth rings in chronological order.

    Returns:
        Each ring's added area in acres, in the input order.
    """
    cumulative_areas_in_acres: list[float] = []
    combined_geometry: shapely.Geometry | None = None
    for ring in rings:
        combined_geometry = (
            ring.geometry
            if combined_geometry is None
            else shapely.union(combined_geometry, ring.geometry)
        )
        cumulative_areas_in_acres.append(
            peri_scribe.units.area_in_acres(combined_geometry),
        )
    added_areas_in_acres: list[float] = []
    previous_area_in_acres = 0.0
    for cumulative_area_in_acres in cumulative_areas_in_acres:
        # A later ring never removes ground from the fire it joins, so a tiny negative
        # difference is measurement noise, not shrinkage.
        added_areas_in_acres.append(
            max(0.0, cumulative_area_in_acres - previous_area_in_acres),
        )
        previous_area_in_acres = cumulative_area_in_acres
    return tuple(added_areas_in_acres)


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


# One fire's prepared work while its plots render: the entry, its identifiers, the
# geometry observations and growth rings, and the perimeter and point row positions used
# to rebuild small slices for the balloon description.
PendingFire = tuple[
    peri_scribe.models.FireIndexEntry,
    frozenset[str],
    tuple[Perimeter, ...],
    tuple[peri_scribe.perimeters.progression.Ring, ...],
    tuple[int, ...],
    tuple[int, ...],
]

# One fire's rendered plots: the filename prefix and the plots to draw.
PlotBundle = tuple[str, tuple[peri_scribe.kml.plot_data.FirePlot, ...]]


def prepare_fire_bundles(
    *,
    index: peri_scribe.models.FireIndex,
    perimeters: geopandas.GeoDataFrame,
    points: geopandas.GeoDataFrame,
    perimeter_by_identifier: dict[str, list[Perimeter]],
    perimeter_by_name: dict[str, list[Perimeter]],
    ring_by_identifier: dict[str, list[Perimeter]],
    ring_by_name: dict[str, list[Perimeter]],
) -> tuple[list[PendingFire], list[PlotBundle]]:
    """Return each fire's pending entry and plot bundle.

    One pass indexes the two history layers by row position, then each fire's rows are
    looked up and sliced without scanning the full frames. The pending entries retain
    only the row positions, so the full layers stay loaded while only one fire's small
    slices exist at a time.

    Args:
        index: The fire index that names each fire and its status.
        perimeters: The perimeter history layer.
        points: The point history layer.
        perimeter_by_identifier: Perimeters keyed by identifier.
        perimeter_by_name: Perimeters keyed by name.
        ring_by_identifier: Differential perimeters keyed by identifier.
        ring_by_name: Differential perimeters keyed by name.

    Returns:
        Each fire's pending entry and each fire's plot bundle, in index order.
    """
    perimeter_index = peri_scribe.kml.history_index.HistoryRowIndex.from_frame(
        perimeters,
    )
    point_index = peri_scribe.kml.history_index.HistoryRowIndex.from_frame(points)
    pending: list[PendingFire] = []
    plot_bundles: list[PlotBundle] = []
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
        perimeter_positions = perimeter_index.positions_for(
            fire_identifiers,
            entry.name,
        )
        point_positions = point_index.positions_for(
            fire_identifiers,
            entry.name,
        )
        pending.append(
            (
                entry,
                fire_identifiers,
                perimeter_observations,
                progression_rings,
                perimeter_positions,
                point_positions,
            ),
        )
        plot_bundles.append(
            (
                prefix,
                peri_scribe.kml.plot_data.fire_plots(
                    peri_scribe.kml.history_index.select_rows(
                        perimeters,
                        perimeter_positions,
                    ),
                    peri_scribe.kml.history_index.select_rows(
                        points,
                        point_positions,
                    ),
                ),
            ),
        )
    return pending, plot_bundles


def fire_geometries(
    index: peri_scribe.models.FireIndex,
    perimeters: geopandas.GeoDataFrame,
    points: geopandas.GeoDataFrame,
    differential_perimeters: geopandas.GeoDataFrame,
    scores: peri_scribe.models.FireScores | None = None,
    *,
    render_plots: bool = True,
) -> list[FireGeometry]:
    """Return each indexed fire's geometry and plots, sorted by case-folded name.

    Each fire's point is its last known location, or a representative point of its
    latest perimeter when no location is known. The full perimeters feed the latest
    perimeters folder, the differential growth rings feed the progression maps, and the
    point and perimeter histories feed the line plots embedded in each fire's balloon.
    When *render_plots* is True the fires' plots are rendered together, in parallel, in
    one shared process pool. When scores are supplied, each fire's score explanation is
    shown as the final row of its balloon, matched by identifier and falling back to
    name.

    Args:
        index: The fire index that names each fire and its status.
        perimeters: The perimeter history layer.
        points: The point history layer.
        differential_perimeters: The differential perimeter history layer.
        scores: The saved score for each fire, or None.
        render_plots: Whether to render each fire's plot images. Callers that only need
            each fire's description and perimeters pass False to skip the rendering
            step.

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
    pending, plot_bundles = prepare_fire_bundles(
        index=index,
        perimeters=perimeters,
        points=points,
        perimeter_by_identifier=perimeter_by_identifier,
        perimeter_by_name=perimeter_by_name,
        ring_by_identifier=ring_by_identifier,
        ring_by_name=ring_by_name,
    )
    if render_plots:
        image_bundles = peri_scribe.kml.plot_rendering.plot_image_bundles(
            tuple(plot_bundles),
        )
    else:
        image_bundles = tuple(() for _plot_bundle in plot_bundles)
    fires: list[FireGeometry] = []
    for (
        entry,
        fire_identifiers,
        perimeter_observations,
        progression_rings,
        perimeter_positions,
        point_positions,
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
                description=peri_scribe.kml.text.fire_description(
                    entry,
                    peri_scribe.kml.history_index.select_rows(
                        perimeters,
                        perimeter_positions,
                    ),
                    peri_scribe.kml.history_index.select_rows(
                        points,
                        point_positions,
                    ),
                    of_note=peri_scribe.kml.text.score_explanation_for(
                        notes_by_identifier,
                        notes_by_name,
                        fire_identifiers,
                        entry.name,
                    ),
                ),
                images=images,
            ),
        )
    return sorted(fires, key=lambda fire: fire.name.casefold())
