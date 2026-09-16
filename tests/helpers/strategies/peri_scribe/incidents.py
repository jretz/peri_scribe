"""Generate incidents examples with constrained domains."""

from __future__ import annotations

import hypothesis.strategies

import peri_scribe.incidents
import tests.helpers.factories.peri_scribe.incidents


@hypothesis.strategies.composite
def update_histories(
    draw: hypothesis.strategies.DrawFn,
) -> list[peri_scribe.incidents.IncidentUpdate]:
    """Mix simultaneous feeds, partial measurements, and old or new report evidence.

    Args:
        draw: The current example's strategy sampler.

    Returns:
        Updates with unique snapshot serials and report times no later than observation.
    """
    updates = []
    for serial in range(draw(hypothesis.strategies.integers(0, 15))):
        day = draw(hypothesis.strategies.integers(1, 6))
        report_day = draw(
            hypothesis.strategies.one_of(
                hypothesis.strategies.none(),
                hypothesis.strategies.integers(1, day),
            ),
        )
        updates.append(
            peri_scribe.incidents.IncidentUpdate(
                observation_time=tests.helpers.factories.peri_scribe.incidents.time(
                    day,
                ),
                report_time=None
                if report_day is None
                else tests.helpers.factories.peri_scribe.incidents.time(report_day),
                confirmed=report_day is not None
                and draw(hypothesis.strategies.booleans()),
                source=draw(
                    hypothesis.strategies.sampled_from(
                        ("wfigs_location", "wfigs_perimeter"),
                    ),
                ),
                source_file=f"{serial}.gpkg",
                serial=serial,
                measurements=draw(
                    hypothesis.strategies.dictionaries(
                        hypothesis.strategies.sampled_from(
                            peri_scribe.incidents.VALUE_COLUMNS,
                        ),
                        hypothesis.strategies.integers(0, 100).map(float),
                    ),
                ),
            ),
        )
    return updates
