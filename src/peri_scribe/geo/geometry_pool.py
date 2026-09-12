"""Sharing immutable snapshot geometries within one source read."""

from __future__ import annotations

import dataclasses
import hashlib
import threading

import shapely


def geometry_digest(wkb: bytes) -> bytes:
    """Compact keys avoid retaining a second copy of every geometry's coordinates.

    Returns:
        The digest used to select candidate geometries.
    """
    return hashlib.sha256(wkb).digest()


@dataclasses.dataclass(frozen=True, kw_only=True)
class GeometryPool:
    """A source read owns its pool so completed reads cannot accumulate geometries.

    Snapshot workers share the pool. A digest only selects candidates: comparing their
    complete WKB preserves distinct coordinates, dimensions, and spatial references even
    when digests collide.
    """

    geometries: dict[bytes, list[shapely.Geometry]] = dataclasses.field(
        default_factory=dict,
    )
    lock: threading.Lock = dataclasses.field(default_factory=threading.Lock)

    def from_wkb(self, wkb: bytes) -> shapely.Geometry:
        """Reuse matching decoded geometry without retaining the source WKB bytes.

        Returns:
            A geometry with the supplied coordinates and spatial reference.
        """
        digest = geometry_digest(wkb)
        with self.lock:
            candidates = self.geometries.setdefault(digest, [])
            for geometry in candidates:
                if shapely.to_wkb(geometry, include_srid=True) == wkb:
                    return geometry
            geometry = shapely.from_wkb(wkb)
            candidates.append(geometry)
            return geometry
