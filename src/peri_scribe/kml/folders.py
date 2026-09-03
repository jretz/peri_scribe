"""Building the KML folder hierarchy for a year's fires.

These helpers append each fire's folder and the top-level active and inactive status
folders to a shared :class:`peri_scribe.kml.geometry.KmlWriter`.
"""

from __future__ import annotations

import datetime
import math
import operator
import typing

import peri_scribe.kml.colormap
import peri_scribe.kml.descriptions
import peri_scribe.kml.fire_data
import peri_scribe.kml.geometry
import peri_scribe.kml.icons
import peri_scribe.kml.styles
import peri_scribe.kml.tour
import peri_scribe.models
import peri_scribe.perimeters.progression
import peri_scribe.units


ACTIVE_FIRES_FOLDER_NAME = "Active Fires"
INACTIVE_FIRES_FOLDER_NAME = "Inactive Fires"
TOP_FIRES_BY_NAME_FOLDER_NAME = "Top Fires by Name"
TOP_FIRES_BY_SCORE_FOLDER_NAME = "Top Fires by Score"
TOP_FIRE_COUNT = 50

NEW_NOTABLE_FIRES_FOLDER_NAME = "New, Notable Fires"
FAST_GROWING_FIRES_BY_ACRES_FOLDER_NAME = "Fast Growing Fires (acres)"
FAST_GROWING_FIRES_BY_PERCENT_FOLDER_NAME = "Fast Growing Fires (%)"
MOST_PERSONNEL_FIRES_FOLDER_NAME = "Fires with Most Personnel"

# A newly discovered fire stays in the "New, Notable Fires" view for this long.
NEW_NOTABLE_DISCOVERY_LOOKBACK = datetime.timedelta(days=5)

# The growth window for the fast-growing views, and the minimum growth a fire needs to
# qualify for each.
FAST_GROWTH_LOOKBACK = datetime.timedelta(hours=48)
MINIMUM_FAST_GROWTH_IN_ACRES = 1000.0
MINIMUM_FAST_GROWTH_IN_PERCENT = 10.0

# A fire stays in the "Fires with Most Personnel" view only while it was updated this
# recently.
MOST_PERSONNEL_UPDATE_LOOKBACK = datetime.timedelta(days=7)

# The fraction of the highest-scoring active fires that defines "notable".
NOTABLE_SCORE_FRACTION = 0.20

# The folder inside each fire's folder that holds its outline perimeters, present only
# when the fire has more than one.
PERIMETERS_FOLDER_NAME = "Perimeters"

# The folder inside each fire's folder that holds the growth rings filling its interior.
INTERIOR_FOLDER_NAME = "Interior"


def fire_balloon(
    fire: peri_scribe.kml.fire_data.FireGeometry,
    added_area_in_acres: float | None = None,
) -> str | None:
    """Return the KML balloon text for *fire*'s placemarks.

    Every placemark showing the fire as a whole carries the same balloon describing the
    fire's latest state, so a reader sees the same facts whether they click the point,
    an outline, or a ring. With *added_area_in_acres*, the text instead opens that
    balloon's table with the area a growth ring added to the fire, so the ring's own
    growth reads above the fire's shared state. A fire without a description has no
    balloon.

    Args:
        fire: The fire to describe.
        added_area_in_acres: The acres the placemark's growth ring added, or None for
            the fire's own placemarks.

    Returns:
        The balloon's KML description text, or None when the fire has no description.
    """
    if fire.description is None:
        return None
    image_filenames = tuple(image.filename for image in fire.images)
    if added_area_in_acres is None:
        return peri_scribe.kml.descriptions.description_html(
            fire.description,
            image_filenames,
        )
    return peri_scribe.kml.descriptions.description_html(
        fire.description,
        image_filenames,
        leading_rows=(
            (
                peri_scribe.kml.descriptions.ADDED_AREA_LABEL,
                peri_scribe.kml.descriptions.format_in_acres(added_area_in_acres),
            ),
        ),
    )


def outline_placemarks(
    writer: peri_scribe.kml.geometry.KmlWriter,
    fire: peri_scribe.kml.fire_data.FireGeometry,
    style_urls: typing.Mapping[str, str],
    outline_count: int,
    ring_count: int,
    *,
    visible: bool,
    description: str | None,
) -> None:
    """Append *fire*'s outline perimeters, newest first, to *writer*.

    The outlines draw above the fire's interior rings, so each outline stays visible
    over the rings beneath it. Each outline carries *description*, the balloon the
    fire's own placemarks share.

    Args:
        writer: The writer to append to.
        fire: The fire whose outlines to draw.
        style_urls: The style URL for each template placemark name.
        outline_count: The number of outlines to draw.
        ring_count: The number of interior rings drawn beneath the outlines.
        visible: Whether each outline is visible.
        description: The balloon text each outline shows.
    """
    for index, name in enumerate(peri_scribe.kml.styles.OUTLINED_PERIMETER_NAMES):
        if len(fire.perimeters) <= index:
            break
        perimeter = fire.perimeters[-(index + 1)]
        peri_scribe.kml.geometry.perimeter_placemark(
            writer,
            peri_scribe.kml.tour.mapping_placemark_name(perimeter.observation_time),
            style_urls[name],
            perimeter.geometry,
            peri_scribe.kml.styles.outline_draw_order(outline_count, index)
            + ring_count,
            description=description,
            visible=visible,
        )


def fire_folder(
    writer: peri_scribe.kml.geometry.KmlWriter,
    fire: peri_scribe.kml.fire_data.FireGeometry,
    style_urls: typing.Mapping[str, str],
    ring_style_urls: typing.Mapping[str, str],
    *,
    visible: bool = True,
) -> None:
    """Append the folder symbolizing *fire* to *writer*.

    The folder leads with the fire's point location, then a "Progression" tour, then its
    latest, penultimate, and antepenultimate perimeter outlines, each shown when the
    fire's history has one, and finally an ``Interior`` folder holding its growth rings
    styled by the color for the day each was observed. A fire with more than one
    perimeter holds its outline perimeters in a ``Perimeters`` folder; a fire with a
    single perimeter shows it directly. A fire with no dated rings falls back to its
    complete latest perimeter, styled with the hottest color, so every fire with
    perimeters appears with an interior. The interior lists its rings newest first while
    the tour replays them oldest first. Each interior ring's balloon opens with the area
    that ring added to the fire, so the ring's own growth reads above the fire's shared
    balloon.

    Args:
        writer: The writer to append to.
        fire: The fire to symbolize.
        style_urls: The style URL for each template placemark name.
        ring_style_urls: The style URL for each progression ring color, keyed by its
            ``#RRGGBB`` color.
        visible: Whether the folder and its features are visible.
    """
    outline_count = min(
        len(fire.perimeters),
        len(peri_scribe.kml.styles.OUTLINED_PERIMETER_NAMES),
    )
    colored_rings = peri_scribe.kml.colormap.progression_ring_colors(
        fire.progression_rings,
    )
    if colored_rings:
        rings = [
            (ring, peri_scribe.kml.colormap.color_hex(rgb))
            for ring, rgb in colored_rings
        ]
        ring_times = tuple(ring.observation_time for ring, _color in rings)
    elif fire.perimeters:
        latest_perimeter = fire.perimeters[-1]
        rings = [
            (
                peri_scribe.perimeters.progression.Ring(
                    geometry=latest_perimeter.geometry,
                    observation_time=latest_perimeter.observation_time,
                ),
                peri_scribe.kml.colormap.color_hex(
                    peri_scribe.kml.colormap.TURBO_RAMP[-1],
                ),
            ),
        ]
        ring_times = (latest_perimeter.observation_time,)
    else:
        rings = []
        ring_times = ()
    description = fire_balloon(fire)
    with writer.folder(fire.name, visible=visible) as folder_id:
        if fire.point is not None:
            peri_scribe.kml.geometry.point_placemark(
                writer,
                fire.name,
                style_urls[peri_scribe.kml.styles.POINT_LOCATION_NAME],
                fire.point,
                peri_scribe.kml.styles.point_draw_order(outline_count) + len(rings),
                description=description,
                visible=visible,
            )
        if ring_times:
            peri_scribe.kml.tour.progression_tour(
                writer,
                folder_id,
                ring_times,
                visible=visible,
            )
        if outline_count > 1:
            with writer.folder(
                PERIMETERS_FOLDER_NAME,
                visible=visible,
                item_icon=peri_scribe.kml.icons.perimeters_icon_filename(),
            ):
                outline_placemarks(
                    writer,
                    fire,
                    style_urls,
                    outline_count,
                    len(rings),
                    visible=visible,
                    description=description,
                )
        else:
            outline_placemarks(
                writer,
                fire,
                style_urls,
                outline_count,
                len(rings),
                visible=visible,
                description=description,
            )
        if rings:
            added_areas_in_acres = peri_scribe.kml.fire_data.ring_added_areas_in_acres(
                tuple(ring for ring, _color in rings),
            )
            with writer.folder(
                INTERIOR_FOLDER_NAME,
                visible=visible,
                item_icon=peri_scribe.kml.icons.interior_progression_icon_filename(),
            ):
                for index in range(len(rings) - 1, -1, -1):
                    ring, color = rings[index]
                    peri_scribe.kml.geometry.perimeter_placemark(
                        writer,
                        peri_scribe.kml.tour.interior_placemark_name(
                            ring.observation_time,
                        ),
                        ring_style_urls[color],
                        ring.geometry,
                        index,
                        description=fire_balloon(
                            fire,
                            added_areas_in_acres[index],
                        ),
                        visible=visible,
                        placemark_id=peri_scribe.kml.tour.interior_ring_id(
                            folder_id,
                            index,
                        ),
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
    writer: peri_scribe.kml.geometry.KmlWriter,
    fires: list[peri_scribe.kml.fire_data.FireGeometry],
    status: peri_scribe.models.FireStatus,
    style_urls: typing.Mapping[str, str],
    ring_style_urls: typing.Mapping[str, str],
    *,
    visible: bool | None = None,
) -> None:
    """Append the top-level folder for fires of *status* to *writer*.

    The folder holds each fire's folder directly, and each fire loads checked or
    unchecked on its own.

    Args:
        writer: The writer to append to.
        fires: Every fire.
        status: The status whose fires belong in the folder.
        style_urls: The style URL for each template placemark name.
        ring_style_urls: The style URL for each progression ring color, keyed by its
            ``#RRGGBB`` color.
        visible: Whether the folder loads checked, or None for the status default
            (active fires load checked, inactive fires load unchecked).

    The inactive fires folder loads unchecked, along with everything beneath it, so
    inactive fires stay hidden until the folder is enabled. A status folder that loads
    unchecked keeps its whole tree hidden, so it carries no visible content and its
    radio button in Google Earth loads off instead of being selected.
    """
    status_fires = [fire for fire in fires if fire.status is status]
    inactive = status is peri_scribe.models.FireStatus.INACTIVE
    if visible is None:
        visible = not inactive
    with writer.folder(
        status_folder_name(status),
        visible=visible,
    ):
        for fire in status_fires:
            fire_folder(writer, fire, style_urls, ring_style_urls, visible=visible)


def score_fire(
    entry: peri_scribe.models.FireScoreEntry,
    fires_by_identifier: typing.Mapping[
        str,
        peri_scribe.kml.fire_data.FireGeometry,
    ],
    fires_by_name: typing.Mapping[str, peri_scribe.kml.fire_data.FireGeometry],
) -> peri_scribe.kml.fire_data.FireGeometry | None:
    """Return the geometry matching *entry*, by identifier first and then name.

    Args:
        entry: One saved score.
        fires_by_identifier: The showable fires keyed by each identifier.
        fires_by_name: The showable fires keyed by name.

    Returns:
        The entry's geometry, or None when neither its identifier nor its name matches a
        showable fire.
    """
    fire = (
        fires_by_identifier.get(entry.identifier)
        if entry.identifier is not None
        else None
    )
    if fire is None:
        fire = fires_by_name.get(entry.name)
    return fire


def top_fires(
    fires: list[peri_scribe.kml.fire_data.FireGeometry],
    scores: peri_scribe.models.FireScores,
) -> list[peri_scribe.kml.fire_data.FireGeometry]:
    """Return the highest-scoring fires that are present in *fires*.

    Scores can include fires excluded from the map for lacking qualifying geography, so
    the result is matched back to the already-filtered geometry list. A score is matched
    by identifier first, so fires that share a name but not an identity each resolve to
    their own geometry; a score whose identifier matches no fire falls back to its name.

    Args:
        fires: The fires that can be shown in the KMZ.
        scores: The saved score for each fire.

    Returns:
        The top fires in descending score order.
    """
    fires_by_identifier = {
        identifier: fire for fire in fires for identifier in fire.identifiers
    }
    fires_by_name = {fire.name: fire for fire in fires}
    matched = [
        score_fire(entry, fires_by_identifier, fires_by_name)
        for entry in sorted(
            scores.fires,
            key=lambda entry: (-entry.score, entry.name.casefold()),
        )
    ]
    return [fire for fire in matched if fire is not None][:TOP_FIRE_COUNT]


def score_maps(
    scores: peri_scribe.models.FireScores,
) -> tuple[
    dict[str, peri_scribe.models.FireScoreEntry],
    dict[str, peri_scribe.models.FireScoreEntry],
]:
    """Return the score entries keyed by identifier and by name.

    An entry with an identifier is keyed by that identifier; an entry without one is
    keyed by its name. The two maps mirror how a score is matched back to a fire, so a
    fire resolves to the same entry however it is looked up.

    Args:
        scores: The saved score for each fire.

    Returns:
        The entries keyed by identifier and by name.
    """
    scores_by_identifier: dict[str, peri_scribe.models.FireScoreEntry] = {}
    scores_by_name: dict[str, peri_scribe.models.FireScoreEntry] = {}
    for entry in scores.fires:
        identifier = entry.identifier
        if identifier is not None:
            scores_by_identifier[identifier] = entry
        else:
            scores_by_name[entry.name] = entry
    return scores_by_identifier, scores_by_name


def score_value_for_fire(
    fire: peri_scribe.kml.fire_data.FireGeometry,
    scores_by_identifier: typing.Mapping[str, peri_scribe.models.FireScoreEntry],
    scores_by_name: typing.Mapping[str, peri_scribe.models.FireScoreEntry],
) -> int | None:
    """Return *fire*'s score, or None when no entry matches it.

    A fire's identifiers are checked first, so fires that share a name but not an
    identity each resolve to their own score; a fire whose identifier matches nothing
    falls back to its name.

    Args:
        fire: The fire to score.
        scores_by_identifier: Score entries keyed by identifier.
        scores_by_name: Score entries keyed by name.

    Returns:
        The fire's score, or None when no entry matches.
    """
    for identifier in sorted(fire.identifiers):
        entry = scores_by_identifier.get(identifier)
        if entry is not None:
            return entry.score
    entry = scores_by_name.get(fire.name)
    return None if entry is None else entry.score


def notable_score_threshold(
    fires: list[peri_scribe.kml.fire_data.FireGeometry],
    scores: peri_scribe.models.FireScores,
) -> int | None:
    """Return the lowest score in the top fraction of active fires.

    The threshold is the score of the last fire in the highest-scoring
    :data:`NOTABLE_SCORE_FRACTION` of active fires, so a fire at or above it is among
    that fraction.

    Args:
        fires: The fires that can be shown in the KMZ.
        scores: The saved score for each fire.

    Returns:
        The cutoff score, or None when no active fire has a score.
    """
    scores_by_identifier, scores_by_name = score_maps(scores)
    active_scores: list[int] = []
    for fire in fires:
        if fire.status is not peri_scribe.models.FireStatus.ACTIVE:
            continue
        score = score_value_for_fire(fire, scores_by_identifier, scores_by_name)
        if score is not None:
            active_scores.append(score)
    if not active_scores:
        return None
    active_scores.sort(reverse=True)
    top_count = max(1, math.ceil(len(active_scores) * NOTABLE_SCORE_FRACTION))
    return active_scores[top_count - 1]


def new_notable_fires(
    fires: list[peri_scribe.kml.fire_data.FireGeometry],
    scores: peri_scribe.models.FireScores,
    reference_time: datetime.datetime | None,
) -> list[peri_scribe.kml.fire_data.FireGeometry]:
    """Return the newly discovered fires that score among the top active fires.

    A fire qualifies when it was discovered within
    :data:`NEW_NOTABLE_DISCOVERY_LOOKBACK` of *reference_time* and its score meets the
    active-fire threshold.

    Args:
        fires: The fires that can be shown in the KMZ.
        scores: The saved score for each fire.
        reference_time: The wall-clock time of the KMZ generation, or None when no
            reference time is available.

    Returns:
        The qualifying fires in descending score order.
    """
    if reference_time is None:
        return []
    threshold = notable_score_threshold(fires, scores)
    if threshold is None:
        return []
    scores_by_identifier, scores_by_name = score_maps(scores)
    cutoff = reference_time - NEW_NOTABLE_DISCOVERY_LOOKBACK
    scored: list[tuple[peri_scribe.kml.fire_data.FireGeometry, int]] = []
    for fire in fires:
        discovery_time = (
            fire.description.discovery_time if fire.description is not None else None
        )
        if discovery_time is None:
            continue
        if discovery_time < cutoff or discovery_time > reference_time:
            continue
        score = score_value_for_fire(fire, scores_by_identifier, scores_by_name)
        if score is None or score < threshold:
            continue
        scored.append((fire, score))
    scored.sort(key=lambda pair: (-pair[1], pair[0].name.casefold()))
    return [fire for fire, _score in scored]


def fire_growth(
    fire: peri_scribe.kml.fire_data.FireGeometry,
    reference_time: datetime.datetime,
) -> tuple[float | None, float | None]:
    """Return *fire*'s growth over the fast-growth window.

    The fire's latest known area is compared with its area at the start of the window,
    measured from its perimeters. A fire first observed inside the window has no area
    at the window's start, so it is treated as having grown from zero acres: its whole
    latest area counts as growth, and its growth in percent is unknown because a zero
    baseline has no percentage.

    Args:
        fire: The fire to measure.
        reference_time: The wall-clock time of the KMZ generation.

    Returns:
        The growth in acres and percent, or None for each when it cannot be measured.
    """
    timed_perimeters: list[
        tuple[datetime.datetime, peri_scribe.kml.fire_data.Perimeter],
    ] = []
    for perimeter in fire.perimeters:
        observation_time = perimeter.observation_time
        if observation_time is not None:
            timed_perimeters.append((observation_time, perimeter))
    if not timed_perimeters:
        return None, None
    timed_perimeters.sort(key=operator.itemgetter(0))
    latest_perimeter = timed_perimeters[-1][1]
    latest_area_in_acres = peri_scribe.units.area_in_acres(
        latest_perimeter.geometry,
    )
    cutoff = reference_time - FAST_GROWTH_LOOKBACK
    baseline_perimeter: peri_scribe.kml.fire_data.Perimeter | None = None
    for observation_time, perimeter in reversed(timed_perimeters):
        if observation_time <= cutoff:
            baseline_perimeter = perimeter
            break
    if baseline_perimeter is None:
        return latest_area_in_acres, None
    baseline_area_in_acres = peri_scribe.units.area_in_acres(
        baseline_perimeter.geometry,
    )
    growth_in_acres = latest_area_in_acres - baseline_area_in_acres
    growth_in_percent = (
        growth_in_acres / baseline_area_in_acres * 100.0
        if baseline_area_in_acres > 0
        else None
    )
    return growth_in_acres, growth_in_percent


def fast_growing_fires_by_acres(
    fires: list[peri_scribe.kml.fire_data.FireGeometry],
    reference_time: datetime.datetime | None,
) -> list[peri_scribe.kml.fire_data.FireGeometry]:
    """Return the fires that grew most in acres over the fast-growth window.

    A fire qualifies when it grew at least :data:`MINIMUM_FAST_GROWTH_IN_ACRES` acres;
    a fire first observed inside the window is treated as having grown from zero acres,
    so its whole latest area counts. The result is limited to :data:`TOP_FIRE_COUNT`
    fires.

    Args:
        fires: The fires that can be shown in the KMZ.
        reference_time: The wall-clock time of the KMZ generation, or None when no
            reference time is available.

    Returns:
        The qualifying fires in descending growth order.
    """
    if reference_time is None:
        return []
    growing: list[tuple[peri_scribe.kml.fire_data.FireGeometry, float]] = []
    for fire in fires:
        growth_in_acres, _growth_in_percent = fire_growth(fire, reference_time)
        if (
            growth_in_acres is not None
            and growth_in_acres >= MINIMUM_FAST_GROWTH_IN_ACRES
        ):
            growing.append((fire, growth_in_acres))
    growing.sort(key=lambda pair: (-pair[1], pair[0].name.casefold()))
    return [fire for fire, _growth_in_acres in growing][:TOP_FIRE_COUNT]


def fast_growing_fires_by_percent(
    fires: list[peri_scribe.kml.fire_data.FireGeometry],
    reference_time: datetime.datetime | None,
) -> list[peri_scribe.kml.fire_data.FireGeometry]:
    """Return the fires that grew most by percent over the fast-growth window.

    A fire qualifies when it grew at least :data:`MINIMUM_FAST_GROWTH_IN_PERCENT`
    percent; a fire without an area at the window's start has no growth percent and is
    skipped. The result is limited to :data:`TOP_FIRE_COUNT` fires.

    Args:
        fires: The fires that can be shown in the KMZ.
        reference_time: The wall-clock time of the KMZ generation, or None when no
            reference time is available.

    Returns:
        The qualifying fires in descending growth order.
    """
    if reference_time is None:
        return []
    growing: list[tuple[peri_scribe.kml.fire_data.FireGeometry, float]] = []
    for fire in fires:
        _growth_in_acres, growth_in_percent = fire_growth(fire, reference_time)
        if (
            growth_in_percent is not None
            and growth_in_percent >= MINIMUM_FAST_GROWTH_IN_PERCENT
        ):
            growing.append((fire, growth_in_percent))
    growing.sort(key=lambda pair: (-pair[1], pair[0].name.casefold()))
    return [fire for fire, _growth_in_percent in growing][:TOP_FIRE_COUNT]


def most_personnel_fires(
    fires: list[peri_scribe.kml.fire_data.FireGeometry],
    reference_time: datetime.datetime | None,
) -> list[peri_scribe.kml.fire_data.FireGeometry]:
    """Return the fires with the most known personnel, updated recently.

    A fire qualifies when its personnel count is known and it was updated within
    :data:`MOST_PERSONNEL_UPDATE_LOOKBACK` of *reference_time*; the result is limited to
    :data:`TOP_FIRE_COUNT` fires.

    Args:
        fires: The fires that can be shown in the KMZ.
        reference_time: The wall-clock time of the KMZ generation, or None when no
            reference time is available.

    Returns:
        The qualifying fires in descending personnel order.
    """
    if reference_time is None:
        return []
    cutoff = reference_time - MOST_PERSONNEL_UPDATE_LOOKBACK
    staffed: list[tuple[peri_scribe.kml.fire_data.FireGeometry, float]] = []
    for fire in fires:
        if fire.description is None:
            continue
        total_personnel = fire.description.total_personnel
        observation_time = fire.description.observation_time
        if total_personnel is None:
            continue
        if observation_time is None:
            continue
        if observation_time < cutoff or observation_time > reference_time:
            continue
        staffed.append((fire, total_personnel))
    staffed.sort(key=lambda pair: (-pair[1], pair[0].name.casefold()))
    return [fire for fire, _total_personnel in staffed][:TOP_FIRE_COUNT]


def top_fires_folder(
    writer: peri_scribe.kml.geometry.KmlWriter,
    fires: list[peri_scribe.kml.fire_data.FireGeometry],
    name: str,
    style_urls: typing.Mapping[str, str],
    ring_style_urls: typing.Mapping[str, str],
    *,
    visible: bool = True,
) -> None:
    """Append a top-fires folder holding each fire's symbolized geometry.

    The folder holds the fires directly, and each fire loads checked or unchecked on its
    own.

    Args:
        writer: The writer to append to.
        fires: The fires to place in the folder.
        name: The folder's name.
        style_urls: The style URL for each template placemark name.
        ring_style_urls: The style URL for each progression ring color, keyed by its
            ``#RRGGBB`` color.
        visible: Whether the folder and its features load visible. A folder that loads
            unchecked keeps its whole tree hidden, so it carries no visible content and
            its radio button in Google Earth loads off instead of being selected.
    """
    with writer.folder(name, visible=visible):
        for fire in fires:
            fire_folder(writer, fire, style_urls, ring_style_urls, visible=visible)
