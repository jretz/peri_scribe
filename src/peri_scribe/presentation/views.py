"""Rank and select the fire views shared by maps and reports."""

from __future__ import annotations

import datetime
import math
import operator
import typing

import peri_scribe.models
import peri_scribe.presentation.fire_data
import peri_scribe.presentation.perimeters
import peri_scribe.presentation.selection
from measurement_units import units


if typing.TYPE_CHECKING:
    import pint


TOP_FIRE_COUNT = 50

NEW_NOTABLE_DISCOVERY_LOOKBACK = datetime.timedelta(days=5)

NEW_NOTABLE_MINIMUM_AREA_ACRES = 100.0

NEW_NOTABLE_SIZE_AREA_ACRES = 1_000.0

NEW_NOTABLE_MINIMUM_BUILDINGS = 100

FAST_GROWTH_LOOKBACK = datetime.timedelta(hours=48)

MINIMUM_FAST_GROWTH = 1_000.0 * units.acres

MINIMUM_FAST_GROWTH_PERCENT = 10.0 * units.percent

MOST_PERSONNEL_UPDATE_LOOKBACK = datetime.timedelta(days=7)

NOTABLE_SCORE_FRACTION = 0.20


def score_fire[Fire: peri_scribe.presentation.fire_data.FireSummary](
    entry: peri_scribe.models.FireScoreEntry,
    fires_by_identifier: typing.Mapping[str, Fire],
    fires_by_name: typing.Mapping[str, Fire],
) -> Fire | None:
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


def top_fires[Fire: peri_scribe.presentation.fire_data.FireSummary](
    fires: list[Fire],
    scores: peri_scribe.models.FireScores,
) -> list[Fire]:
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
            key=lambda entry: (
                -entry.score,
                peri_scribe.presentation.fire_data.fire_name_key(entry),
            ),
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


def score_entry_for_fire(
    fire: peri_scribe.presentation.fire_data.FireSummary,
    scores_by_identifier: typing.Mapping[str, peri_scribe.models.FireScoreEntry],
    scores_by_name: typing.Mapping[str, peri_scribe.models.FireScoreEntry],
) -> peri_scribe.models.FireScoreEntry | None:
    """Return *fire*'s score entry, or None when no entry matches it.

    A fire's identifiers are checked first, so fires that share a name but not an
    identity each resolve to their own entry; a fire whose identifier matches nothing
    falls back to its name.

    Args:
        fire: The fire to resolve.
        scores_by_identifier: Score entries keyed by identifier.
        scores_by_name: Score entries keyed by name.

    Returns:
        The fire's score entry, or None when no entry matches.
    """
    entry = peri_scribe.presentation.selection.first_identifier_match(
        fire.identifiers,
        scores_by_identifier,
    )
    if entry is None:
        entry = scores_by_name.get(fire.name)
    return entry


def score_value_for_fire(
    fire: peri_scribe.presentation.fire_data.FireSummary,
    scores_by_identifier: typing.Mapping[str, peri_scribe.models.FireScoreEntry],
    scores_by_name: typing.Mapping[str, peri_scribe.models.FireScoreEntry],
) -> int | None:
    """Return *fire*'s score, or None when no entry matches it.

    Args:
        fire: The fire to score.
        scores_by_identifier: Score entries keyed by identifier.
        scores_by_name: Score entries keyed by name.

    Returns:
        The fire's score, or None when no entry matches.
    """
    entry = score_entry_for_fire(fire, scores_by_identifier, scores_by_name)
    return None if entry is None else entry.score


def notable_score_threshold(
    fires: typing.Sequence[peri_scribe.presentation.fire_data.FireSummary],
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


def new_notable_signals_qualify(entry: peri_scribe.models.FireScoreEntry) -> bool:
    """Return whether a newly discovered fire's signals make it notable.

    A fire qualifies by signals only once it presents at least
    :data:`NEW_NOTABLE_MINIMUM_AREA_ACRES`, and then by size, evacuation overlap, or
    nearby buildings. Below that minimum nothing but the score qualifies it.

    Args:
        entry: The fire's score entry, carrying its area and external signals.

    Returns:
        Whether the fire's signals qualify it for the view.
    """
    area = entry.area
    if area is None or area < NEW_NOTABLE_MINIMUM_AREA_ACRES:
        return False
    if area >= NEW_NOTABLE_SIZE_AREA_ACRES:
        return True
    if entry.evacuation_overlap:
        return True
    return (
        entry.building_count is not None
        and entry.building_count >= NEW_NOTABLE_MINIMUM_BUILDINGS
    )


def new_notable_fires[Fire: peri_scribe.presentation.fire_data.FireSummary](
    fires: list[Fire],
    scores: peri_scribe.models.FireScores,
    reference_time: datetime.datetime | None,
) -> list[Fire]:
    """Return the newly discovered fires that are notable.

    A fire qualifies when it was discovered within
    :data:`NEW_NOTABLE_DISCOVERY_LOOKBACK` of *reference_time* and either scores among
    the top active fires, or presents at least :data:`NEW_NOTABLE_MINIMUM_AREA_ACRES`
    and clears one of the notable-signal gates: at least
    :data:`NEW_NOTABLE_SIZE_AREA_ACRES`, an evacuation-zone overlap, or at least
    :data:`NEW_NOTABLE_MINIMUM_BUILDINGS` within a mile.

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
    scored: list[tuple[Fire, int]] = []
    for fire in fires:
        discovery_time = (
            fire.description.discovery_time if fire.description is not None else None
        )
        if discovery_time is None:
            continue
        if discovery_time < cutoff or discovery_time > reference_time:
            continue
        entry = score_entry_for_fire(fire, scores_by_identifier, scores_by_name)
        if entry is None:
            continue
        if entry.score >= threshold or new_notable_signals_qualify(entry):
            scored.append((fire, entry.score))
    scored.sort(key=peri_scribe.presentation.fire_data.descending_value_name_key)
    return [fire for fire, _score in scored]


def type_one_fires[Fire: peri_scribe.presentation.fire_data.FireSummary](
    fires: list[Fire],
) -> list[Fire]:
    """Return the active fires marked as Type 1 Incidents, sorted by name.

    A fire qualifies when it is active and its latest point-history row marks it a Type
    1 Incident, the concept scoring uses, so a fire downgraded from Type 1 leaves the
    view. The fires are ordered by their case-folded names, like the top fires by name.

    Args:
        fires: The fires that can be shown in the KMZ.

    Returns:
        The qualifying fires in name order.
    """
    qualifying = [
        fire
        for fire in fires
        if fire.status is peri_scribe.models.FireStatus.ACTIVE and fire.type_one
    ]
    qualifying.sort(key=peri_scribe.presentation.fire_data.fire_name_key)
    return qualifying


def fire_growth(
    fire: peri_scribe.presentation.fire_data.FireSummary,
    reference_time: datetime.datetime,
) -> tuple[pint.Quantity[float] | None, pint.Quantity[float] | None]:
    """Return *fire*'s growth over the fast-growth window.

    The fire's latest area known at the reference time is compared with its area at the
    start of the window, measured from its perimeters. A fire first observed inside the
    window has no area at the window's start, so it is treated as having grown from zero
    acres: its whole latest area counts as growth, and its growth percent is unknown
    because a zero baseline has no percentage.

    Args:
        fire: The fire to measure.
        reference_time: The wall-clock time of the KMZ generation.

    Returns:
        The growth and growth percent, or None for each when it cannot be measured.
    """
    timed_perimeters: list[
        tuple[datetime.datetime, peri_scribe.presentation.perimeters.Perimeter],
    ] = []
    for perimeter in fire.perimeters:
        observation_time = perimeter.observation_time
        if observation_time is not None and observation_time <= reference_time:
            timed_perimeters.append((observation_time, perimeter))
    if not timed_perimeters:
        return None, None
    timed_perimeters.sort(key=operator.itemgetter(0))
    latest_perimeter = timed_perimeters[-1][1]
    latest_area = latest_perimeter.measured_area
    cutoff = reference_time - FAST_GROWTH_LOOKBACK
    baseline_perimeter: peri_scribe.presentation.perimeters.Perimeter | None = None
    for observation_time, perimeter in reversed(timed_perimeters):
        if observation_time <= cutoff:
            baseline_perimeter = perimeter
            break
    if baseline_perimeter is None:
        return latest_area, None
    baseline_area = baseline_perimeter.measured_area
    growth = latest_area - baseline_area
    growth_percent = (
        (growth / baseline_area) * 100.0 * units.percent
        if baseline_area.magnitude > 0
        else None
    )
    return growth, growth_percent


def fast_growing_fires_by_acres[Fire: peri_scribe.presentation.fire_data.FireSummary](
    fires: list[Fire],
    reference_time: datetime.datetime | None,
) -> list[Fire]:
    """Return the fires that grew most in area over the fast-growth window.

    A fire qualifies when it grew at least :data:`MINIMUM_FAST_GROWTH`; a fire first
    observed inside the window is treated as having grown from zero acres, so its whole
    latest area counts. The result is limited to :data:`TOP_FIRE_COUNT` fires.

    Args:
        fires: The fires that can be shown in the KMZ.
        reference_time: The wall-clock time of the KMZ generation, or None when no
            reference time is available.

    Returns:
        The qualifying fires in descending growth order.
    """
    if reference_time is None:
        return []
    growing: list[tuple[Fire, float]] = []
    for fire in fires:
        growth, _growth_percent = fire_growth(fire, reference_time)
        if growth is not None and growth >= MINIMUM_FAST_GROWTH:
            growing.append((fire, growth.m_as("acres")))
    growing.sort(key=peri_scribe.presentation.fire_data.descending_value_name_key)
    return [fire for fire, _growth in growing][:TOP_FIRE_COUNT]


def fast_growing_fires_by_percent[Fire: peri_scribe.presentation.fire_data.FireSummary](
    fires: list[Fire],
    reference_time: datetime.datetime | None,
) -> list[Fire]:
    """Return the fires that grew most by percent over the fast-growth window.

    A fire qualifies when it grew at least :data:`MINIMUM_FAST_GROWTH_PERCENT` percent;
    a fire without an area at the window's start has no growth percent and is skipped.
    The result is limited to :data:`TOP_FIRE_COUNT` fires.

    Args:
        fires: The fires that can be shown in the KMZ.
        reference_time: The wall-clock time of the KMZ generation, or None when no
            reference time is available.

    Returns:
        The qualifying fires in descending growth order.
    """
    if reference_time is None:
        return []
    growing: list[tuple[Fire, float]] = []
    for fire in fires:
        _, growth_percent = fire_growth(fire, reference_time)
        if growth_percent is not None and growth_percent >= MINIMUM_FAST_GROWTH_PERCENT:
            growing.append((fire, growth_percent.m_as("percent")))
    growing.sort(key=peri_scribe.presentation.fire_data.descending_value_name_key)
    return [fire for fire, _ in growing][:TOP_FIRE_COUNT]


def most_personnel_fires[Fire: peri_scribe.presentation.fire_data.FireSummary](
    fires: list[Fire],
    reference_time: datetime.datetime | None,
) -> list[Fire]:
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
    staffed: list[tuple[Fire, float]] = []
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
    staffed.sort(key=peri_scribe.presentation.fire_data.descending_value_name_key)
    return [fire for fire, _total_personnel in staffed][:TOP_FIRE_COUNT]
