"""Isolate fire data tests with explicit fixtures."""

from __future__ import annotations

import functools
import typing

import pytest

import peri_scribe.kml.fire_data
import tests.helpers.factories.geography
import tests.helpers.factories.geometry
import tests.helpers.factories.time
from peri_scribe.units import units


if typing.TYPE_CHECKING:
    import geopandas


@pytest.fixture
def isolated_added_area_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep cache assertions independent of rings processed by other tests.

    Args:
        monkeypatch: Replace dependencies and restore them after the test.
    """
    monkeypatch.setattr(
        peri_scribe.kml.fire_data,
        "added_areas_for_rings",
        functools.cache(peri_scribe.kml.fire_data.added_areas_for_rings.__wrapped__),
    )


@pytest.fixture
def mapped_fire() -> geopandas.GeoDataFrame:
    """Provide a measured perimeter without supplied acreage for qualification tests.

    Returns:
        A dated, 100-acre mapping with its canonical fire identity.
    """
    return tests.helpers.factories.geography.geo_frame(
        {
            "fire_name": ["Example"],
            "fire_identifier": ["example"],
            "observation_time": [tests.helpers.factories.time.utc(2026, 9, 1, 0)],
            "geometry_area_square_meters": [(100 * units.acres).m_as("meters**2")],
        },
        [tests.helpers.factories.geometry.square(0.01)],
    )
