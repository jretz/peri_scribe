"""Generate colormap examples with constrained domains."""

from __future__ import annotations

import datetime
import typing

import hypothesis.strategies

import tests.helpers.factories.peri_scribe.kml.colormap


if typing.TYPE_CHECKING:
    import peri_scribe.perimeters.progression


@hypothesis.strategies.composite
def ring_histories(
    draw: hypothesis.strategies.DrawFn,
) -> list[peri_scribe.perimeters.progression.Ring]:
    """Vary growth amounts and observation spacing, including undated rings.

    Args:
        draw: The current example's strategy sampler.

    Returns:
        Rings in chronological order, with whole-second times and positive areas.
    """
    observations = draw(
        hypothesis.strategies.lists(
            hypothesis.strategies.tuples(
                hypothesis.strategies.one_of(
                    hypothesis.strategies.none(),
                    hypothesis.strategies.integers(0, 30 * 24 * 60 * 60),
                ),
                hypothesis.strategies.integers(1, 1000),
            ),
            max_size=20,
        ),
    )
    base = datetime.datetime(2026, 8, 1, tzinfo=datetime.UTC)
    return [
        tests.helpers.factories.peri_scribe.kml.colormap.ring(
            1.0,
            None if seconds is None else base + datetime.timedelta(seconds=seconds),
            area=float(area),
        )
        for seconds, area in sorted(
            observations,
            key=lambda item: -1 if item[0] is None else item[0],
        )
    ]
