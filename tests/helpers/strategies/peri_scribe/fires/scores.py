"""Generate scores examples with constrained domains."""

from __future__ import annotations

import hypothesis.strategies

import tests.helpers.factories.peri_scribe.fires.scores


@hypothesis.strategies.composite
def score_histories(
    draw: hypothesis.strategies.DrawFn,
) -> list[tests.helpers.factories.peri_scribe.fires.scores.ScoreObservation]:
    """Interleave fires with missing observations and disagreeing source measurements.

    Args:
        draw: The current example's strategy sampler.

    Returns:
        Measurements with unique times per fire, including possible undated records.
    """
    area = hypothesis.strategies.one_of(
        hypothesis.strategies.none(),
        hypothesis.strategies.integers(0, 10_000),
    )
    growth = hypothesis.strategies.one_of(
        hypothesis.strategies.none(),
        hypothesis.strategies.integers(-1000, 10_000),
    )
    rows = draw(
        hypothesis.strategies.dictionaries(
            hypothesis.strategies.tuples(
                hypothesis.strategies.sampled_from(["a", "b", "c"]),
                hypothesis.strategies.one_of(
                    hypothesis.strategies.none(),
                    hypothesis.strategies.integers(-5, 5),
                ),
            ),
            hypothesis.strategies.tuples(area, growth, area, growth),
            max_size=12,
        ),
    )
    return [
        tests.helpers.factories.peri_scribe.fires.scores.ScoreObservation(
            key=key,
            hour=hour,
            reported_area=reported_area,
            reported_growth=reported_growth,
            calculated_area=calculated_area,
            calculated_growth=calculated_growth,
        )
        for (key, hour), (
            reported_area,
            reported_growth,
            calculated_area,
            calculated_growth,
        ) in rows.items()
    ]
