"""Scoring points and the fire score model."""

from __future__ import annotations

import dataclasses
import json
import typing

import peri_scribe.models


if typing.TYPE_CHECKING:
    import geopandas
    import shapely


FIRE_SCORES_VERSION = "2026-08-29"


SIZE_TIERS = (
    (100_000.0, 5),
    (50_000.0, 4),
    (25_000.0, 3),
    (10_000.0, 2),
    (1_000.0, 1),
)


GROWTH_TIERS = (
    (50_000.0, 4),
    (25_000.0, 3),
    (10_000.0, 2),
    (5_000.0, 1),
)


FIRST_MAPPING_TIERS = (
    (5_000.0, 3),
    (1_000.0, 2),
    (100.0, 1),
)


BUILDING_COUNT_TIERS = (
    (1_000.0, 4),
    (250.0, 3),
    (50.0, 2),
    (5.0, 1),
)


SIZE_DESCRIPTIONS = {
    5: "over 100,000 acres",
    4: "over 50,000 acres",
    3: "over 25,000 acres",
    2: "over 10,000 acres",
    1: "over 1,000 acres",
}


GROWTH_DESCRIPTIONS = {
    4: "a single growth step over 50,000 acres",
    3: "a single growth step over 25,000 acres",
    2: "a single growth step over 10,000 acres",
    1: "a single growth step over 5,000 acres",
}


FIRST_MAPPING_DESCRIPTIONS = {
    3: "already over 5,000 acres when first mapped",
    2: "already over 1,000 acres when first mapped",
    1: "already over 100 acres when first mapped",
}


BUILDING_COUNT_DESCRIPTIONS = {
    4: "over 1,000 structures within a mile",
    3: "over 250 structures within a mile",
    2: "over 50 structures within a mile",
    1: "over 5 structures within a mile",
}


EVACUATION_POINTS = 3


IMPORTANCE_POINTS_BY_LEVEL = {
    "Type 1 Incident": 3,
    "Type 2 Incident": 2,
    "Type 3 Incident": 1,
}


IMPORTANCE_DESCRIPTIONS = {
    3: "a Type 1 Incident",
    2: "a Type 2 Incident",
    1: "a Type 3 Incident",
}


SIZE_WEIGHT = 27


GROWTH_WEIGHT = 15


FIRST_MAPPING_WEIGHT = 11


BUILDINGS_WEIGHT = 4


EVACUATION_WEIGHT = 11


IMPORTANCE_WEIGHT = 120


def tiered_points(
    value: float | None,
    tiers: tuple[tuple[float, int], ...],
) -> int:
    """Return the points for the first tier *value* meets, or zero.

    Args:
        value: The measured value, or None when unknown.
        tiers: ``(threshold, points)`` pairs ordered from largest threshold down.

    Returns:
        The points of the first tier whose threshold *value* meets, or 0.
    """
    if value is None:
        return 0
    for threshold, points in tiers:
        if value >= threshold:
            return points
    return 0


def signal_description(
    points: int,
    weight: int,
    descriptions: dict[int, str],
) -> str | None:
    """Return the human description of a signal's tier, or None for no points.

    Args:
        points: The signal's weighted points.
        weight: The weight the signal's tier points were multiplied by.
        descriptions: The tier-points-to-description map.

    Returns:
        The description for the signal's tier, or None when the signal
        contributed no points.
    """
    if points == 0:
        return None
    return descriptions[points // weight]


def importance_points(complexity_level: str | None) -> int:
    """Return the official-importance points for a complexity level.

    Args:
        complexity_level: The incident complexity level, or None.

    Returns:
        The points for the level, or 0 when the level is unrecognized.
    """
    return IMPORTANCE_POINTS_BY_LEVEL.get(complexity_level, 0)


def complexity_level(source_attributes_json: object) -> str | None:
    """Return the incident complexity level from a source-attributes JSON string.

    Args:
        source_attributes_json: A row's serialized source attributes.

    Returns:
        The incident complexity level, or None when it is absent or unreadable.
    """
    if source_attributes_json is None:
        return None
    try:
        attributes = json.loads(str(source_attributes_json))
    except json.JSONDecodeError, TypeError:
        return None
    if not isinstance(attributes, dict):
        return None
    value = attributes.get("IncidentComplexityLevel")
    return str(value) if value is not None else None


@dataclasses.dataclass(frozen=True, kw_only=True)
class PerimeterMetrics:
    """The size and growth measurements derived from a fire's perimeters."""

    area_acres: float | None
    growth_acres: float | None
    first_mapping_acres: float | None
    geometry: shapely.Geometry | None


def fire_importance_points(points: geopandas.GeoDataFrame) -> int:
    """Return the highest official-importance points among a fire's observations.

    Args:
        points: The fire's point-history rows.

    Returns:
        The highest importance points across the rows, or 0 when there are none.
    """
    if points.empty:
        return 0
    levels = (
        complexity_level(attributes) for attributes in points["source_attributes"]
    )
    return max((importance_points(level) for level in levels), default=0)


@dataclasses.dataclass(frozen=True, kw_only=True)
class FireRecords:
    """A fire's identity and the history rows that describe it."""

    name: str
    identifier: str | None
    perimeters: geopandas.GeoDataFrame
    points: geopandas.GeoDataFrame


@dataclasses.dataclass(frozen=True, kw_only=True)
class FireScore:
    """A fire's current score and the points each signal contributed."""

    name: str
    identifier: str | None
    size_points: int
    growth_points: int
    first_mapping_points: int
    building_points: int
    evacuation_points: int
    importance_points: int

    @property
    def total(self) -> int:
        """Return the fire's total score."""
        return (
            self.size_points
            + self.growth_points
            + self.first_mapping_points
            + self.building_points
            + self.evacuation_points
            + self.importance_points
        )


def fire_score_for(
    record: FireRecords,
    metrics: PerimeterMetrics,
    *,
    building_count: int,
    evacuation_overlap: bool,
) -> FireScore:
    """Return the score for one fire from its history and external signals.

    Args:
        record: The fire's identity and history rows.
        metrics: The fire's size and growth measurements.
        building_count: The number of buildings within a mile of the fire.
        evacuation_overlap: Whether the fire overlaps an evacuation zone.

    Returns:
        The fire's score.
    """
    return FireScore(
        name=record.name,
        identifier=record.identifier,
        size_points=SIZE_WEIGHT * tiered_points(metrics.area_acres, SIZE_TIERS),
        growth_points=GROWTH_WEIGHT * tiered_points(metrics.growth_acres, GROWTH_TIERS),
        first_mapping_points=FIRST_MAPPING_WEIGHT
        * tiered_points(
            metrics.first_mapping_acres,
            FIRST_MAPPING_TIERS,
        ),
        building_points=BUILDINGS_WEIGHT
        * tiered_points(building_count, BUILDING_COUNT_TIERS),
        evacuation_points=EVACUATION_WEIGHT
        * (EVACUATION_POINTS if evacuation_overlap else 0),
        importance_points=IMPORTANCE_WEIGHT * fire_importance_points(record.points),
    )


def score_explanation(fire_score: FireScore) -> str:
    """Return a short English explanation of why a fire has its score.

    Each signal that contributed points is described in one phrase, in the order the
    components are stored; signals that contributed nothing are omitted. A fire whose
    signals all scored zero gets a sentence saying so.

    Args:
        fire_score: The fire's score.

    Returns:
        The explanation sentence.
    """
    phrases = [
        signal_description(fire_score.size_points, SIZE_WEIGHT, SIZE_DESCRIPTIONS),
        signal_description(
            fire_score.growth_points,
            GROWTH_WEIGHT,
            GROWTH_DESCRIPTIONS,
        ),
        signal_description(
            fire_score.first_mapping_points,
            FIRST_MAPPING_WEIGHT,
            FIRST_MAPPING_DESCRIPTIONS,
        ),
        signal_description(
            fire_score.building_points,
            BUILDINGS_WEIGHT,
            BUILDING_COUNT_DESCRIPTIONS,
        ),
        "overlap with an evacuation zone" if fire_score.evacuation_points else None,
        signal_description(
            fire_score.importance_points,
            IMPORTANCE_WEIGHT,
            IMPORTANCE_DESCRIPTIONS,
        ),
    ]
    present = [phrase for phrase in phrases if phrase is not None]
    if not present:
        return "No notable size, growth, threat, or official-importance signals."
    if len(present) == 1:
        sentence = present[0]
    else:
        sentence = ", ".join(present[:-1]) + ", and " + present[-1]
    return sentence[0].upper() + sentence[1:] + "."


def score_entry(
    fire_score: FireScore,
) -> peri_scribe.models.FireScoreEntry:
    """Return the persisted score entry for a fire.

    Args:
        fire_score: The fire's current score.

    Returns:
        The entry holding the fire's score, current components, and an explanation of
        the score.
    """
    return peri_scribe.models.FireScoreEntry(
        name=fire_score.name,
        identifier=fire_score.identifier,
        score=fire_score.total,
        components=peri_scribe.models.FireScoreComponents(
            size=fire_score.size_points,
            growth=fire_score.growth_points,
            first_mapping=fire_score.first_mapping_points,
            buildings=fire_score.building_points,
            evacuation=fire_score.evacuation_points,
            importance=fire_score.importance_points,
        ),
        explanation=score_explanation(fire_score),
    )


def fire_scores_document(
    entries: list[peri_scribe.models.FireScoreEntry],
) -> peri_scribe.models.FireScores:
    """Wrap *entries* in the current fire-scores document.

    Args:
        entries: The fire score entries, ordered most-to-least interesting.

    Returns:
        The validated fire-scores document.
    """
    return peri_scribe.models.FireScores(
        version=FIRE_SCORES_VERSION,
        fires=entries,
    )
