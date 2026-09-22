"""Build inputs for builder tests."""

from __future__ import annotations

import datetime

import shapely.geometry

import peri_scribe.kml.fire_data
import peri_scribe.models
import peri_scribe.presentation.descriptions
import peri_scribe.presentation.perimeters
import tests.helpers.factories.geometry


SCENARIO_TIME = datetime.datetime(2026, 8, 20, 12, 0, tzinfo=datetime.UTC)


def new_folder_scenario() -> tuple[
    list[peri_scribe.kml.fire_data.FireGeometry],
    peri_scribe.models.FireScores,
]:
    """Return one fire that qualifies for every new top-level folder.

    Returns:
        The fire and its score.
    """
    fire = peri_scribe.kml.fire_data.FireGeometry(
        name="Alpha",
        status=peri_scribe.models.FireStatus.ACTIVE,
        point=shapely.geometry.Point(0.0, 0.0),
        perimeters=(
            peri_scribe.presentation.perimeters.Perimeter(
                geometry=tests.helpers.factories.geometry.square(0.02),
                observation_time=SCENARIO_TIME - datetime.timedelta(hours=48),
            ),
            peri_scribe.presentation.perimeters.Perimeter(
                geometry=tests.helpers.factories.geometry.square(0.03),
                observation_time=SCENARIO_TIME,
            ),
        ),
        description=peri_scribe.presentation.descriptions.FireDescription(
            discovery_time=SCENARIO_TIME - datetime.timedelta(days=1),
            observation_time=SCENARIO_TIME,
            total_personnel=50.0,
        ),
        type_one=True,
    )
    scores = peri_scribe.models.FireScores(
        version="test",
        fires=[
            peri_scribe.models.FireScoreEntry(
                name="Alpha",
                score=10,
                explanation="No notable size, growth, threat, or "
                "official-importance signals.",
            ),
        ],
    )
    return [fire], scores


NEW_FOLDER_NAMES = [
    "New, Notable Fires",
    "Type 1 Fires",
    "Fast Growing Fires (acres)",
    "Fast Growing Fires (%)",
    "Fires with Most Personnel",
]
