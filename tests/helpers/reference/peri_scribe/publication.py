"""Calculate independent expected results for publication tests."""

from __future__ import annotations

import datetime
import typing


if typing.TYPE_CHECKING:
    import peri_scribe.publication


def earliest_linked_capture(
    target: peri_scribe.publication.Mapping,
    measurements: list[peri_scribe.publication.Mapping],
) -> datetime.datetime:
    """Find the earliest same-shape capture by following overlapping alias sets.

    Args:
        target: The mapping whose first capture is required.
        measurements: Every snapshot's original measurements.

    Returns:
        The earliest time reachable through identifiers for the same shape, retaining
        the original timestamp when there are no identifiers.
    """
    identifiers = set(target.identifiers)
    related = [target]
    remaining = [item for item in measurements if item.shape == target.shape]
    while remaining:
        connected = [
            item for item in remaining if identifiers.intersection(item.identifiers)
        ]
        if not connected:
            break
        related.extend(connected)
        identifiers.update(
            identifier for item in connected for identifier in item.identifiers
        )
        remaining = [item for item in remaining if item not in connected]
    return min(item.captured_at for item in related)
