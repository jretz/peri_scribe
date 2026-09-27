"""Exercise every score tier without reproducing its expected points in Python."""

import itertools
import json

import geopandas

import peri_scribe.fires.scoring
from measurement_units import units


type ScoreInput = tuple[int, int, int, int, int, int]


def score_cases() -> list[ScoreInput]:
    """Cover threshold equality and interactions with all other saturated signals.

    Returns:
        Acreages, building count, evacuation flag, and official importance points.
    """
    thresholds = (
        (1_000, 10_000, 25_000, 50_000, 100_000),
        (5_000, 10_000, 25_000, 50_000),
        (100, 1_000, 5_000),
        (5, 50, 250, 1_000),
    )
    result: set[ScoreInput] = set()
    for position, boundaries in enumerate(thresholds):
        for threshold, offset, saturated, evacuation, importance in itertools.product(
            (0, *boundaries),
            (-1, 0, 1),
            (False, True),
            (0, 1),
            range(4),
        ):
            values = [tiers[-1] if saturated else 0 for tiers in thresholds]
            values[position] = max(0, threshold + offset)
            size, growth, first_mapping, buildings = values
            result.add((size, growth, first_mapping, buildings, evacuation, importance))
    return sorted(result)


def implementation_score(case: ScoreInput) -> int:
    """Supply exact policy values through the scoring module's public entry point.

    Args:
        case: Size, growth, first mapping, buildings, evacuation, and importance.

    Returns:
        The implementation's complete weighted score.
    """
    size, growth, first_mapping, buildings, evacuation, importance = case
    levels = (None, "Type 3 Incident", "Type 2 Incident", "Type 1 Incident")
    record = peri_scribe.fires.scoring.FireRecords(
        name="Formal policy",
        identifier="formal-policy",
        perimeters=geopandas.GeoDataFrame(),
        points=geopandas.GeoDataFrame({
            "source_attributes": [
                json.dumps({"IncidentComplexityLevel": levels[importance]}),
            ],
        }),
    )
    metrics = peri_scribe.fires.scoring.PerimeterMetrics(
        area=float(size) * units.acres,
        growth=float(growth) * units.acres,
        first_mapping=float(first_mapping) * units.acres,
        geometry=None,
    )
    return peri_scribe.fires.scoring.fire_score_for(
        record,
        metrics,
        building_count=buildings,
        evacuation_overlap=bool(evacuation),
    ).total
