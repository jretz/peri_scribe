"""Isolate models tests with explicit fixtures."""

from __future__ import annotations

import typing

import pytest

import peri_scribe.models
import tests.helpers.factories.geography


@pytest.fixture
def layer_data_factory() -> typing.Callable[[str], peri_scribe.models.LayerData]:
    """Build LayerData entries with two point features in WGS84.

    Returns:
        A factory for LayerData entries with two point features in WGS84.
    """

    def make_layer_data(name: str) -> peri_scribe.models.LayerData:
        """Build a named sample layer for GeoPackage writer tests.

        Args:
            name: Name assigned to the selected layer or source.

        Returns:
            The named layer containing the sample point dataframe.
        """
        return peri_scribe.models.LayerData(
            name=name,
            dataframe=tests.helpers.factories.geography.sample_geo_dataframe(),
        )

    return make_layer_data
