"""Attach map imagery and progression colors to shared fire summaries."""

from __future__ import annotations

import dataclasses
import functools
import typing

import peri_scribe.areas
import peri_scribe.kml.colormap
import peri_scribe.kml.plot_data
import peri_scribe.kml.plot_rendering
import peri_scribe.logging
import peri_scribe.models
import peri_scribe.perimeters.progression
import peri_scribe.phases
import peri_scribe.presentation.fire_data
import peri_scribe.presentation.history_index
import peri_scribe.presentation.perimeters
import peri_scribe.presentation.selection


if typing.TYPE_CHECKING:
    import geopandas
    import pint


@dataclasses.dataclass(frozen=True, kw_only=True)
class FireGeometry(peri_scribe.presentation.fire_data.FireSummary):
    """A fire's shared facts together with the plot images embedded in its map."""

    images: tuple[peri_scribe.kml.plot_rendering.PlotImage, ...] = ()


@functools.cache
def added_areas_for_rings(
    rings: tuple[peri_scribe.perimeters.progression.Ring, ...],
) -> tuple[pint.Quantity[float], ...]:
    """Return each ring's added area, cached by the exact ring sequence.

    The folder views each serialize a fire once, and a fire's drawn ring sequence
    carries the same ring objects into every view, so the cumulative union work is
    computed for the first view and reused by the rest instead of repeated per view.

    Args:
        rings: The fire's growth rings in chronological order.

    Returns:
        Each ring's added area, in the input order.
    """
    if rings and all(ring.added_area is not None for ring in rings):
        digest = peri_scribe.perimeters.progression.sequence_digest(
            ring.geometry for ring in rings
        )
        if all(ring.sequence_digest == digest for ring in rings):
            return tuple(
                typing.cast("pint.Quantity[float]", ring.added_area) for ring in rings
            )
    return peri_scribe.perimeters.progression.added_areas(
        ring.geometry for ring in rings
    )


def ring_added_areas(
    rings: typing.Sequence[peri_scribe.perimeters.progression.Ring],
) -> tuple[pint.Quantity[float], ...]:
    """Return each ring's added area, in chronological order.

    A ring's added area is the area of the fire once that ring is included minus the
    area of the fire with only the earlier rings, measured from the ring geometries as
    the KMZ draws them. The interior ring balloons show each ring's added area so a
    reader can see how much new ground that ring's observation added; measuring the
    unions rather than trusting each ring's own area keeps that figure honest when a
    ring re-covers ground an earlier ring already claimed.

    Args:
        rings: The fire's growth rings in chronological order.

    Returns:
        Each ring's added area, in the input order.
    """
    return added_areas_for_rings(tuple(rings))


def interior_ring_colors(
    rings: typing.Sequence[peri_scribe.perimeters.progression.Ring],
    perimeters: typing.Sequence[peri_scribe.presentation.perimeters.Perimeter],
) -> tuple[tuple[peri_scribe.perimeters.progression.Ring, str], ...]:
    """Return the (ring, color) pairs a fire's interior folder draws.

    Only dated rings can carry a progression color, so the folder draws the dated rings,
    each colored for the day it was observed. A fire whose rings carry no observation
    times falls back to its latest perimeter in the hottest color, so every fire with a
    perimeter still shows an interior; the interior folder and the added areas
    precomputed while plots render both derive the drawn rings from this one function,
    so their ring sequences cannot drift apart.

    Args:
        rings: The fire's growth rings in chronological order.
        perimeters: The fire's perimeters in chronological order.

    Returns:
        One (ring, color) pair per drawn ring, oldest first.
    """
    colored_rings = peri_scribe.kml.colormap.progression_ring_colors(rings)
    if colored_rings:
        return tuple(
            (ring, peri_scribe.kml.colormap.color_hex(rgb))
            for ring, rgb in colored_rings
        )
    if perimeters:
        latest_perimeter = perimeters[-1]
        return (
            (
                peri_scribe.perimeters.progression.Ring(
                    geometry=latest_perimeter.geometry,
                    observation_time=latest_perimeter.observation_time,
                    area=latest_perimeter.measured_area,
                    added_area=latest_perimeter.measured_area,
                    sequence_digest=peri_scribe.perimeters.progression.sequence_digest(
                        (latest_perimeter.geometry,),
                    ),
                ),
                peri_scribe.kml.colormap.color_hex(
                    peri_scribe.kml.colormap.TURBO_RAMP[-1],
                ),
            ),
        )
    return ()


def precompute_interior_added_areas(
    fires: typing.Sequence[peri_scribe.presentation.fire_data.FireSummary],
) -> None:
    """Warm the added-area cache for every pending fire's drawn rings.

    The folder-writing phase asks each fire for the same added areas, and computing them
    there lengthens that single-threaded phase, so this runs before the plots are drawn
    instead: by the time the folders are written every fire's cumulative union work is
    done and the folder's requests hit the cache.

    Args:
        fires: The prepared fires with their perimeter observations and progression
            rings awaiting plot and folder generation.
    """
    for fire in fires:
        sequence = tuple(
            ring
            for ring, _color in interior_ring_colors(
                fire.progression_rings,
                fire.perimeters,
            )
        )
        if sequence:
            added_areas_for_rings(sequence)


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


def fire_geometries(
    index: peri_scribe.models.FireIndex,
    perimeters: geopandas.GeoDataFrame,
    points: geopandas.GeoDataFrame,
    differential_perimeters: geopandas.GeoDataFrame,
    scores: peri_scribe.models.FireScores | None = None,
    *,
    incident_rows: geopandas.GeoDataFrame | None = None,
    histories: typing.Mapping[
        peri_scribe.presentation.selection.AreaKey,
        peri_scribe.areas.PreparedHistory,
    ]
    | None = None,
) -> list[FireGeometry]:
    """Render chart images for the shared fire facts shown on the map.

    Args:
        index: Fire identities and current status.
        perimeters: The full perimeter history.
        points: The point history.
        differential_perimeters: Differential growth rings.
        scores: Saved scores and their explanations, when available.
        incident_rows: The optional independent incident history.
        histories: Already prepared reporting evidence keyed by fire identity.

    Returns:
        The named and sorted fires, with each fire's rendered map images.
    """
    prepared = peri_scribe.presentation.fire_data.prepare_fire_data(
        index,
        perimeters,
        points,
        differential_perimeters,
        scores,
        incident_rows=incident_rows,
        histories=histories,
    )
    bundles: list[tuple[str, tuple[peri_scribe.kml.plot_data.FirePlot, ...]]] = []
    used_prefixes: set[str] = set()
    for fire in prepared:
        prefix = unique_filename_prefix(
            fire.identifier,
            fire.summary.name,
            frozenset(used_prefixes),
        )
        used_prefixes.add(prefix)
        bundles.append((
            prefix,
            peri_scribe.kml.plot_data.fire_plots(
                peri_scribe.presentation.history_index.select_rows(
                    perimeters,
                    fire.perimeter_positions,
                ),
                peri_scribe.presentation.history_index.select_rows(
                    points,
                    fire.point_positions,
                ),
                history=fire.history,
            ),
        ))
    with peri_scribe.logging.log_phase(peri_scribe.phases.Phase.PREPARE_PLOT_IMAGES):
        images = peri_scribe.kml.plot_rendering.plot_image_bundles(
            tuple(bundles),
            before_rendering=functools.partial(
                precompute_interior_added_areas,
                [fire.summary for fire in prepared],
            ),
        )
    return sorted(
        [
            FireGeometry(
                name=fire.summary.name,
                status=fire.summary.status,
                point=fire.summary.point,
                perimeters=fire.summary.perimeters,
                progression_rings=fire.summary.progression_rings,
                description=fire.summary.description,
                identifiers=fire.summary.identifiers,
                type_one=fire.summary.type_one,
                images=fire_images,
            )
            for fire, fire_images in zip(prepared, images, strict=True)
        ],
        key=peri_scribe.presentation.fire_data.fire_name_key,
    )
