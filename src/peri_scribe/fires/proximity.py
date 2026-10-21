"""Find an exact proximity forest without materializing dense neighbor graphs.

[Connectivity and active bounds](../../../docs/algorithms/incremental-grouping.md)
"""

from __future__ import annotations

import collections.abc
import dataclasses
import math
import typing

import shapely


if typing.TYPE_CHECKING:
    import pint


SMALL_QUERY_LIMIT = 32
type Bounds = tuple[float, float, float, float]


@dataclasses.dataclass(frozen=True, kw_only=True)
class BoundsNode:
    """Retain a source-coordinate envelope and its immutable tree links."""

    bounds: Bounds
    parent: int | None
    children: tuple[int, ...] = ()
    item: int | None = None


@dataclasses.dataclass(frozen=True, kw_only=True)
class BoundsTree:
    """Separate active counters from immutable source-coordinate envelopes."""

    nodes: tuple[BoundsNode, ...]
    leaves: tuple[int, ...]
    counts: tuple[int, ...]


def bounds_tree(bounds: list[Bounds]) -> BoundsTree:
    """Balance source envelopes so exhausted subtrees can be skipped.

    Args:
        bounds: Nonempty finite GEOS envelopes, in source degree coordinates.

    Returns:
        Immutable tree nodes, each input's leaf position, and initial subtree counts.
    """
    nodes: list[BoundsNode] = []
    leaves = [0] * len(bounds)
    counts: list[int] = []

    def add(indices: list[int], parent: int | None) -> int:
        """Give each branch a conservative envelope over all its leaves.

        Args:
            indices: Input positions assigned to this branch.
            parent: Owning branch, or None for the root.

        Returns:
            This branch's position in the immutable node table.
        """
        envelope = (
            min(bounds[index][0] for index in indices),
            min(bounds[index][1] for index in indices),
            max(bounds[index][2] for index in indices),
            max(bounds[index][3] for index in indices),
        )
        position = len(nodes)
        nodes.append(BoundsNode(bounds=envelope, parent=parent))
        counts.append(len(indices))
        if len(indices) == 1:
            leaves[indices[0]] = position
            nodes[position] = dataclasses.replace(nodes[position], item=indices[0])
        else:
            axis = 0 if envelope[2] - envelope[0] >= envelope[3] - envelope[1] else 1
            ordered = sorted(
                indices,
                key=lambda index: bounds[index][axis] + bounds[index][axis + 2],
            )
            middle = len(ordered) // 2
            children = add(ordered[:middle], position), add(ordered[middle:], position)
            nodes[position] = dataclasses.replace(nodes[position], children=children)
        return position

    if bounds:
        add(list(range(len(bounds))), None)
    return BoundsTree(nodes=tuple(nodes), leaves=tuple(leaves), counts=tuple(counts))


def remove(tree: BoundsTree, counts: list[int], item: int) -> None:
    """Remove one discovered leaf from every ancestor's active count.

    Args:
        tree: Immutable source envelopes.
        counts: This traversal's remaining leaf counts.
        item: An input position that was active immediately before removal.
    """
    position: int | None = tree.leaves[item]
    while position is not None:
        counts[position] -= 1
        position = tree.nodes[position].parent


def candidates(
    tree: BoundsTree,
    counts: list[int],
    query: Bounds,
) -> collections.abc.Iterator[int]:
    """Visit only undiscovered envelopes intersecting a conservative search box.

    Args:
        tree: Immutable source envelopes.
        counts: Current remaining counts, which can change between yielded candidates.
        query: Expanded source envelope in the same degree coordinate system.

    Yields:
        Active leaf positions whose envelopes can contain a near geometry.
    """
    pending = [0] if tree.nodes else []
    while pending:
        position = pending.pop()
        if not counts[position]:
            continue
        node = tree.nodes[position]
        if (
            node.bounds[0] > query[2]
            or node.bounds[1] > query[3]
            or node.bounds[2] < query[0]
            or node.bounds[3] < query[1]
        ):
            continue
        if node.item is not None:
            yield node.item
        else:
            pending.extend(node.children)


def expanded(bounds: Bounds, distance: float) -> Bounds:
    """Round the broad phase outward so exact-distance boundary cases remain eligible.

    Args:
        bounds: Native GEOS envelope in source degree coordinates.
        distance: Degree magnitude converted at the geometry adapter boundary.

    Returns:
        A conservative native-coordinate search envelope.
    """
    return (
        math.nextafter(bounds[0] - distance, -math.inf),
        math.nextafter(bounds[1] - distance, -math.inf),
        math.nextafter(bounds[2] + distance, math.inf),
        math.nextafter(bounds[3] + distance, math.inf),
    )


def spanning_pairs(
    geometries: list[shapely.Geometry],
    *,
    tolerance: pint.Quantity[float],
) -> collections.abc.Iterator[tuple[int, int]]:
    """Connect every proximity component with exact geometry predicates.

    Small inputs use a bounded STRtree query. Large finite inputs remove discovered
    geometries from an active bounding-box tree, so a dense true-neighbor graph emits
    only a spanning forest. False envelope candidates can still require quadratic work.

    Args:
        geometries: Nonempty source geometries in degree coordinates.
        tolerance: Maximum exact GEOS distance in degrees.

    Yields:
        Sound edges whose transitive closure equals the complete proximity graph.
    """
    distance = tolerance.m_as("degrees")
    bounds = [geometry.bounds for geometry in geometries]
    if len(geometries) < SMALL_QUERY_LIMIT or any(
        not all(math.isfinite(value) for value in envelope) for envelope in bounds
    ):
        tree = shapely.STRtree(geometries)
        pairs = tree.query(geometries, predicate="dwithin", distance=distance)
        for left, right in zip(pairs[0], pairs[1], strict=True):
            if left < right:
                yield int(left), int(right)
        return
    tree = bounds_tree(bounds)
    counts = list(tree.counts)
    for seed in range(len(geometries)):
        if not counts[tree.leaves[seed]]:
            continue
        remove(tree, counts, seed)
        pending = [seed]
        while pending:
            current = pending.pop()
            for neighbor in candidates(
                tree,
                counts,
                expanded(bounds[current], distance),
            ):
                if shapely.dwithin(geometries[current], geometries[neighbor], distance):
                    remove(tree, counts, neighbor)
                    pending.append(neighbor)
                    yield current, neighbor
