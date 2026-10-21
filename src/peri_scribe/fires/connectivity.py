"""Transient union tables for exact source grouping and dependency partitions.

[Grouping and dependency reasoning](../../../docs/algorithms/incremental-grouping.md)
"""

from __future__ import annotations

import dataclasses


@dataclasses.dataclass(frozen=True, kw_only=True)
class UnionFind:
    """Own local mutable tables without allowing the grouping state to escape."""

    parents: list[int]
    sizes: list[int]

    @classmethod
    def for_count(cls, count: int) -> UnionFind:
        """Start one independent class for every original input position.

        Args:
            count: The number of positions in this transient calculation.

        Returns:
            A private union table with singleton components.
        """
        return cls(parents=list(range(count)), sizes=[1] * count)

    def find(self, index: int) -> int:
        """Resolve a representative while shortening its future parent path.

        Args:
            index: An original position in this table.

        Returns:
            The current representative of the position's component.
        """
        while self.parents[index] != index:
            self.parents[index] = self.parents[self.parents[index]]
            index = self.parents[index]
        return index

    def union(self, left: int, right: int) -> None:
        """Join components by size so subsequent paths remain shallow.

        Args:
            left: One original position to join.
            right: The other original position to join.
        """
        first, second = self.find(left), self.find(right)
        if first == second:
            return
        if self.sizes[first] < self.sizes[second]:
            first, second = second, first
        self.parents[second] = first
        self.sizes[first] += self.sizes[second]

    def groups(self) -> list[list[int]]:
        """Preserve original position and first-encounter component ordering.

        Returns:
            Sorted members in components ordered by their first member.
        """
        groups: dict[int, list[int]] = {}
        for index in range(len(self.parents)):
            groups.setdefault(self.find(index), []).append(index)
        return list(groups.values())
