"""Observe dependency-block calculation without changing its identity policy."""

from __future__ import annotations

import dataclasses

import peri_scribe.fires.grouping
import peri_scribe.models


@dataclasses.dataclass(frozen=True, kw_only=True)
class PartitionCalculator:
    """Retain the complete input of each actually recomputed dependency block."""

    calls: list[tuple[peri_scribe.models.FireRecord, ...]] = dataclasses.field(
        default_factory=list,
    )

    def calculate(
        self,
        records: list[peri_scribe.models.FireRecord],
    ) -> list[list[int]]:
        """Record a calculation while evaluating the ordinary exact grouping policy.

        Args:
            records: One independent current dependency block.

        Returns:
            Its uncached ordered identity partition.
        """
        self.calls.append(tuple(records))
        return peri_scribe.fires.grouping.group_fire_record_indices(records)
