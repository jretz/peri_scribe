"""Provide isolated fixtures for this test package."""

from __future__ import annotations

import datetime
import functools
import typing

import pytest

import peri_scribe.kml.fire_data
import peri_scribe.kml.plot_data
import peri_scribe.kml.styles
import tests.factories
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
def style_urls() -> dict[str, str]:
    """Provide production placemark styles for folder assertions.

    Returns:
        The placemark style URLs keyed by style name.
    """
    return peri_scribe.kml.styles.PLACEMARK_STYLE_URLS


@pytest.fixture
def intraday_series() -> tuple[peri_scribe.kml.plot_data.PlotSeries, ...]:
    """Expose date truncation through distinct, equally spaced readings within one day.

    Returns:
        One area series with morning, midday, and evening observations.
    """
    return (
        peri_scribe.kml.plot_data.PlotSeries(
            label="Area",
            points=tuple(
                peri_scribe.kml.plot_data.SeriesPoint(
                    observation_time=datetime.datetime(
                        2026,
                        9,
                        3,
                        hour,
                        tzinfo=datetime.UTC,
                    ),
                    value=value,
                )
                for hour, value in ((6, 100.0), (12, 500.0), (18, 200.0))
            ),
        ),
    )


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
