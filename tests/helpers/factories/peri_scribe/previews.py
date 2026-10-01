"""Small geographic histories for raster and snapshot preview tests."""

import datetime

import shapely

import peri_scribe.models
import peri_scribe.perimeters.progression
import peri_scribe.presentation.fire_data
import peri_scribe.presentation.perimeters
from measurement_units import units


def fire() -> peri_scribe.presentation.fire_data.FireSummary:
    """Supply nested observations with visible growth between the three outlines.

    Returns:
        A named fire with a stable identifier and three chronological growth rings.
    """
    geometries = [
        shapely.box(-121.01 - step, 36.0 - step, -121.0 + step, 36.006 + step)
        for step in (0, 0.002, 0.004)
    ]
    times = [
        datetime.datetime(2026, 9, day, tzinfo=datetime.UTC) for day in (20, 21, 22)
    ]
    return peri_scribe.presentation.fire_data.FireSummary(
        name="Timber",
        status=peri_scribe.models.FireStatus.ACTIVE,
        point=None,
        identifiers=frozenset({"2026-catst-000001", "alias"}),
        component_id="timber-component",
        perimeters=tuple(
            peri_scribe.presentation.perimeters.Perimeter(
                geometry=geometry,
                observation_time=time,
                area=(index + 1) * units.acres,
            )
            for index, (geometry, time) in enumerate(
                zip(geometries, times, strict=True),
            )
        ),
        progression_rings=tuple(
            peri_scribe.perimeters.progression.Ring(
                geometry=(
                    geometry
                    if index == 0
                    else geometry.difference(geometries[index - 1])
                ),
                observation_time=time,
                area=1 * units.acres,
            )
            for index, (geometry, time) in enumerate(
                zip(geometries, times, strict=True),
            )
        ),
    )
