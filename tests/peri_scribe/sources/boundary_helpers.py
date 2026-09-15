"""Provide data builders and stand-ins for administrative boundaries tests."""

from __future__ import annotations

import pathlib
import typing

import arcgis.features
import geopandas
import pandas as pd
import pyproj
import shapely.geometry

import peri_scribe.sources.administrative_boundaries
import peri_scribe.sources.borders


if typing.TYPE_CHECKING:
    import pytest


CALIFORNIA = shapely.geometry.Polygon([(0, 0), (0, 10), (10, 10), (10, 0)])


ARIZONA = shapely.geometry.Polygon([(10, 0), (10, 10), (20, 10), (20, 0)])


NEVADA = shapely.geometry.Polygon([(0, 10), (0, 20), (10, 20), (10, 10)])


OREGON = shapely.geometry.Polygon([(-10, 0), (-10, 10), (0, 10), (0, 0)])


BASE_DIRECTORY = pathlib.Path("/boundaries")


OUTPUT_LAYER_NAME = peri_scribe.sources.administrative_boundaries.OUTPUT_LAYER_NAME


class FeatureLayerStub:
    """Minimal stand-in for an ArcGIS FeatureLayer with a fixed query result."""

    def __init__(self, feature_set: object) -> None:
        """Initialize a layer that captures queries and serves a fixed feature set.

        Args:
            feature_set: Feature set returned by the controlled query.
        """
        self.feature_set = feature_set
        self.queries: list[dict[str, object]] = []

    def query(self, **parameters: object) -> object:
        """Capture query parameters before serving the configured feature set.

        Args:
            parameters: Parameters supplied to the intercepted query or command.

        Returns:
            The feature set supplied to this stub.
        """
        self.queries.append(parameters)
        return self.feature_set


class FailingFeatureLayerStub:
    """FeatureLayer stand-in whose query always raises."""

    @staticmethod
    def query(**_parameters: object) -> object:
        """Simulate a failed administrative-boundary query.

        Args:
            _parameters: Query options accepted for compatibility with ArcGIS callers.

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


def polygon_feature_set(
    polygons: list[shapely.Polygon],
    names: list[str],
    abbreviations: list[str],
) -> arcgis.features.FeatureSet:
    """Build an ArcGIS FeatureSet from polygon geometries in WGS84.

    Args:
        polygons: Boundary polygons expressed in WGS84.
        names: Administrative names aligned with the polygon sequence.
        abbreviations: Optional state abbreviations aligned with the polygons.

    Returns:
        A FeatureSet whose features carry the named polygons in WGS84.
    """
    features = []
    for polygon, name, abbreviation in zip(polygons, names, abbreviations, strict=True):
        rings = [[list(coordinate) for coordinate in polygon.exterior.coords]]
        features.append(
            arcgis.features.Feature(
                geometry={"rings": rings, "spatialReference": {"wkid": 4326}},
                attributes={"STATE_NAME": name, "STATE_ABBR": abbreviation},
            ),
        )
    return arcgis.features.FeatureSet(features)


def good_border_dataframe() -> geopandas.GeoDataFrame:
    """Return the border GeoDataFrame for the sample neighboring states.

    Returns:
        The three shared borders in WGS84 with the expected columns.
    """
    neighbors = geopandas.GeoDataFrame(
        {
            "STATE_NAME": ["Arizona", "Nevada", "Oregon"],
            "STATE_ABBR": ["AZ", "NV", "OR"],
        },
        geometry=[ARIZONA, NEVADA, OREGON],
        crs=pyproj.CRS.from_epsg(4326),
    )
    return peri_scribe.sources.borders.border_dataframe(CALIFORNIA, neighbors)


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
        lambda _path, **_keywords: dataframe,
    )


def is_usable_dataframe(
    *,
    geometry: list[shapely.Geometry | None],
    crs: object | None = pyproj.CRS.from_epsg(4326),
) -> geopandas.GeoDataFrame:
    """Build a candidate border dataframe for the is_usable checks.

    Args:
        geometry: The border line geometries.
        crs: The dataframe's CRS, or None to omit it.

    Returns:
        The GeoDataFrame with the expected border columns.
    """
    return geopandas.GeoDataFrame(
        {
            "NEIGHBOR": ["Arizona", "Nevada", "Oregon"],
            "NEIGHBOR_ABBR": ["AZ", "NV", "OR"],
            "LENGTH_KM": [1.0, 2.0, 3.0],
        },
        geometry=geometry,
        crs=crs,
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
        lambda _path, **_keywords: dataframe,
    )


def california_like_border() -> shapely.geometry.MultiLineString:
    """Return a synthetic border shaped like California's interstate border.

    Returns:
        An Oregon segment across the top and a Nevada/Arizona segment down the east.
    """
    return shapely.geometry.MultiLineString([
        shapely.geometry.LineString([(-124.0, 42.0), (-120.0, 42.0)]),
        shapely.geometry.LineString([(-120.0, 42.0), (-114.0, 32.7)]),
    ])


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
