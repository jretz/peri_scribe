"""Filtering out implausibly small reported perimeters."""

from __future__ import annotations

import dataclasses
import typing

import peri_scribe.perimeters.history_attributes
import peri_scribe.perimeters.versions
import peri_scribe.units
from peri_scribe.units import units


if typing.TYPE_CHECKING:
    import pint
    import shapely


COMPUTED_AREA_COLUMNS = (
    "poly_Acres_AutoCalc",
    "poly_GISAcres",
    "area_acres",
)


INCIDENT_SIZE_COLUMNS = (
    "attr_IncidentSize",
    "attr_FinalAcres",
)


@dataclasses.dataclass(frozen=True, kw_only=True)
class PerimeterSizeFilterConfig:
    """Thresholds for dropping a perimeter whose geometry collapsed.

    A perimeter is dropped when its geometry area is smaller than one of these
    fractions of the size the source reports for the same row. The computed-area
    fraction is generous because the polygon's computed area should match its
    geometry; the incident-size fraction is strict because the incident size
    legitimately runs ahead of the mapped extent early in a fire.
    """

    minimum_computed_area_fraction: float = 0.2
    minimum_incident_area_fraction: float = 0.01


DEFAULT_SIZE_FILTER_CONFIG = PerimeterSizeFilterConfig()


def geometry_area(geometry: shapely.Geometry | None) -> pint.Quantity[float] | None:
    """Return *geometry*'s area, or None when it has none.

    The area is computed geodesically so it is accurate anywhere on Earth.

    Args:
        geometry: The perimeter geometry, in degree coordinates, or None.

    Returns:
        The absolute area, or None when *geometry* is missing or empty.
    """
    if geometry is None or geometry.is_empty:
        return None
    return peri_scribe.units.area(geometry)


def computed_area(attributes: dict[str, object]) -> pint.Quantity[float] | None:
    """Return the polygon's computed area for one row, in acres.

    The computed-area columns hold the source's own area for the polygon, so a healthy
    row's geometry should nearly equal this value.

    Args:
        attributes: The row's attributes.

    Returns:
        The first positive computed area in acres, or None when the row reports none.
    """
    for column in COMPUTED_AREA_COLUMNS:
        value = peri_scribe.perimeters.history_attributes.float_attribute(
            attributes,
            column,
        )
        if value is not None and value > 0:
            return value * units.acres
    return None


def incident_size(attributes: dict[str, object]) -> pint.Quantity[float] | None:
    """Return the incident's reported size for one row, in acres.

    The incident size is a human report that can outrun the mapped perimeter, so it is
    only used as a collapse reference with a much stricter threshold.

    Args:
        attributes: The row's attributes.

    Returns:
        The first positive incident size in acres, or None when the row reports none.
    """
    for column in INCIDENT_SIZE_COLUMNS:
        value = peri_scribe.perimeters.history_attributes.float_attribute(
            attributes,
            column,
        )
        if value is not None and value > 0:
            return value * units.acres
    return None


def perimeter_is_implausibly_small(
    observation: peri_scribe.perimeters.versions.SourceObservation,
    config: PerimeterSizeFilterConfig = DEFAULT_SIZE_FILTER_CONFIG,
) -> bool:
    """Return whether *observation*'s geometry collapsed below its reported size.

    The geometry is judged against the polygon's computed area and, more strictly,
    against the incident's reported size. Either reference can reveal a collapse: the
    computed area when the polygon alone shrank, and the incident size when the polygon
    and its computed area shrank together.

    Args:
        observation: The perimeter observation to judge.
        config: The size-filter thresholds.

    Returns:
        True when the geometry has area but is smaller than one of the configured
        fractions of the row's reported sizes.
    """
    measured = geometry_area(observation.geometry)
    if measured is None:
        return False
    computed = computed_area(observation.attributes)
    incident = incident_size(observation.attributes)
    return (
        computed is not None
        and measured < config.minimum_computed_area_fraction * computed
    ) or (
        incident is not None
        and measured < config.minimum_incident_area_fraction * incident
    )


def drop_implausibly_small_perimeters(
    observations: list[peri_scribe.perimeters.versions.SourceObservation],
    config: PerimeterSizeFilterConfig = DEFAULT_SIZE_FILTER_CONFIG,
) -> list[peri_scribe.perimeters.versions.SourceObservation]:
    """Return *observations* without perimeters whose geometry collapsed.

    Args:
        observations: The reconciled perimeter versions for one fire.
        config: The size-filter thresholds.

    Returns:
        The observations whose geometry matches their reported size, in order.
    """
    return [
        observation
        for observation in observations
        if not perimeter_is_implausibly_small(observation, config)
    ]
