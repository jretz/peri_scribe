"""Tests for peri_scribe.perimeters.border_classification."""

from __future__ import annotations

import datetime
import typing

import peri_scribe.perimeters.border_classification


FIRIS = peri_scribe.perimeters.border_classification.FireSourceKind.FIRIS_PERIMETER

WFIGS_PERIMETER = (
    peri_scribe.perimeters.border_classification.FireSourceKind.WFIGS_PERIMETER
)

WFIGS_LOCATION = (
    peri_scribe.perimeters.border_classification.FireSourceKind.WFIGS_LOCATION
)


if typing.TYPE_CHECKING:
    import shapely.geometry


def observation(
    source: peri_scribe.perimeters.border_classification.FireSourceKind,
    geometry: shapely.geometry.base.BaseGeometry | None,
    *,
    observed_at: datetime.datetime | None = None,
    serial_number: int = 0,
    identifiers: frozenset[str] = frozenset(),
    mission: str | None = None,
    point_of_origin_state: str | None = None,
    point_of_origin_fips: str | None = None,
) -> peri_scribe.perimeters.border_classification.FireObservation:
    """Build a fire observation for a test.

    Returns:
        The fire observation.
    """
    return peri_scribe.perimeters.border_classification.FireObservation(
        source=source,
        geometry=geometry,
        observed_at=observed_at,
        serial_number=serial_number,
        identifiers=identifiers,
        mission=mission,
        point_of_origin_state=point_of_origin_state,
        point_of_origin_fips=point_of_origin_fips,
    )


def geometry_signal(
    *,
    distance_to_boundary_in_meters: float = 100.0,
    outside_area_fraction: float = 0.0,
    outside_area_in_acres: float = 0.0,
    inside_area_fraction: float = 1.0,
    crosses: bool = False,
    near: bool = False,
    inside: bool = True,
) -> peri_scribe.perimeters.border_classification.GeometrySignal:
    """Build a geometry signal, defaulting to a fire fully inside California.

    Returns:
        The geometry signal.
    """
    return peri_scribe.perimeters.border_classification.GeometrySignal(
        distance_to_boundary_in_meters=distance_to_boundary_in_meters,
        outside_area_fraction=outside_area_fraction,
        outside_area_in_acres=outside_area_in_acres,
        inside_area_fraction=inside_area_fraction,
        crosses=crosses,
        near=near,
        inside=inside,
    )


def extent_signal(
    *,
    wfigs_to_firis_area_ratio: float | None = None,
    disagrees: bool = False,
) -> peri_scribe.perimeters.border_classification.ExtentSignal:
    """Build an extent signal, defaulting to no disagreement.

    Returns:
        The extent signal.
    """
    return peri_scribe.perimeters.border_classification.ExtentSignal(
        wfigs_to_firis_area_ratio=wfigs_to_firis_area_ratio,
        disagrees=disagrees,
    )
