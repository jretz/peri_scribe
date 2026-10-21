"""Reuse exact grouping partitions within conservative source dependency blocks.

[Incremental grouping](../../../docs/algorithms/incremental-grouping.md)
"""

from __future__ import annotations

import collections.abc
import hashlib
import json
import operator
import typing

import pydantic
import structlog

import peri_scribe.fires.connectivity
import peri_scribe.models
import spatial_data.product_cache


NAMESPACE = "source-grouping-dependency-block-v1"
logger = structlog.get_logger()


class Partition(pydantic.BaseModel):
    """Validate a complete ordered partition before translating cached positions."""

    model_config = pydantic.ConfigDict(strict=True, frozen=True)

    count: pydantic.NonNegativeInt
    groups: tuple[tuple[int, ...], ...]

    @pydantic.model_validator(mode="after")
    def complete(self) -> typing.Self:
        """Reject incomplete, repeated, misordered, or out-of-domain positions.

        Returns:
            This partition when it accounts for every original occurrence.

        Raises:
            ValueError: If the payload is not the canonical ordered partition shape.
        """
        if any(not group or tuple(sorted(group)) != group for group in self.groups):
            message = "Grouping partitions require nonempty ordered components"
            raise ValueError(message)
        if tuple(sorted(self.groups, key=operator.itemgetter(0))) != self.groups:
            message = "Grouping components must follow their first occurrence"
            raise ValueError(message)
        positions = [position for group in self.groups for position in group]
        if len(positions) != self.count or any(
            actual != expected for expected, actual in enumerate(sorted(positions))
        ):
            message = "Grouping partitions must contain every position exactly once"
            raise ValueError(message)
        return self


def dependency_blocks(
    records: list[peri_scribe.models.FireRecord],
) -> list[list[int]]:
    """Contain every possible identity edge without requiring geometry work.

    A proximity edge needs a shared name; an identifier edge needs a shared identifier.
    Joining both incidences conservatively includes every possible fire component.
    Rebuilding these blocks each time allows removed bridge rows to split a block.

    Args:
        records: Current records in authoritative occurrence order.

    Returns:
        Independent blocks in original occurrence order.
    """
    components = peri_scribe.fires.connectivity.UnionFind.for_count(len(records))
    identifiers: dict[str, int] = {}
    names: dict[str, int] = {}
    for index, record in enumerate(records):
        for values, seen in ((record.identifiers, identifiers), (record.names, names)):
            for value in values:
                components.union(index, seen.setdefault(value, index))
    return components.groups()


def block_key(row_keys: collections.abc.Sequence[str], policy: str) -> str:
    """Retain occurrence multiplicity and ordering in a content-addressed block key.

    Args:
        row_keys: Complete canonical evidence identities in this block's order.
        policy: Exact runtime grouping threshold identity.

    Returns:
        A fingerprint within the product store's code and runtime context.
    """
    return hashlib.sha256(json.dumps((policy, list(row_keys))).encode()).hexdigest()


def cached_partition(key: str, count: int) -> Partition | None:
    """Treat an unauthenticated or structurally invalid partition as a miss.

    Args:
        key: This block's exact ordered input identity.
        count: Current occurrence count required by the key.

    Returns:
        A complete compatible partition, or None when calculation is required.
    """
    payload = spatial_data.product_cache.get(NAMESPACE, key)
    if payload is None:
        return None
    try:
        result = Partition.model_validate_json(payload)
    except pydantic.ValidationError:
        logger.info("Ignoring invalid grouping partition", exc_info=True)
        return None
    return result if result.count == count else None


def grouped_indices(
    records: list[peri_scribe.models.FireRecord],
    row_keys: collections.abc.Sequence[str],
    policy: str,
    calculate: collections.abc.Callable[
        [list[peri_scribe.models.FireRecord]],
        list[list[int]],
    ],
) -> list[list[int]]:
    """Recompute changed dependency closures and reuse every unchanged local partition.

    Args:
        records: Current source occurrences.
        row_keys: Complete canonical evidence identity for each occurrence.
        policy: Runtime grouping threshold identity.
        calculate: The uncached exact grouping algorithm for one independent block.

    Returns:
        The complete ordered partition of the current records.

    Raises:
        ValueError: If the caller supplies a different number of record identities.
    """
    if len(records) != len(row_keys):
        message = "Grouping evidence keys must align with every source occurrence"
        raise ValueError(message)
    result: list[list[int]] = []
    retained: set[str] = set()
    reused = recomputed = trivial = 0
    for block in dependency_blocks(records):
        if len(block) == 1:
            result.append(block)
            trivial += 1
            continue
        key = block_key([row_keys[index] for index in block], policy)
        retained.add(key)
        partition = cached_partition(key, len(block))
        if partition is None:
            groups = calculate([records[index] for index in block])
            partition = Partition(
                count=len(block),
                groups=tuple(tuple(group) for group in groups),
            )
            spatial_data.product_cache.put(
                NAMESPACE,
                key,
                partition.model_dump_json().encode(),
            )
            recomputed += 1
        else:
            reused += 1
        result.extend([block[index] for index in group] for group in partition.groups)
    spatial_data.product_cache.prune(NAMESPACE, retained)
    logger.info(
        "Grouping dependency reuse",
        reused=reused,
        recomputed=recomputed,
        trivial=trivial,
    )
    return sorted(result, key=operator.itemgetter(0))
