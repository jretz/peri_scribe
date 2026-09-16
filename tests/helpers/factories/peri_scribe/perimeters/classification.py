"""Build inputs for classification tests."""

from __future__ import annotations

import datetime

import geopandas
import shapely.affinity
import shapely.geometry

import peri_scribe.models
import peri_scribe.perimeters.classification_data


CALIFORNIA_BOX_WGS84 = shapely.geometry.box(-126.0, 31.0, -119.0, 40.0)


CA_BORDER_WGS84 = shapely.geometry.LineString([(-119.0, 38.0), (-119.0, 40.0)])


def overlapping_observation_cases() -> list[
    tuple[list[shapely.Geometry], tuple[int, ...]]
]:
    """Keep fixed overlap cases independent of Hypothesis's example database.

    Returns:
        Source polygons and the order in which their observations repeat.
    """
    cases: list[tuple[list[shapely.Geometry], tuple[int, ...]]] = [
        (
            [
                shapely.Polygon([(-121, bottom), (-120, bottom), (-121, bottom + 1)]),
                shapely.Polygon(
                    shapely.box(-121, bottom, -119.5, bottom + 1.5).exterior,
                    [shapely.box(-120.5, bottom + 0.5, -120, bottom + 1).exterior],
                ),
            ],
            order,
        )
        for bottom, order in [(35, (0, 1)), (36, (1, 0, 0))]
    ]
    cases.append((
        [
            shapely.Polygon(
                shapely.box(left, 37, left + 1.5, 38.5).exterior,
                [shapely.box(left + 0.5, 37.5, left + 1, 38).exterior],
            )
            for left in (-120.5, -120)
        ],
        (0, 0, 1),
    ))
    return cases


def projected_boundaries() -> peri_scribe.perimeters.classification_data.Boundaries:
    """Place the synthetic state boundary in the classification's working projection.

    Returns:
        The synthetic California box and border in California Albers.
    """
    projected = geopandas.GeoSeries(
        [CALIFORNIA_BOX_WGS84, CA_BORDER_WGS84],
        crs=peri_scribe.models.WGS84_SPATIAL_REFERENCE_ID,
    ).to_crs(peri_scribe.models.CALIFORNIA_ALBERS_SPATIAL_REFERENCE_ID)
    return peri_scribe.perimeters.classification_data.Boundaries(
        box=projected.iloc[0],
        border=projected.iloc[1],
    )


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
