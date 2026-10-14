"""Filtering out implausibly small reported perimeters.

[Geometry policy](../../../docs/algorithms/perimeter-geometry-policy.md)
"""

from __future__ import annotations

import dataclasses
import typing

import peri_scribe.perimeters.history_attributes
import peri_scribe.perimeters.versions
import spatial_data.measurements
from measurement_units import units


if typing.TYPE_CHECKING:
    import pint
    import shapely


COMPUTED_AREA_COLUMNS = ("poly_Acres_AutoCalc", "poly_GISAcres", "area_acres")


INCIDENT_SIZE_COLUMNS = ("attr_IncidentSize", "attr_FinalAcres")


@dataclasses.dataclass(frozen=True, kw_only=True)
class PerimeterSizeFilterConfig:
    """Thresholds for identifying a perimeter whose geometry has collapsed.

    Drop a perimeter when its measured area falls below a configured fraction of the
    size reported on the same row. The source's computed polygon area should be close to
    the measured geometry. Incident size can legitimately run ahead of mapping,
    especially early in a fire, so it takes a much larger discrepancy to reject a
    perimeter on that evidence.
    """

    minimum_computed_area_fraction: float = 0.2
    minimum_incident_area_fraction: float = 0.01


DEFAULT_SIZE_FILTER_CONFIG = PerimeterSizeFilterConfig()


def geometry_area(geometry: shapely.Geometry | None) -> pint.Quantity[float] | None:
    """Return *geometry*'s area, or None when it has none.

    Measure on the WGS84 ellipsoid rather than treating degrees as planar distances.

    Args:
        geometry: The perimeter geometry, in degree coordinates, or None.

    Returns:
        The absolute area, or None when *geometry* is missing or empty.
    """
    if geometry is None or geometry.is_empty:
        return None
    return spatial_data.measurements.area(geometry)


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

    A human report can describe growth that the perimeter has not yet mapped. Allow a
    much larger discrepancy against this value than against the source's computed
    polygon area before treating the geometry as collapsed.

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
    """Return whether the measured perimeter is implausibly small for its reported size.

    Compare the measured geometry with both the source's computed polygon area and the
    incident's reported size. The first can reveal a polygon that shrank while its
    stored area stayed the same. The second can reveal a polygon and stored area that
    shrank together, but requires a much larger discrepancy because reported growth can
    legitimately precede mapping.

    Args:
        observation: The perimeter observation to judge.
        config: The size-filter thresholds.

    Returns:
        True when the geometry has area but is smaller than one of the configured
        fractions of the row's reported sizes.
    """
    return area_is_implausibly_small(
        geometry_area(observation.geometry),
        observation.attributes,
        config,
    )


def area_is_implausibly_small(
    measured: pint.Quantity[float] | None,
    attributes: dict[str, object],
    config: PerimeterSizeFilterConfig = DEFAULT_SIZE_FILTER_CONFIG,
) -> bool:
    """Share collapse thresholds with callers that already measured the geometry.

    Args:
        measured: The measured perimeter area, or None when it is unavailable.
        attributes: The source row's reported polygon and incident sizes.
        config: The size-filter thresholds.

    Returns:
        Whether the measured area is implausibly small relative to a reported size.
    """
    if measured is None:
        return False
    computed = computed_area(attributes)
    incident = incident_size(attributes)
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
        The observations not rejected by the size thresholds, in input order.
    """
    return [
        observation
        for observation in observations
        if not perimeter_is_implausibly_small(observation, config)
    ]
