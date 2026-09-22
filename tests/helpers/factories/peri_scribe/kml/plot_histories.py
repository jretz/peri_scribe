"""Build inputs for plot histories tests."""

from __future__ import annotations

import datetime
import typing

import shapely.geometry

import tests.helpers.factories.geography


if typing.TYPE_CHECKING:
    import geopandas


def perimeter_frame_from_observations(
    observations: list[
        tuple[
            datetime.datetime | None,
            shapely.Geometry,
            float | None,
            float | None,
            float | None,
            float | None,
        ]
    ],
) -> geopandas.GeoDataFrame:
    """Build a perimeter history frame.

    Each observation is (observation_time, geometry, area_acres, percent_contained,
    estimated_cost_to_date, estimated_final_cost).

    Args:
        observations: One tuple per perimeter row.

    Returns:
        The perimeter history frame.
    """
    return tests.helpers.factories.geography.geo_frame(
        {
            "fire_identifier": ["id-bug"] * len(observations),
            "fire_name": ["Bug"] * len(observations),
            "observation_time": [row[0] for row in observations],
            "modified_time": [row[0] for row in observations],
            "area_acres": [row[2] for row in observations],
            "percent_contained": [row[3] for row in observations],
            "estimated_cost_to_date": [row[4] for row in observations],
            "estimated_final_cost": [row[5] for row in observations],
        },
        [row[1] for row in observations],
    )


def point_frame_from_observations(
    observations: list[
        tuple[datetime.datetime | None, float | None, float | None, float | None]
    ],
) -> geopandas.GeoDataFrame:
    """Build a point history frame.

    Each observation is (observation_time, incident_size, estimated_cost_to_date,
    estimated_final_cost).

    Args:
        observations: One tuple per point row.

    Returns:
        The point history frame.
    """
    return tests.helpers.factories.geography.geo_frame(
        {
            "fire_identifier": ["id-bug"] * len(observations),
            "fire_name": ["Bug"] * len(observations),
            "observation_time": [row[0] for row in observations],
            "incident_size": [row[1] for row in observations],
            "estimated_cost_to_date": [row[2] for row in observations],
            "estimated_final_cost": [row[3] for row in observations],
        },
        [shapely.geometry.Point(0.0, 0.0)] * len(observations),
    )
