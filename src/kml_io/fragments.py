"""Keep exact polygon boundary text reusable without retaining source geometries.

Design notes:
[Output serialization](../../docs/algorithms/output-serialization.md) and
[fresh boundary spill](../../docs/algorithms/fresh-boundary-spill.md).
"""

from __future__ import annotations

import collections
import contextlib
import dataclasses
import hashlib
import re
import sys
import tempfile
import typing

import shapely

import spatial_data.cache_values
import spatial_data.payload_codec
import spatial_data.product_cache


NAMESPACE = "kml-polygon-boundaries-v1"
MEMORY_BUDGET = 16 * 1024 * 1024
SPILL_BUDGET = 128 * 1024 * 1024
SPILL_ENTRIES = 8192
BOUNDARY_PATTERN = re.compile(
    r"<outerBoundaryIs><LinearRing><coordinates>[-0-9., nanif]*"
    r"</coordinates></LinearRing></outerBoundaryIs>"
    r"(?:<innerBoundaryIs><LinearRing><coordinates>[-0-9., nanif]*"
    r"</coordinates></LinearRing></innerBoundaryIs>)*",
)


@dataclasses.dataclass(frozen=True, kw_only=True, slots=True)
class Entry:
    """Account for retained Python values as well as their coordinate text."""

    boundaries: tuple[str, ...]
    size: int


def geometry_key(geometry: shapely.Geometry, decimals: int) -> str:
    """Distinguish exact coordinates, component order, SRID, and display precision.

    Args:
        geometry: The geometry whose ordered rings will be formatted.
        decimals: The coordinate precision used by the formatter.

    Returns:
        A compact fingerprint that holds no reference to the geometry.
    """
    digest = hashlib.sha256(f"{geometry.geom_type}:{decimals}:".encode())
    digest.update(shapely.to_wkb(geometry, include_srid=True))
    return digest.hexdigest()


def decoded_boundaries(payload: bytes, count: int) -> tuple[str, ...] | None:
    """Reject malformed disposable fragments before they can enter a document.

    Args:
        payload: The authenticated stored bytes.
        count: The number of polygon components expected by the current geometry.

    Returns:
        Ordered boundary strings, or None when storage needs regeneration.
    """
    try:
        value = spatial_data.cache_values.loads(payload)
    except ValueError:
        return None
    if (
        not isinstance(value, tuple)
        or len(value) != count
        or not all(
            isinstance(boundary, str) and BOUNDARY_PATTERN.fullmatch(boundary)
            for boundary in value
        )
    ):
        return None
    return value


@dataclasses.dataclass(frozen=True, kw_only=True, slots=True)
class SpillEntry:
    """Locate and authenticate one complete frame without retaining its text."""

    offset: int
    length: int
    digest: bytes


class BoundarySpool:
    """Keep bounded, append-only fresh fragments in one privately owned stream."""

    def __init__(
        self,
        stream: typing.BinaryIO,
        *,
        budget: int = SPILL_BUDGET,
        limit: int = SPILL_ENTRIES,
    ) -> None:
        """Leave stream closure to the surrounding publication scope.

        Args:
            stream: Empty private seekable file with no concurrent readers or writers.
            budget: Maximum encoded bytes reserved, including incomplete writes.
            limit: Maximum indexed fragments retained until the scope ends.
        """
        self.stream = stream
        self.budget = budget
        self.limit = limit
        self.entries: dict[str, SpillEntry] = {}
        self.size = 0
        self.disabled = False

    def get(self, key: str) -> bytes | None:
        """Read only complete, authenticated payloads from this scope.

        Args:
            key: Exact geometry and formatter fingerprint.

        Returns:
            Original logical bytes, or None after absence, corruption or I/O failure.
        """
        entry = self.entries.get(key)
        if entry is None:
            return None
        try:
            self.stream.seek(entry.offset)
            frame = self.stream.read(entry.length)
            payload = spatial_data.payload_codec.decode(frame)
        except OSError, ValueError:
            return None
        return payload if hashlib.sha256(payload).digest() == entry.digest else None

    def put(self, key: str, payload: bytes) -> None:
        """Index completed writes while treating capacity and storage errors as misses.

        A failed write disables later appends. Existing records remain readable and the
        reserved byte count still covers any incomplete tail.

        Args:
            key: Exact geometry and formatter fingerprint.
            payload: Complete logical boundary bytes created or validated this scope.
        """
        if self.disabled or key in self.entries or len(self.entries) >= self.limit:
            return
        try:
            frame = spatial_data.payload_codec.encode(payload)
        except ValueError:
            return
        if self.size + len(frame) > self.budget:
            return
        entry = SpillEntry(
            offset=self.size,
            length=len(frame),
            digest=hashlib.sha256(payload).digest(),
        )
        self.size += len(frame)
        try:
            self.stream.seek(entry.offset)
            if self.stream.write(frame) != len(frame):
                self.disabled = True
                return
        except OSError:
            self.disabled = True
            return
        self.entries[key] = entry


class BoundaryCache:
    """Bound each writer's retained fragments independently of document size."""

    def __init__(self, budget: int = MEMORY_BUDGET) -> None:
        """Retain only compact identifiers and rendered text for nearby reuse.

        Args:
            budget: Maximum accounted bytes of retained entries.
        """
        self.budget = budget
        self.entries: collections.OrderedDict[str, Entry] = collections.OrderedDict()
        self.retained_bytes = 0
        self.peak_bytes = 0
        self.largest_fragment_bytes = 0
        self.memory_hits = 0
        self.persistent_hits = 0
        self.computed = 0
        self.spill_hits = 0
        self.spool: BoundarySpool | None = None

    @contextlib.contextmanager
    def spill(self) -> typing.Generator[None]:
        """Release optional fresh fragments when this document succeeds or fails.

        Standalone geometry calls keep their existing memory-only lifetime. A document
        opens a fresh private file; failure to open it leaves ordinary rendering active.

        Yields:
            Control while document-local reuse is available.
        """
        with contextlib.ExitStack() as resources:
            try:
                stream = resources.enter_context(
                    tempfile.TemporaryFile(mode="w+b", buffering=0),
                )
            except OSError:
                yield
                return
            previous = self.spool
            self.spool = BoundarySpool(stream)
            try:
                yield
            finally:
                self.spool = previous

    def boundaries(
        self,
        geometry: shapely.Geometry,
        decimals: int,
        render: typing.Callable[[shapely.Geometry], tuple[str, ...]],
    ) -> tuple[str, ...]:
        """Reuse stable rings while leaving presentation wrappers to each caller.

        Args:
            geometry: The current ordered polygon geometry.
            decimals: The current formatter's coordinate precision.
            render: The unchanged boundary formatter, used only on a cache miss.

        Returns:
            The exact ordered polygon boundary text.
        """
        key = geometry_key(geometry, decimals)
        entry = self.entries.get(key)
        if entry is not None:
            self.entries.move_to_end(key)
            self.memory_hits += 1
            return entry.boundaries
        count = 1 if geometry.geom_type == "Polygon" else len(geometry.geoms)
        payload = None if self.spool is None else self.spool.get(key)
        boundaries = None if payload is None else decoded_boundaries(payload, count)
        if boundaries is not None:
            self.spill_hits += 1
        else:
            payload = spatial_data.product_cache.get(NAMESPACE, key)
            boundaries = None if payload is None else decoded_boundaries(payload, count)
            if boundaries is None:
                boundaries = render(geometry)
                self.computed += 1
                payload = None
                if self.spool is not None or spatial_data.product_cache.active():
                    payload = spatial_data.cache_values.dumps(boundaries)
                if payload is not None and spatial_data.product_cache.active():
                    spatial_data.product_cache.put(NAMESPACE, key, payload)
            else:
                self.persistent_hits += 1
            if self.spool is not None and payload is not None:
                self.spool.put(key, payload)
        self.retain(key, boundaries)
        return boundaries

    def retain(self, key: str, boundaries: tuple[str, ...]) -> None:
        """Evict old fragments before retaining another bounded entry.

        Oversized fragments remain transient so one large fire cannot pin its rings
        for the remainder of a publication.

        Args:
            key: The compact input fingerprint.
            boundaries: Complete formatted polygon boundaries.
        """
        size = (
            sys.getsizeof(key)
            + sys.getsizeof(boundaries)
            + sum(sys.getsizeof(boundary) for boundary in boundaries)
            + sys.getsizeof(Entry(boundaries=boundaries, size=0))
            + sys.getsizeof(0)
        )
        self.largest_fragment_bytes = max(self.largest_fragment_bytes, size)
        previous = self.entries.pop(key, None)
        if previous is not None:
            self.retained_bytes -= previous.size
        if size > self.budget:
            return
        while self.retained_bytes + size > self.budget:
            _, evicted = self.entries.popitem(last=False)
            self.retained_bytes -= evicted.size
        self.entries[key] = Entry(boundaries=boundaries, size=size)
        self.retained_bytes += size
        self.peak_bytes = max(self.peak_bytes, self.retained_bytes)
