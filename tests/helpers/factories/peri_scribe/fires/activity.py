"""Construct independent acreage timelines for activity-policy tests."""

import datetime

import peri_scribe.fires.activity
from measurement_units import units


REFERENCE_TIME = datetime.datetime(2026, 10, 22, 12, tzinfo=datetime.UTC)


def observations(
    samples: list[tuple[float, float]],
) -> tuple[peri_scribe.fires.activity.AreaObservation, ...]:
    """Convert day offsets and acre magnitudes into dated quantity observations.

    Args:
        samples: Day offsets from REFERENCE_TIME and corresponding acres.

    Returns:
        Observations in the supplied source order.
    """
    return tuple(
        peri_scribe.fires.activity.AreaObservation(
            time=REFERENCE_TIME + datetime.timedelta(days=day),
            area=acres * units.acres,
        )
        for day, acres in samples
    )
