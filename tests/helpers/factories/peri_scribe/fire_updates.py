"""Mapped fires distinguish logged geometry area from incident-reported size."""

import datetime

import shapely

import peri_scribe.models
import peri_scribe.presentation.descriptions
import peri_scribe.presentation.fire_data
import peri_scribe.presentation.perimeters
from measurement_units import units


def mapped_fire() -> peri_scribe.presentation.fire_data.FireSummary:
    """Provide an interesting fire with stored acreage and conflicting reported size.

    Returns:
        A Type 1 fire with a single dated perimeter near Soledad, California.
    """
    return peri_scribe.presentation.fire_data.FireSummary(
        name="Timber",
        identifiers=frozenset({"2026-calpf-002271"}),
        status=peri_scribe.models.FireStatus.ACTIVE,
        point=None,
        type_one=True,
        perimeters=(
            peri_scribe.presentation.perimeters.Perimeter(
                geometry=shapely.box(-121.5, 36.2, -121.4, 36.3),
                observation_time=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
                area=1234.5 * units.acres,
            ),
        ),
        description=peri_scribe.presentation.descriptions.FireDescription(
            area=9999.0 * units.acres,
        ),
    )
