"""Realize every bounded abstract graph through exact multipart geometry overlap."""

from __future__ import annotations

import collections
import re
import typing

import shapely


if typing.TYPE_CHECKING:
    import tests.formal.helpers.tlc


VERTEX_COUNT = 4
type Edges = frozenset[tuple[int, int]]


def edges(value: str) -> Edges:
    """Translate checked one-based TLA+ edge tuples to concrete geometry positions.

    Args:
        value: Complete exported finite edge set from TLC.

    Returns:
        Canonical zero-based undirected pairs.
    """
    return frozenset(
        (int(left) - 1, int(right) - 1)
        for left, right in re.findall(r"<<\s*(\d+)\s*,\s*(\d+)\s*>>", value)
    )


def geometries(graph: Edges) -> list[shapely.Geometry]:
    """Give each graph edge a shared polygon gadget without metric assumptions.

    Each vertex has a private polygon. Its multipart geometry also contains one square
    shared only with each incident neighbor. Different gadgets lie farther apart than
    the proximity tolerance, so geometric adjacency equals the arbitrary input graph.

    Args:
        graph: Abstract undirected adjacency on four original vertices.

    Returns:
        Four nonempty geometries realizing exactly those edges.
    """
    ordered = sorted(graph)
    return [
        shapely.MultiPolygon([
            shapely.box(-10 - vertex * 5, 0, -9 - vertex * 5, 1),
            *[
                shapely.box(position * 5, 10, position * 5 + 1, 11)
                for position, edge in enumerate(ordered)
                if vertex in edge
            ],
        ])
        for vertex in range(VERTEX_COUNT)
    ]


def final_forests(
    graph: tests.formal.helpers.tlc.Graph,
) -> dict[Edges, set[Edges]]:
    """Retain every checked terminal forest for every complete abstract input graph.

    Args:
        graph: Full freshly checked finite frontier/discovery transition graph.

    Returns:
        All allowed completed forests grouped by their original edge relation.
    """
    result: dict[Edges, set[Edges]] = collections.defaultdict(set)
    for state in graph.states.values():
        if (
            state["active"] == "{}"
            and state["pending"] == "{}"
            and state["current"] == "0"
        ):
            result[edges(state["graph"])].add(edges(state["forest"]))
    return dict(result)
