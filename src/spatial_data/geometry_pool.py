"""Sharing immutable snapshot geometries within one source read.

[Geometry sharing reasoning](../../docs/algorithms/geometry-sharing.md)
explains the contract and correctness argument.
[Source preparation](../../docs/algorithms/source-geometry-preparation.md) explains
compact encoding keys and independently locked digest partitions.
"""

from __future__ import annotations

import contextlib
import dataclasses
import hashlib
import threading

import shapely


GEOMETRY_SHARD_COUNT = 16
type GeometryKey = tuple[bytes, int]


def geometry_digest(wkb: bytes) -> bytes:
    """Compact keys avoid retaining a second copy of every geometry's coordinates.

    Args:
        wkb: The serialized geometry bytes used to identify matching candidates.

    Returns:
        The digest used to select candidate geometries.
    """
    return hashlib.sha256(wkb).digest()


@dataclasses.dataclass(frozen=True, kw_only=True)
class GeometryState:
    """Unchanged digest branches stay shared when a cache snapshot gains a geometry.

    Branches split on differing digest bits. Skipping common prefixes keeps storage
    proportional to the number of geometries, and digest width bounds the depth even
    when observations arrive sorted by digest.
    """

    digest: bytes
    geometries: tuple[shapely.Geometry, ...]
    split_bit: int | None = None
    smaller: GeometryState | None = None
    larger: GeometryState | None = None


def shared_geometry(
    state: GeometryState | None,
    digest: bytes,
    wkb: bytes,
) -> tuple[GeometryState, shapely.Geometry]:
    """Preserve prior cache snapshots while sharing byte-identical geometry.

    A digest only selects candidates. Complete WKB comparisons preserve coordinates,
    dimensions, and spatial references even when digests collide.

    Args:
        state: The immutable cache snapshot, or None for an empty cache.
        digest: The digest identifying candidate geometries.
        wkb: Serialized geometry, including its spatial-reference identifier.

    Returns:
        The updated cache snapshot and the decoded or shared geometry.
    """
    if state is None:
        geometry = shapely.from_wkb(wkb)
        return GeometryState(digest=digest, geometries=(geometry,)), geometry
    digest_value = int.from_bytes(digest)
    differing_bit = (digest_value ^ int.from_bytes(state.digest)).bit_length()
    if state.split_bit is None or differing_bit > state.split_bit:
        if differing_bit:
            geometry = shapely.from_wkb(wkb)
            leaf = GeometryState(digest=digest, geometries=(geometry,))
            smaller, larger = (state, leaf) if state.digest < digest else (leaf, state)
            return (
                GeometryState(
                    digest=state.digest,
                    geometries=(),
                    split_bit=differing_bit,
                    smaller=smaller,
                    larger=larger,
                ),
                geometry,
            )
        for geometry in state.geometries:
            if shapely.to_wkb(geometry, include_srid=True) == wkb:
                return state, geometry
        geometry = shapely.from_wkb(wkb)
        return (
            dataclasses.replace(state, geometries=(*state.geometries, geometry)),
            geometry,
        )
    if not digest_value & (1 << (state.split_bit - 1)):
        smaller, geometry = shared_geometry(state.smaller, digest, wkb)
        updated = (
            state
            if smaller is state.smaller
            else dataclasses.replace(state, smaller=smaller)
        )
        return updated, geometry
    larger, geometry = shared_geometry(state.larger, digest, wkb)
    updated = (
        state if larger is state.larger else dataclasses.replace(state, larger=larger)
    )
    return updated, geometry


class GeometryShard:
    """One digest partition serializes immutable root replacement independently."""

    def __init__(self) -> None:
        """Keep each root's ownership aligned with its insertion lock."""
        self.state: GeometryState | None = None
        self.lock = threading.Lock()


class EncodingShard:
    """Exact collision classes keep compact keys separate from coordinate buffers."""

    def __init__(self) -> None:
        """Bound retained representatives to the source read owning this registry."""
        self.classes: dict[bytes, list[shapely.Geometry]] = {}
        self.lock = threading.Lock()


class GeometryKeys:
    """Identify canonical WKB classes without retaining a second coordinate copy."""

    def __init__(self) -> None:
        """Retained references prevent object identities being recycled during reuse."""
        self.identities: dict[int, tuple[shapely.Geometry, GeometryKey]] = {}
        self.lock = threading.Lock()
        self.shards = tuple(EncodingShard() for _ in range(GEOMETRY_SHARD_COUNT))

    def key(self, geometry: shapely.Geometry) -> GeometryKey:
        """Preserve the exact SRID-ignoring equality used by `.wkb` consumers.

        Args:
            geometry: Immutable geometry retained by this source-read owner.

        Returns:
            A digest and collision-class ordinal, meaningful only in this registry.
        """
        identity = id(geometry)
        with self.lock:
            retained = self.identities.get(identity)
            if retained is not None:
                return retained[1]
        encoded = geometry.wkb
        digest = geometry_digest(encoded)
        shard = self.shards[int.from_bytes(digest) % len(self.shards)]
        with shard.lock:
            candidates = shard.classes.setdefault(digest, [])
            for position, candidate in enumerate(candidates):
                if candidate.wkb == encoded:
                    result = digest, position
                    break
            else:
                result = digest, len(candidates)
                candidates.append(geometry)
        with self.lock:
            self.identities[identity] = geometry, result
        return result


class GeometryPool:
    """A source read owns independently locked immutable geometry partitions.

    Identical digest candidates always reach one shard, so concurrent decodes still
    publish one object per canonical encoding. Completed reads release their cache.
    """

    def __init__(self) -> None:
        """Give source decoding and representation keys one explicit lifetime."""
        self.shards = tuple(GeometryShard() for _ in range(GEOMETRY_SHARD_COUNT))
        self.geometry_keys = GeometryKeys()

    def states(self) -> tuple[GeometryState | None, ...]:
        """Read one consistent immutable snapshot across all digest partitions.

        Returns:
            Roots in fixed shard order; subsequent insertion cannot change them.
        """
        with contextlib.ExitStack() as locks:
            for shard in self.shards:
                locks.enter_context(shard.lock)
            return tuple(shard.state for shard in self.shards)

    def from_wkb(self, wkb: bytes) -> shapely.Geometry:
        """Reuse matching decoded geometry without retaining the source WKB bytes.

        Args:
            wkb: The serialized geometry, including its spatial-reference identifier
                when present.

        Returns:
            A geometry with the supplied coordinates and spatial reference.
        """
        digest = geometry_digest(wkb)
        shard = self.shards[int.from_bytes(digest) % len(self.shards)]
        with shard.lock:
            shard.state, geometry = shared_geometry(shard.state, digest, wkb)
            return geometry
