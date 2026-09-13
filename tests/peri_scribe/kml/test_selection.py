"""Area qualification uses the same evidence and history as the displayed estimate."""

from __future__ import annotations

import typing

import pytest

import peri_scribe.kml.selection
import tests.factories
from peri_scribe.units import units


if typing.TYPE_CHECKING:
    import geopandas


@pytest.fixture
def mapped_fire() -> geopandas.GeoDataFrame:
    """Provide a measured perimeter without supplied acreage for qualification tests.

    Returns:
        A dated, 100-acre mapping with its canonical fire identity.
    """
    return tests.factories.geo_frame(
        {
            "fire_name": ["Example"],
            "fire_identifier": ["example"],
            "observation_time": [tests.factories.utc(2026, 9, 1, 0)],
            "geometry_area_square_meters": [(100 * units.acres).m_as("meters**2")],
        },
        [tests.factories.square(0.01)],
    )


def test_fires_with_qualifying_area_includes_geometry_without_reported_acres(
    mapped_fire: geopandas.GeoDataFrame,
) -> None:
    assert peri_scribe.kml.selection.fires_with_qualifying_area(
        mapped_fire,
        mapped_fire.iloc[0:0],
        25 * units.acres,
    ) == {("id", "example")}


def test_fires_with_qualifying_area_includes_independent_incident_growth(
    mapped_fire: geopandas.GeoDataFrame,
) -> None:
    mapped_fire["geometry_area_square_meters"] = (10 * units.acres).m_as("meters**2")
    incidents = tests.factories.geo_frame(
        {
            "fire_identifier": ["alias"],
            "fire_name": ["Example"],
            "observation_time": [tests.factories.utc(2026, 9, 5, 0)],
            "report_confirmed": [False],
            "incident_size": [40],
        },
        [None],
    )
    assert peri_scribe.kml.selection.fires_with_qualifying_area(
        mapped_fire,
        mapped_fire.iloc[0:0],
        25 * units.acres,
        incidents,
        aliases={"alias": "example"},
    ) == {("id", "example")}


def test_fires_with_qualifying_area_does_not_split_alias_evidence(
    mapped_fire: geopandas.GeoDataFrame,
) -> None:
    mapped_fire["geometry_area_square_meters"] = (10 * units.acres).m_as("meters**2")
    points = tests.factories.geo_frame(
        {
            "fire_identifier": ["alias"],
            "fire_name": ["Example"],
            "observation_time": [tests.factories.utc(2026, 9, 2, 0)],
            "incident_size": [100],
        },
        [None],
    )
    assert not peri_scribe.kml.selection.fires_with_qualifying_area(
        mapped_fire,
        points,
        25 * units.acres,
        aliases={"alias": "example"},
    )


def test_fires_with_qualifying_area_keeps_historical_qualification(
    mapped_fire: geopandas.GeoDataFrame,
) -> None:
    mapped_fire.loc[1] = mapped_fire.iloc[0]
    mapped_fire.loc[1, "observation_time"] = tests.factories.utc(2026, 9, 5, 0)
    mapped_fire.loc[1, "geometry"] = tests.factories.square(0.001)
    mapped_fire.loc[1, "geometry_area_square_meters"] = (10 * units.acres).m_as(
        "meters**2",
    )
    assert peri_scribe.kml.selection.fires_with_qualifying_area(
        mapped_fire,
        mapped_fire.iloc[0:0],
        25 * units.acres,
    ) == {("id", "example")}
