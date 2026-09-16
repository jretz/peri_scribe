"""Tests for peri_scribe.report.locations."""

from __future__ import annotations

import math
import typing

import hypothesis
import hypothesis.strategies
import pytest
import shapely

import peri_scribe.report.locations
import tests.helpers.factories.peri_scribe.report.locations
import tests.helpers.strategies.peri_scribe.report.locations


if typing.TYPE_CHECKING:
    import geopandas


@hypothesis.given(
    longitude=hypothesis.strategies.floats(-180, 180),
    latitude=hypothesis.strategies.floats(-80, 80),
    azimuth=hypothesis.strategies.integers(0, 359),
    meters=hypothesis.strategies.integers(10, 1_000_000),
)
def test_distance_and_bearing_from_point_recovers_geodesic_journey(
    longitude: float,
    latitude: float,
    azimuth: int,
    meters: int,
) -> None:
    destination_longitude, destination_latitude, _back_azimuth = (
        tests.helpers.factories.peri_scribe.report.locations.GEODESIC.fwd(
            longitude,
            latitude,
            azimuth,
            meters,
        )
    )
    distance, bearing = peri_scribe.report.locations.distance_and_bearing_from_point(
        shapely.Point(destination_longitude, destination_latitude),
        longitude,
        latitude,
    )
    assert distance.m_as("meters") == pytest.approx(meters, abs=1e-3, rel=1e-9)
    assert bearing is not None
    angular_error = (bearing.m_as("degrees") - azimuth + 180) % 360 - 180
    # A millimeter of projection error affects short journeys' bearings more strongly.
    assert angular_error == pytest.approx(0, abs=max(1e-8, math.degrees(1e-3 / meters)))


# This test is slow, so limit examples to keep routine test runs fast.
@hypothesis.settings(max_examples=25)
@hypothesis.given(
    scenario=tests.helpers.strategies.peri_scribe.report.locations.city_queries(),
)
def test_nearest_city_matches_exhaustive_search(
    scenario: tuple[
        shapely.Geometry,
        geopandas.GeoDataFrame,
        list[tuple[str, str, shapely.Point]],
    ],
) -> None:
    geometry, cities, usable = scenario
    distances = {
        (name, state): peri_scribe.report.locations.distance_and_bearing_from_point(
            geometry,
            point.x,
            point.y,
        )[0].m_as("meters")
        for name, state, point in usable
    }
    expected = min(distances, key=lambda key: (distances[key], *key))
    actual = peri_scribe.report.locations.nearest_city(geometry, cities)
    assert actual is not None
    assert (actual.name, actual.state_abbreviation) == expected
    assert actual.distance.m_as("meters") == pytest.approx(
        distances[expected],
        abs=1e-6,
    )
