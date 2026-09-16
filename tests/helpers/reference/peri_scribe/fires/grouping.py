"""Calculate independent expected results for grouping tests."""

from __future__ import annotations

import peri_scribe.fires.grouping
import peri_scribe.models


def reference_groups(records: list[peri_scribe.models.FireRecord]) -> list[list[int]]:
    """Find connected components by walking all pairwise identity and proximity edges.

    Args:
        records: Records with normalized identity keys and degree coordinates.

    Returns:
        Components in encounter order, with each component's indices sorted.
    """
    neighbors = {index: set[int]() for index in range(len(records))}
    for left, record in enumerate(records):
        for right, other in enumerate(records):
            shared_identifier = bool(record.identifiers & other.identifiers)
            shared_location = (
                bool(record.names & other.names)
                and record.geometry is not None
                and other.geometry is not None
                and not record.geometry.is_empty
                and not other.geometry.is_empty
                and record.geometry.distance(other.geometry)
                <= peri_scribe.fires.grouping.FIRE_PROXIMITY_TOLERANCE.m_as("degrees")
            )
            if shared_identifier or shared_location:
                neighbors[left].add(right)
    remaining = set(neighbors)
    groups = []
    while remaining:
        pending = [min(remaining)]
        component: set[int] = set()
        while pending:
            index = pending.pop()
            if index not in component:
                component.add(index)
                pending.extend(neighbors[index] - component)
        remaining -= component
        groups.append(sorted(component))
    return groups
