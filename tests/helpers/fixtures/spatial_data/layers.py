"""Isolate spatial layer tests with explicit fixtures."""

from __future__ import annotations

import typing

import pytest

import spatial_data.layers
import tests.helpers.factories.geography


@pytest.fixture
def layer_data_factory() -> typing.Callable[[str], spatial_data.layers.LayerData]:
    """Build LayerData entries with two point features in WGS84.

    Returns:
        A factory for LayerData entries with two point features in WGS84.
    """

    def make_layer_data(name: str) -> spatial_data.layers.LayerData:
        """Build a named sample layer for GeoPackage writer tests.

        Args:
            name: Name assigned to the selected layer or source.

        Returns:
            The named layer containing the sample point dataframe.
        """
        return spatial_data.layers.LayerData(
            name=name,
            dataframe=tests.helpers.factories.geography.sample_geo_dataframe(),
        )

    return make_layer_data
