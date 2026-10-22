"""Observe actual boundary rendering without replacing its output."""

import dataclasses

import shapely

import kml_io.geometry


@dataclasses.dataclass(frozen=True, kw_only=True)
class BoundaryRenderer:
    """Record detached geometry bytes so call assertions retain no source objects."""

    calls: list[bytes] = dataclasses.field(default_factory=list)

    def __call__(self, geometry: shapely.Geometry) -> tuple[str, ...]:
        """Exercise the actual formatter while exposing unnecessary recomputation.

        Args:
            geometry: The polygon geometry requested by a cache miss.

        Returns:
            Exact production boundary fragments.
        """
        self.calls.append(shapely.to_wkb(geometry, include_srid=True))
        return kml_io.geometry.geometry_boundaries(geometry)


class FailingStream:
    """Expose optional spill failures without changing the boundary renderer."""

    def __init__(self, *, short_write: bool = False) -> None:
        """Choose a short write or an I/O exception at the stream boundary.

        Args:
            short_write: Whether writes return zero instead of raising.
        """
        self.short_write = short_write
        self.position = 0

    def seek(self, position: int) -> None:
        """Accept positioning so failures occur during actual I/O.

        Args:
            position: The requested absolute byte position.
        """
        self.position = position

    def write(self, value: bytes) -> int:
        """Fail after the caller reserves capacity but before it can index bytes.

        Args:
            value: The complete encoded frame.

        Returns:
            Zero when short-write injection is selected.

        Raises:
            OSError: When exception injection is selected.
        """
        if self.short_write:
            return 0
        message = f"Spill write failed for {len(value)} bytes"
        raise OSError(message)

    def read(self, size: int) -> bytes:
        """Reject a read without allowing an unauthenticated cache result.

        Args:
            size: The requested frame length.

        Raises:
            OSError: Always, to exercise the optional read failure.
        """
        message = f"Spill read failed for {size} bytes at {self.position}"
        raise OSError(message)
