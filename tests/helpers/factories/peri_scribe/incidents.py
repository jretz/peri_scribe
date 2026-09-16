"""Build inputs for incidents tests."""

from __future__ import annotations

import datetime

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
