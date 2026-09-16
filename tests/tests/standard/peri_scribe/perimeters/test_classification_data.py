"""Tests for peri_scribe.perimeters.classification_data."""

from __future__ import annotations

import pytest
import shapely.geometry

import peri_scribe.perimeters.classification_data


def test_reproject_to_california_albers_returns_projected_geometry() -> None:
    point = shapely.geometry.Point(-120.0, 39.0)
    result = peri_scribe.perimeters.classification_data.reproject_to_california_albers(
        point,
        4326,
    )
    assert isinstance(result, shapely.geometry.Point)
    assert result != point


def test_reproject_to_california_albers_preserves_z_coordinates() -> None:
    point = shapely.geometry.Point(-120.0, 39.0, 123.0)
    result = peri_scribe.perimeters.classification_data.reproject_to_california_albers(
        point,
        4326,
    )
    assert isinstance(result, shapely.geometry.Point)
    assert result.z == pytest.approx(123.0)
