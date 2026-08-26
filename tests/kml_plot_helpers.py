"""Shared helpers for the KML plot test modules.

These helpers build the series points and history frames the plot functions read.
"""

from __future__ import annotations

import datetime

import geopandas
import shapely.geometry

import peri_scribe.kml_plot_data
import peri_scribe.units


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def square(side: float) -> shapely.geometry.Polygon:
    """Return a square of *side* degrees centered at the origin.

    Args:
        side: The length of each side.

    Returns:
        The square.
    """
    half = side / 2
    return shapely.geometry.box(-half, -half, half, half)


def exterior_length(geometry: shapely.Geometry) -> float:
    """Return *geometry*'s exterior perimeter length, which is always known.

    Args:
        geometry: A non-empty polygon.

    Returns:
        The exterior perimeter length in miles.
    """
    length = peri_scribe.units.exterior_perimeter_in_miles(geometry)
    assert length is not None
    return length


def observation_time(day: int, hour: int = 0) -> datetime.datetime:
    """Return an aware UTC observation time on August *day*.

    Args:
        day: The day of the month.
        hour: The hour of the day.

    Returns:
        The observation time.
    """
    return datetime.datetime(2026, 8, day, hour, tzinfo=datetime.UTC)


def series_point(
    day: int,
    value: float,
    hour: int = 0,
) -> peri_scribe.kml_plot_data.SeriesPoint:
    """Return a series point at *day* with *value*.

    Args:
        day: The day of the observation.
        value: The measurement.
        hour: The hour of the observation.

    Returns:
        The point.
    """
    return peri_scribe.kml_plot_data.SeriesPoint(
        observation_time=observation_time(day, hour),
        value=value,
    )


def geo_frame(
    columns: dict[str, list[object]],
    geometry: list[shapely.Geometry],
) -> geopandas.GeoDataFrame:
    """Build a WGS84 GeoDataFrame from *columns* and *geometry*.

    Args:
        columns: Each column name and its row values.
        geometry: The geometry of each row.

    Returns:
        The frame.
    """
    return geopandas.GeoDataFrame(
        columns,
        geometry=geometry,
        crs="EPSG:4326",
    )


def perimeter_frame(
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
    return geo_frame(
        {
            "fire_identifier": ["id-bug"] * len(observations),
            "fire_name": ["Bug"] * len(observations),
            "observation_time": [row[0] for row in observations],
            "area_acres": [row[2] for row in observations],
            "percent_contained": [row[3] for row in observations],
            "estimated_cost_to_date": [row[4] for row in observations],
            "estimated_final_cost": [row[5] for row in observations],
        },
        [row[1] for row in observations],
    )


def point_frame(
    observations: list[
        tuple[
            datetime.datetime | None,
            float | None,
            float | None,
            float | None,
        ]
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
    return geo_frame(
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
