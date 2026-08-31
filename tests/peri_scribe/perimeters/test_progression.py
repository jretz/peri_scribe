"""Tests for peri_scribe.perimeters.progression."""

from __future__ import annotations

import datetime

import pytest
import shapely.geometry

import peri_scribe.perimeters.progression


def square(side: float) -> shapely.geometry.Polygon:
    """Return a square of the given side, centered at the origin.

    Args:
        side: The length of each side.

    Returns:
        The square.
    """
    half = side / 2
    return shapely.geometry.box(-half, -half, half, half)


def test_ring_carries_its_geometry_time_and_area() -> None:
    observation_time = datetime.datetime(2026, 8, 5, 20, 30, tzinfo=datetime.UTC)
    ring = peri_scribe.perimeters.progression.Ring(
        geometry=square(1.0),
        observation_time=observation_time,
        area=42.5,
    )
    assert ring.geometry == square(1.0)
    assert ring.observation_time == observation_time
    assert ring.area == pytest.approx(42.5)


def test_ring_defaults_to_zero_area() -> None:
    ring = peri_scribe.perimeters.progression.Ring(
        geometry=square(1.0),
        observation_time=None,
    )
    assert ring.area == pytest.approx(0.0)
