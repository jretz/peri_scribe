"""Calculate independent expected results for grouping tests."""

from __future__ import annotations

import collections.abc

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
    return groups_from_neighbors(neighbors)


def edge_groups(
    count: int,
    edges: collections.abc.Iterable[tuple[int, int]],
) -> list[list[int]]:
    """Walk the full undirected adjacency independently of production union-find.

    Args:
        count: Number of original vertices, including isolated vertices.
        edges: Sound undirected graph edges.

    Returns:
        Connected components in original encounter order.
    """
    neighbors = {index: set[int]() for index in range(count)}
    for left, right in edges:
        neighbors[left].add(right)
        neighbors[right].add(left)
    return groups_from_neighbors(neighbors)


def groups_from_neighbors(neighbors: dict[int, set[int]]) -> list[list[int]]:
    """Return reachability components by exhausting every queued vertex.

    Args:
        neighbors: Full undirected adjacency, including every isolated vertex.

    Returns:
        Sorted component members ordered by their first original vertex.
    """
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
