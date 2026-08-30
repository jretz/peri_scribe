"""Scoring points and the fire score model."""

from __future__ import annotations

import abc
import dataclasses
import json
import typing

import peri_scribe.models


if typing.TYPE_CHECKING:
    import geopandas
    import shapely


FIRE_SCORES_VERSION = "2026-08-29"


@dataclasses.dataclass(frozen=True, kw_only=True)
class SignalTier(abc.ABC):
    """A scoring tier: the threshold a signal must meet and its tier points.

    Concrete tier kinds inherit and add a description that phrases the threshold in
    English.
    """

    threshold: float
    score: int

    @property
    @abc.abstractmethod
    def description(self) -> str:
        """Return the tier's English description."""


@dataclasses.dataclass(frozen=True, kw_only=True)
class SizeTier(SignalTier):
    """A tier on a fire's reported size."""

    @property
    def description(self) -> str:
        """Return the tier's English description."""
        return f"over {self.threshold:,.0f} acres"


@dataclasses.dataclass(frozen=True, kw_only=True)
class GrowthTier(SignalTier):
    """A tier on a fire's largest single growth step."""

    @property
    def description(self) -> str:
        """Return the tier's English description."""
        return f"a single growth step over {self.threshold:,.0f} acres"


@dataclasses.dataclass(frozen=True, kw_only=True)
class FirstMappingTier(SignalTier):
    """A tier on a fire's size when first mapped."""

    @property
    def description(self) -> str:
        """Return the tier's English description."""
        return f"already over {self.threshold:,.0f} acres when first mapped"


@dataclasses.dataclass(frozen=True, kw_only=True)
class BuildingCountTier(SignalTier):
    """A tier on the structures within a mile of a fire."""

    @property
    def description(self) -> str:
        """Return the tier's English description."""
        return f"over {self.threshold:,.0f} structures within a mile"


SIZE_TIERS = (
    SizeTier(threshold=100_000.0, score=5),
    SizeTier(threshold=50_000.0, score=4),
    SizeTier(threshold=25_000.0, score=3),
    SizeTier(threshold=10_000.0, score=2),
    SizeTier(threshold=1_000.0, score=1),
)


GROWTH_TIERS = (
    GrowthTier(threshold=50_000.0, score=4),
    GrowthTier(threshold=25_000.0, score=3),
    GrowthTier(threshold=10_000.0, score=2),
    GrowthTier(threshold=5_000.0, score=1),
)


FIRST_MAPPING_TIERS = (
    FirstMappingTier(threshold=5_000.0, score=3),
    FirstMappingTier(threshold=1_000.0, score=2),
    FirstMappingTier(threshold=100.0, score=1),
)


BUILDING_COUNT_TIERS = (
    BuildingCountTier(threshold=1_000.0, score=4),
    BuildingCountTier(threshold=250.0, score=3),
    BuildingCountTier(threshold=50.0, score=2),
    BuildingCountTier(threshold=5.0, score=1),
)


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
    tiers: tuple[SignalTier, ...],
) -> int:
    """Return the points for the first tier *value* meets, or zero.

    Args:
        value: The measured value, or None when unknown.
        tiers: ``SignalTier`` instances ordered from largest threshold down.

    Returns:
        The points of the first tier whose threshold *value* meets, or 0.
    """
    if value is None:
        return 0
    for tier in tiers:
        if value >= tier.threshold:
            return tier.score
    return 0


def signal_description(
    points: int,
    weight: int,
    tiers: tuple[SignalTier, ...],
) -> str | None:
    """Return the human description of a signal's tier, or None for no points.

    Args:
        points: The signal's weighted points.
        weight: The weight the signal's tier points were multiplied by.
        tiers: The signal's tiers, ordered from largest threshold down.

    Returns:
        The description for the signal's tier, or None when the signal
        contributed no points or no tier matches.
    """
    if points == 0:
        return None
    tier_score = points // weight
    for tier in tiers:
        if tier.score == tier_score:
            return tier.description
    return None


def importance_description(points: int) -> str | None:
    """Return the human description of the importance tier, or None for no points.

    Args:
        points: The signal's weighted points.

    Returns:
        The description for the importance level, or None when the signal
        contributed no points.
    """
    if points == 0:
        return None
    return IMPORTANCE_DESCRIPTIONS[points // IMPORTANCE_WEIGHT]


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
        signal_description(fire_score.size_points, SIZE_WEIGHT, SIZE_TIERS),
        signal_description(fire_score.growth_points, GROWTH_WEIGHT, GROWTH_TIERS),
        signal_description(
            fire_score.first_mapping_points,
            FIRST_MAPPING_WEIGHT,
            FIRST_MAPPING_TIERS,
        ),
        signal_description(
            fire_score.building_points,
            BUILDINGS_WEIGHT,
            BUILDING_COUNT_TIERS,
        ),
        "overlap with an evacuation zone" if fire_score.evacuation_points else None,
        importance_description(fire_score.importance_points),
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
