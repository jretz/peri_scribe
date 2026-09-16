"""Generate folders examples with constrained domains."""

from __future__ import annotations

import datetime

import hypothesis.strategies

import peri_scribe.kml.perimeters
import tests.helpers.factories.geometry
import tests.helpers.factories.peri_scribe.kml.folders
from peri_scribe.units import units


@hypothesis.strategies.composite
def growth_histories(
    draw: hypothesis.strategies.DrawFn,
) -> tuple[peri_scribe.kml.perimeters.Perimeter, ...]:
    """Mix dated, undated, and future measurements around the growth window.

    Args:
        draw: The current example's strategy sampler.

    Returns:
        Unordered perimeters with unique dated observations and varied area units.
    """
    measurements = draw(
        hypothesis.strategies.dictionaries(
            hypothesis.strategies.one_of(
                hypothesis.strategies.none(),
                hypothesis.strategies.integers(-96, 48),
            ),
            hypothesis.strategies.integers(0, 10_000),
            max_size=12,
        ),
    )
    area_unit = draw(
        hypothesis.strategies.sampled_from(["acres", "hectares", "meters ** 2"]),
    )
    return tuple(
        peri_scribe.kml.perimeters.Perimeter(
            geometry=tests.helpers.factories.geometry.square(0.01),
            observation_time=None
            if hour is None
            else tests.helpers.factories.peri_scribe.kml.folders.REFERENCE_TIME
            + datetime.timedelta(hours=hour),
            area=(area * units.acres).to(area_unit),
        )
        for hour, area in measurements.items()
    )
