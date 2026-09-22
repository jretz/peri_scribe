"""Sharing immutable snapshot geometries within one source read."""

from __future__ import annotations

import dataclasses
import hashlib
import threading

import shapely


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


class GeometryPool:
    """A source read owns the lock and replaces immutable cache snapshots.

    Workers share this small synchronization boundary so concurrent decodes cannot
    publish duplicate geometries. Completed reads release their entire cache.
    """

    def __init__(self) -> None:
        """Give each source read its own cache lifetime and synchronization boundary."""
        self.state: GeometryState | None = None
        self.lock = threading.Lock()

    def from_wkb(self, wkb: bytes) -> shapely.Geometry:
        """Reuse matching decoded geometry without retaining the source WKB bytes.

        Args:
            wkb: The serialized geometry, including its spatial-reference identifier
                when present.

        Returns:
            A geometry with the supplied coordinates and spatial reference.
        """
        digest = geometry_digest(wkb)
        with self.lock:
            self.state, geometry = shared_geometry(self.state, digest, wkb)
            return geometry
