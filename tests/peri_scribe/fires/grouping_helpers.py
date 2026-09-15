"""Provide data builders and stand-ins for grouping tests."""

from __future__ import annotations

import typing

import structlog

import peri_scribe.fires.grouping
import peri_scribe.models


def warning_events(
    records: list[peri_scribe.models.FireRecord],
    fires: list[peri_scribe.models.Fire],
) -> list[typing.MutableMapping[str, object]]:
    """Return events logged while warning about inconsistent *records*.

    Args:
        records: The grouped fire records.
        fires: The fires built from the groups.

    Returns:
        The logged events.
    """
    groups = [[0, 1]]
    with structlog.testing.capture_logs() as captured:
        peri_scribe.fires.grouping.warn_for_inconsistent_fires(records, groups, fires)
    return captured
