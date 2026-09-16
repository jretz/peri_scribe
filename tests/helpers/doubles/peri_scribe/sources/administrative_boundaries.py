"""Replace administrative boundaries dependencies with controlled test doubles."""

from __future__ import annotations

import pathlib
import typing

import pandas as pd

import peri_scribe.sources.administrative_boundaries


if typing.TYPE_CHECKING:
    import arcgis.features
    import geopandas
    import pytest


class FeatureLayerStub:
    """Minimal stand-in for an ArcGIS FeatureLayer with a fixed query result."""

    def __init__(self, feature_set: object) -> None:
        """Initialize a layer that captures queries and serves a fixed feature set.

        Args:
            feature_set: Feature set returned by the controlled query.
        """
        self.feature_set = feature_set
        self.queries: list[dict[str, object]] = []

    def query(self, **kwargs: object) -> object:
        """Capture query parameters before serving the configured feature set.

        Args:
            kwargs: Parameters supplied to the intercepted query or command.

        Returns:
            The feature set supplied to this stub.
        """
        self.queries.append(kwargs)
        return self.feature_set


class FailingFeatureLayerStub:
    """FeatureLayer stand-in whose query always raises."""

    @staticmethod
    def query(**_kwargs: object) -> object:
        """Simulate a failed administrative-boundary query.

        Args:
            _kwargs: Query options accepted for compatibility with ArcGIS callers.

        Raises:
            RuntimeError: Always, to exercise query failure handling.
        """
        message = "boom"
        raise RuntimeError(message)


class GeometrylessFeatureSetStub:
    """FeatureSet stand-in whose dataframe carries no geometry column."""

    def __init__(self, count: int) -> None:
        """Initialize boundary attributes without geometry to exercise validation.

        Args:
            count: Number of boundary features to create without geometry.
        """
        self.features = [object()] * count
        self.sdf = pd.DataFrame({
            "STATE_NAME": [f"State {index}" for index in range(count)],
        })


def as_feature_layer(stub: object) -> arcgis.features.FeatureLayer:
    """Type *stub* as an ArcGIS FeatureLayer for the functions under test.

    Args:
        stub: Controlled layer object passed through the ArcGIS interface.

    Returns:
        The stub, statically typed as a FeatureLayer.
    """
    return typing.cast("arcgis.features.FeatureLayer", stub)


def stub_geopackage_reads(
    monkeypatch: pytest.MonkeyPatch,
    layer_names: list[str],
    dataframe: geopandas.GeoDataFrame,
) -> None:
    """Point the module's GeoPackage reads at in-memory stand-ins.

    Args:
        monkeypatch: Replace dependencies and restore them after the test.
        layer_names: Names exposed by the GeoPackage layer listing.
        dataframe: Boundary dataframe returned by the reader substitute.
    """
    monkeypatch.setattr(pathlib.Path, "is_file", lambda _self: True)
    monkeypatch.setattr(
        peri_scribe.sources.administrative_boundaries.geopandas,
        "list_layers",
        lambda _path: pd.DataFrame({"name": layer_names}),
    )
    monkeypatch.setattr(
        peri_scribe.sources.administrative_boundaries.geopandas,
        "read_file",
        lambda _path, **_kwargs: dataframe,
    )


def stub_border_file(
    monkeypatch: pytest.MonkeyPatch,
    dataframe: geopandas.GeoDataFrame,
) -> None:
    """Point load_border_geometry's file reads at *dataframe*.

    Args:
        monkeypatch: The monkeypatch fixture.
        dataframe: The stored border dataframe.
    """
    monkeypatch.setattr(
        peri_scribe.sources.administrative_boundaries,
        "output_geopackage_path",
        lambda _year_directory: pathlib.Path("/data/border.gpkg"),
    )
    monkeypatch.setattr(
        peri_scribe.sources.administrative_boundaries.geopandas,
        "read_file",
        lambda _path, **_kwargs: dataframe,
    )


def fail_layer_listing(_path: object) -> typing.Never:
    """Simulate an unreadable GeoPackage during usability checks.

    Args:
        _path: File path accepted for compatibility; the configured stub outcome is
            used.

    Raises:
        RuntimeError: Always, to exercise unreadable-file handling.
    """
    message = "corrupt"
    raise RuntimeError(message)


def make_layer_factory(
    *,
    state_set: arcgis.features.FeatureSet,
) -> typing.Callable[..., FeatureLayerStub]:
    """Create a callback with controlled dependencies.

    Provide controlled state boundaries for the requested layer.

    Args:
        state_set: Controlled state boundaries returned for the configured layer URL.

    Returns:
        The callback bound to the supplied dependencies.
    """

    def layer_factory(url: str, gis: object) -> FeatureLayerStub:
        """Provide controlled state boundaries for the requested layer.

        Args:
            url: ArcGIS layer or download URL supplied by the caller.
            gis: GIS connection object supplied to the layer constructor.

        Returns:
            A layer stub serving the matching boundary feature set.

        Raises:
            AssertionError: If the requested URL is not the configured state layer.
        """
        if url == peri_scribe.sources.administrative_boundaries.NEIGHBOR_LAYER_URL:
            return FeatureLayerStub(state_set)
        raise AssertionError(url)

    return layer_factory
