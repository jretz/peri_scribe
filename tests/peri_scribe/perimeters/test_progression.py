"""Tests for peri_scribe.perimeters.progression."""

from __future__ import annotations

import datetime

import pytest

import peri_scribe.perimeters.progression
import tests.factories
from peri_scribe.units import units


def test_ring_carries_its_geometry_time_and_area() -> None:
    observation_time = datetime.datetime(2026, 8, 5, 20, 30, tzinfo=datetime.UTC)
    ring = peri_scribe.perimeters.progression.Ring(
        geometry=tests.factories.square(1.0),
        observation_time=observation_time,
        area=42.5 * units.meters**2,
    )
    assert ring.geometry == tests.factories.square(1.0)
    assert ring.observation_time == observation_time
    assert ring.area.m_as("meters ** 2") == pytest.approx(42.5)


def test_ring_defaults_to_zero_area() -> None:
    ring = peri_scribe.perimeters.progression.Ring(
        geometry=tests.factories.square(1.0),
        observation_time=None,
    )
    assert ring.area.m_as("meters ** 2") == pytest.approx(0.0)
