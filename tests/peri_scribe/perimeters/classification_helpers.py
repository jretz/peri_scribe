"""Provide data builders and stand-ins for border classification tests."""

from __future__ import annotations

import datetime
import typing

import shapely.geometry

import peri_scribe.models


CALIFORNIA_BOX_WGS84 = shapely.geometry.box(-126.0, 31.0, -119.0, 40.0)


CA_BORDER_WGS84 = shapely.geometry.LineString([(-119.0, 38.0), (-119.0, 40.0)])


def classifiable_record(
    *,
    geometry: shapely.geometry.base.BaseGeometry,
    observed_at: datetime.datetime | None = None,
    identifiers: frozenset[str] = frozenset(),
    mission: str | None = None,
    point_of_origin_state: str | None = None,
    point_of_origin_fips: str | None = None,
) -> peri_scribe.models.FireRecord:
    """Build a fire record for classification tests.

    Args:
        geometry: Geometry supplied for the selected spatial case.
        observed_at: Observation time attached to the mapping, or None if unknown.
        identifiers: Fire identifiers supplied for identity matching.
        mission: Mapping mission identifier, or None when unavailable.
        point_of_origin_state: Reported origin state, or None when unavailable.
        point_of_origin_fips: Reported origin FIPS code, or None when unavailable.

    Returns:
        The fire record, named "Fire" and active.
    """
    return peri_scribe.models.FireRecord(
        name="Fire",
        status=peri_scribe.models.FireStatus.ACTIVE,
        identifiers=identifiers,
        geometry=geometry,
        observed_at=observed_at,
        mission=mission,
        point_of_origin_state=point_of_origin_state,
        point_of_origin_fips=point_of_origin_fips,
    )


def make_union_recorder(
    *,
    union_inputs: list[list[shapely.Geometry]],
    original_union_all: typing.Callable[..., shapely.Geometry],
) -> typing.Callable[..., shapely.Geometry]:
    """Create a callback with controlled dependencies.

    Capture union inputs to verify observation deduplication.

    Args:
        union_inputs: Shared list recording the geometries supplied to each union.
        original_union_all: Original union operation used to preserve geometric results.

    Returns:
        The callback bound to the supplied dependencies.
    """

    def recording_union_all(geometries: list[shapely.Geometry]) -> shapely.Geometry:
        """Capture union inputs to verify observation deduplication.

        Args:
            geometries: Geometries supplied to the union operation.

        Returns:
            The union of the supplied geometries.
        """
        union_inputs.append(list(geometries))
        return original_union_all(geometries)

    return recording_union_all


def make_reproject_recorder(
    *,
    reprojected: list[tuple[int, bytes]],
    original: typing.Callable[..., shapely.Geometry],
) -> typing.Callable[..., shapely.Geometry]:
    """Create a callback with controlled dependencies.

    Capture reprojection inputs to verify source-specific geometry handling.

    Args:
        reprojected: Shared list recording destination references and input geometry
            bytes.
        original: Original operation whose results the callback preserves.

    Returns:
        The callback bound to the supplied dependencies.
    """

    def recording_reproject(geometry: shapely.Geometry, wkid: int) -> shapely.Geometry:
        """Capture reprojection inputs to verify source-specific geometry handling.

        Args:
            geometry: Geometry supplied for the selected spatial case.
            wkid: Identifier of the requested destination coordinate system.

        Returns:
            The geometry projected into the requested coordinate system.
        """
        reprojected.append((wkid, geometry.wkb))
        return original(geometry, wkid)

    return recording_reproject
