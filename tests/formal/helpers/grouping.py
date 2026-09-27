"""Finite graphs exercise the actual parent-pointer grouping implementation."""

import itertools

import numpy as np
import shapely

import peri_scribe.fires.grouping
import peri_scribe.models
import tests.formal.helpers.generation


PERMUTATION_SIZE = 4


def graph_records(
    count: int,
    edges: tuple[tuple[int, int], ...],
) -> list[peri_scribe.models.FireRecord]:
    """Encode arbitrary graph edges as shared identifiers without geometric shortcuts.

    Args:
        count: Number of vertices, including isolated records.
        edges: Undirected connections to realize using identifier aliases.

    Returns:
        Records whose identifier-sharing graph is exactly the supplied graph.
    """
    return [
        peri_scribe.models.FireRecord(
            name=f"Record {index}",
            status=peri_scribe.models.FireStatus.ACTIVE,
            identifiers=frozenset(str(edge) for edge in edges if index in edge),
        )
        for index in range(count)
    ]


def graph_cases() -> list[list[peri_scribe.models.FireRecord]]:
    """Exhaust small graphs and all orders where parent compression has many paths.

    Returns:
        Every graph through five vertices and every order of four-vertex graphs.
    """
    result = []
    for count in range(6):
        possible = tuple(itertools.combinations(range(count), 2))
        for mask in range(1 << len(possible)):
            edges = tuple(
                edge for index, edge in enumerate(possible) if mask & (1 << index)
            )
            records = graph_records(count, edges)
            if count == PERMUTATION_SIZE:
                result.extend(list(order) for order in itertools.permutations(records))
            else:
                result.append(records)
    return result


def spatial_cases() -> list[list[peri_scribe.models.FireRecord]]:
    """Exercise proximity-class compression together with identifier and name aliases.

    Returns:
        Reproducible records with absent, empty, repeated, nearby, and distant shapes.
    """
    generator = np.random.default_rng(93477)
    geometries = (
        None,
        shapely.Point(),
        shapely.Point(-120, 40),
        shapely.Point(-120, 40),
        shapely.Point(-119.96, 40),
        shapely.Point(-119.92, 40),
        shapely.Point(-119, 40),
    )
    return [
        [
            peri_scribe.models.FireRecord(
                name="Formal",
                status=peri_scribe.models.FireStatus.ACTIVE,
                identifiers=frozenset(
                    name for name in ("a", "b") if int(generator.integers(4)) == 0
                ),
                names=frozenset(
                    name
                    for name in ("Canyon", "Timber")
                    if int(generator.integers(2)) == 0
                ),
                geometry=tests.formal.helpers.generation.choose(generator, geometries),
            )
            for _ in range(int(generator.integers(1, 10)))
        ]
        for _ in range(400)
    ]


def command(records: list[peri_scribe.models.FireRecord]) -> str:
    """Use the declared graph relation, independently of union and spatial indexing.

    Args:
        records: Records whose names and identifiers determine candidate relationships.

    Returns:
        A command for Lean's proved component construction.
    """
    edges = []
    for left, right in itertools.combinations(range(len(records)), 2):
        first, second = records[left], records[right]
        adjacent = bool(first.identifiers & second.identifiers) or (
            bool(first.names & second.names)
            and first.geometry is not None
            and second.geometry is not None
            and bool(
                shapely.dwithin(
                    first.geometry,
                    second.geometry,
                    peri_scribe.fires.grouping.FIRE_PROXIMITY_TOLERANCE.m_as("degrees"),
                ),
            )
        )
        if adjacent:
            edges.append(f"{left},{right}")
    return f"group {len(records)} {' '.join(edges)}".rstrip()


def canonical(groups: list[list[int]], count: int) -> tuple[int, ...]:
    """Compare membership independently of the representative chosen by union order.

    Args:
        groups: Components returned by the application.
        count: Number of original records, including isolated vertices.

    Returns:
        Each record's smallest component member.
    """
    result = [-1] * count
    for group in groups:
        for member in group:
            assert result[member] == -1
            result[member] = min(group)
    assert all(label >= 0 for label in result)
    return tuple(result)
