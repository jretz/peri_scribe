"""Isolate reading tests with explicit fixtures."""

from __future__ import annotations

import typing

import pytest

import peri_scribe.geo.package


if typing.TYPE_CHECKING:
    import pandas as pd


@pytest.fixture
def stub_geo_package(
    monkeypatch: pytest.MonkeyPatch,
) -> typing.Callable[[pd.DataFrame, dict[str, pd.DataFrame]], None]:
    """Point GeoPackage layer listing and reading at in-memory stand-ins.

    Args:
        monkeypatch: Replace dependencies and restore them after the test.

    Returns:
        A function that installs stand-ins serving the given layers table and per-layer
        dataframes.
    """

    def stub(layers: pd.DataFrame, dataframes: dict[str, pd.DataFrame]) -> None:
        """Install the layer metadata and contents used by GeoPackage readers.

        Args:
            layers: Layer-listing dataframe identifying the available GeoPackage layers.
            dataframes: Dataframe contents keyed by layer name.
        """
        monkeypatch.setattr(
            peri_scribe.geo.package.geopandas,
            "list_layers",
            lambda _path: layers,
        )
        monkeypatch.setattr(
            peri_scribe.geo.package.geopandas,
            "read_file",
            lambda _path, layer: dataframes[layer],
        )

    return stub
