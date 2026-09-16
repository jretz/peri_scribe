"""Provide data builders and stand-ins for incidents tests."""

from __future__ import annotations

import datetime

import hypothesis.strategies

import peri_scribe.incidents


def time(day: int) -> datetime.datetime:
    """Keep incident-reconciliation scenarios on a comparable UTC clock.

    Args:
        day: The calendar day in September 2026.

    Returns:
        Midnight UTC on that day.
    """
    return datetime.datetime(2026, 9, day, tzinfo=datetime.UTC)


def update(
    day: int,
    value: float,
    *,
    confirmed: bool = False,
) -> peri_scribe.incidents.IncidentUpdate:
    """Make reporting evidence explicit without repeating unrelated source fields.

    Args:
        day: The September 2026 observation day and snapshot serial.
        value: The reported incident size in acres.
        confirmed: Whether the update has matching formal-report evidence.

    Returns:
        A direct incident update suitable for confirmation and tie-breaking tests.
    """
    return peri_scribe.incidents.IncidentUpdate(
        observation_time=time(day),
        report_time=time(day) if confirmed else None,
        confirmed=confirmed,
        source="wfigs_location",
        source_file="report.gpkg",
        serial=day,
        measurements={"incident_size": value},
    )


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
                observation_time=time(day),
                report_time=None if report_day is None else time(report_day),
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
