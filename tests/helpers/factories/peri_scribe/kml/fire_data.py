"""Small ordered ring sequences requiring exact cumulative area measurement."""

import peri_scribe.perimeters.progression
import tests.helpers.factories.geometry


def fallback_rings() -> tuple[peri_scribe.perimeters.progression.Ring, ...]:
    """Return overlapping geometries without trusted stored added areas.

    Returns:
        Two ordered rings whose cumulative areas differ from their individual areas.
    """
    return tuple(
        peri_scribe.perimeters.progression.Ring(
            geometry=tests.helpers.factories.geometry.square(width),
            observation_time=None,
        )
        for width in (1, 2)
    )
