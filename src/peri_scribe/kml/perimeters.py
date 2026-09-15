"""Shared perimeter observations for selection and presentation."""

from __future__ import annotations

import dataclasses
import typing

import peri_scribe.units


if typing.TYPE_CHECKING:
    import datetime

    import pint
    import shapely


@dataclasses.dataclass(frozen=True, kw_only=True)
class Perimeter:
    """One perimeter geometry and the time it was observed."""

    geometry: shapely.Geometry
    observation_time: datetime.datetime | None
    area: pint.Quantity[float] | None = None
    added_area: pint.Quantity[float] | None = None
    sequence_digest: str | None = None

    @property
    def measured_area(self) -> pint.Quantity[float]:
        """Share stored measurements while supporting standalone history layers.

        Returns:
            The perimeter area as a unit-aware quantity, using stored measurements when
            available.
        """
        return peri_scribe.units.area(self.geometry) if self.area is None else self.area
