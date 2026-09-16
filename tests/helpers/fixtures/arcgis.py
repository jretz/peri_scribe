"""Isolate arcgis tests with explicit fixtures."""

from __future__ import annotations

import typing

import pytest

import tests.helpers.factories.arcgis


if typing.TYPE_CHECKING:
    import arcgis.features


@pytest.fixture
def feature_set_with_geometry() -> arcgis.features.FeatureSet:
    """Provide point features with a known WGS84 spatial reference.

    Returns:
        A FeatureSet with two point features in WGS84.
    """
    return tests.helpers.factories.arcgis.wgs84_feature_set([
        (None, "a", 1.0, 2.0),
        (None, "b", 3.0, 4.0),
    ])
