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
