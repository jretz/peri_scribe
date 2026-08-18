from __future__ import annotations

import pathlib
import typing

import arcgis.features
import click.testing
import geopandas
import pyproj
import pyproj.exceptions
import pytest
import shapely.geometry

import peri_scribe.feed_types
import peri_scribe.geo_data
import peri_scribe.models
import peri_scribe.operations
import peri_scribe.output


if typing.TYPE_CHECKING:
    import pandas as pd


WGS84_WKID = 4326
WEB_MERCATOR_WKID = 3857
CALIFORNIA_ALBERS_WKID = 3310
NAD83_WKID = 4269
NAVD88_HEIGHT_WKID = 5703
UNKNOWN_WKID = 999999

WEB_MERCATOR_MAXIMUM_MAGNITUDE = 20048966.104014598

CLICK_USAGE_ERROR_EXIT_CODE = 2

SAMPLE_FEED_URL = (
    "https://example.test/ArcGIS/rest/services/Fire_Layers/FeatureServer/3"
)
SAMPLE_PATH_SEGMENTS = [
    "ArcGIS",
    "rest",
    "services",
    "Fire_Layers",
    "FeatureServer",
    "3",
]
SAMPLE_SERVICE_NAME = "Fire_Layers"
SAMPLE_LAYER_ID = 3
SAMPLE_FEED_NAME = "Fire_Layers_3"
SAMPLE_FIRE_NAME_COLUMN = "name"
SAMPLE_STATUS_COLUMN = "status"


def sample_feed_config() -> dict[str, str]:
    """A feed configuration for the sample ArcGIS feed.

    Returns:
        The configuration for the sample ArcGIS feed.
    """
    return {
        "feed_type": "ArcGISFeed",
        "url": SAMPLE_FEED_URL,
        "fire_name_column": SAMPLE_FIRE_NAME_COLUMN,
        "status_column": SAMPLE_STATUS_COLUMN,
    }


class LayerStub(arcgis.features.FeatureLayer):
    """Minimal stand-in for an ArcGIS FeatureLayer exposing properties."""

    def __init__(self, properties: dict[str, object]) -> None:
        self.layer_properties = properties

    @property
    def properties(self) -> dict[str, object]:
        return self.layer_properties


class FeatureSetStub(arcgis.features.FeatureSet):
    """Minimal stand-in for an ArcGIS FeatureSet exposing spatial_reference."""

    def __init__(self, spatial_reference: object) -> None:
        self.stored_spatial_reference = spatial_reference

    @property
    def spatial_reference(self) -> object:
        return self.stored_spatial_reference


class FeatureLayerStub:
    """Minimal stand-in for an ArcGIS FeatureLayer with a fixed query result."""

    def __init__(
        self,
        url: str,
        gis: object,
        feature_set: arcgis.features.FeatureSet,
        query_error: Exception | None = None,
    ) -> None:
        self.url = url
        self.gis = gis
        self.feature_set = feature_set
        self.query_error = query_error
        self.layer_properties: dict[str, object] = {
            "spatialReference": {"wkid": WGS84_WKID},
        }

    @property
    def properties(self) -> dict[str, object]:
        return self.layer_properties

    def query(self) -> arcgis.features.FeatureSet:
        if self.query_error is not None:
            raise self.query_error
        return self.feature_set


class FailingTransformer:
    """Transformer stand-in whose corner transforms always fail."""

    def transform(  # ruff: ignore[no-self-use]
        self,
        longitude: float,
        latitude: float,
    ) -> tuple[float, float]:
        message = f"transform failed at ({longitude}, {latitude})"
        raise pyproj.exceptions.ProjError(message)


def failing_from_crs(
    crs_from: str,
    crs_to: pyproj.CRS,
    *,
    always_xy: bool = True,
) -> FailingTransformer:
    return FailingTransformer()


@pytest.fixture
def runner() -> click.testing.CliRunner:
    return click.testing.CliRunner()


@pytest.fixture
def feature_set_with_geometry() -> arcgis.features.FeatureSet:
    """A FeatureSet whose features carry point geometries in WGS84.

    Returns:
        A FeatureSet with two point features in WGS84.
    """
    return arcgis.features.FeatureSet(
        [
            arcgis.features.Feature(
                geometry={
                    "x": 1.0,
                    "y": 2.0,
                    "spatialReference": {"wkid": WGS84_WKID},
                },
                attributes={"name": "a"},
            ),
            arcgis.features.Feature(
                geometry={
                    "x": 3.0,
                    "y": 4.0,
                    "spatialReference": {"wkid": WGS84_WKID},
                },
                attributes={"name": "b"},
            ),
        ],
    )


@pytest.fixture
def configured_feeds(
    monkeypatch: pytest.MonkeyPatch,
) -> list[peri_scribe.feed_types.Feed]:
    """Point models.FEEDS at two configured feeds for GeoPackage reading.

    Returns:
        The two feeds, configured with fire name and status columns.
    """
    feeds = list(
        peri_scribe.models.build_feeds([
            {
                "feed_type": "ArcGISFeed",
                "url": "https://example.test/ArcGIS/rest/services/Fires_One/FeatureServer/0",
                "fire_name_column": "incident_name",
                "status_column": "displayStatus",
            },
            {
                "feed_type": "ArcGISFeed",
                "url": "https://example.test/ArcGIS/rest/services/Fires_Two/FeatureServer/0",
                "fire_name_column": "IncidentName",
                "status_column": "ActiveFireCandidate",
            },
        ]),
    )
    monkeypatch.setattr(peri_scribe.models, "FEEDS", feeds)
    return feeds


@pytest.fixture
def configured_feeds_with_identifiers(
    monkeypatch: pytest.MonkeyPatch,
) -> list[peri_scribe.feed_types.Feed]:
    """Point models.FEEDS at feeds with identifier and complex columns.

    The first feed is CA-layer-like, with an identifier column only. The second is
    WFIGS-like, with identifier and complex columns.

    Returns:
        The two feeds, configured with fire name, status, identifier, and
        complex columns.
    """
    feeds = list(
        peri_scribe.models.build_feeds([
            {
                "feed_type": "ArcGISFeed",
                "url": "https://example.test/ArcGIS/rest/services/Fires_One/FeatureServer/0",
                "fire_name_column": "incident_name",
                "status_column": "displayStatus",
                "fire_identifier_columns": ["incident_number"],
            },
            {
                "feed_type": "ArcGISFeed",
                "url": "https://example.test/ArcGIS/rest/services/Fires_Two/FeatureServer/0",
                "fire_name_column": "IncidentName",
                "status_column": "ActiveFireCandidate",
                "fire_identifier_columns": ["IrwinID"],
                "complex_identifier_column": "CpxID",
                "complex_name_column": "CpxName",
                "is_complex_child_column": "IsCpxChild",
            },
        ]),
    )
    monkeypatch.setattr(peri_scribe.models, "FEEDS", feeds)
    return feeds


@pytest.fixture
def configured_feeds_with_mission(
    monkeypatch: pytest.MonkeyPatch,
) -> list[peri_scribe.feed_types.Feed]:
    """Point models.FEEDS at a CA-layer-like feed with mission and time columns.

    Returns:
        The feed, configured with name, status, identifier, mission, and observation
        time columns.
    """
    feeds = list(
        peri_scribe.models.build_feeds([
            {
                "feed_type": "ArcGISFeed",
                "url": "https://example.test/ArcGIS/rest/services/Fires_One/FeatureServer/0",
                "fire_name_column": "incident_name",
                "status_column": "displayStatus",
                "fire_identifier_columns": ["incident_number"],
                "mission_column": "mission",
                "observation_time_column": "poly_DateCurrent",
            },
        ]),
    )
    monkeypatch.setattr(peri_scribe.models, "FEEDS", feeds)
    return feeds


@pytest.fixture
def stub_geo_package(
    monkeypatch: pytest.MonkeyPatch,
) -> typing.Callable[[pd.DataFrame, dict[str, pd.DataFrame]], None]:
    """Point GeoPackage layer listing and reading at in-memory stand-ins.

    Returns:
        A function that installs stand-ins serving the given layers table and
        per-layer dataframes.
    """

    def stub(layers: pd.DataFrame, dataframes: dict[str, pd.DataFrame]) -> None:
        monkeypatch.setattr(
            peri_scribe.geo_data.geopandas,
            "list_layers",
            lambda _path: layers,
        )
        monkeypatch.setattr(
            peri_scribe.geo_data.geopandas,
            "read_file",
            lambda _path, layer: dataframes[layer],
        )

    return stub


@pytest.fixture
def layer_data_factory() -> typing.Callable[[str], peri_scribe.models.LayerData]:
    """Build LayerData entries with two point features in WGS84.

    Returns:
        A factory for LayerData entries with two point features in WGS84.
    """

    def make_layer_data(name: str) -> peri_scribe.models.LayerData:
        dataframe = geopandas.GeoDataFrame(
            {"name": ["a", "b"]},
            geometry=[
                shapely.geometry.Point(1.0, 2.0),
                shapely.geometry.Point(3.0, 4.0),
            ],
            crs=pyproj.CRS.from_epsg(WGS84_WKID),
        )
        return peri_scribe.models.LayerData(name=name, dataframe=dataframe)

    return make_layer_data


class GeoPackageStore:
    """In-memory stand-in for the GeoPackage files the fetch command writes.

    Written layers are keyed by (path, layer name) so tests can assert what was
    written and serve it back to incremental fetches without touching the
    filesystem.
    """

    def __init__(self) -> None:
        self.layers: dict[
            tuple[pathlib.Path, str],
            geopandas.GeoDataFrame,
        ] = {}

    def write(
        self,
        path: pathlib.Path,
        layers: list[peri_scribe.models.LayerData],
    ) -> None:
        """Record *layers* as the contents of the GeoPackage at *path*."""
        for layer_data in layers:
            self.layers[path, layer_data.name] = layer_data.dataframe

    def filenames(self, directory: pathlib.Path) -> list[pathlib.Path]:
        """Return the GeoPackage filenames stored under *directory*.

        Returns:
            The stored GeoPackage filenames in sorted order.
        """
        return sorted(
            pathlib.Path(path.name)
            for path, _layer_name in self.layers
            if path.parent == directory and path.suffix == ".gpkg"
        )

    def read_layer(
        self,
        path: pathlib.Path,
        feed: peri_scribe.feed_types.Feed,
    ) -> geopandas.GeoDataFrame:
        """Return the layer for *feed* stored in the GeoPackage at *path*.

        Returns:
            The feed's layer dataframe.
        """
        return self.layers[path, feed.name]

    def layer(
        self,
        path: pathlib.Path,
        layer_name: str,
    ) -> geopandas.GeoDataFrame:
        """Return the layer named *layer_name* stored at *path*.

        Returns:
            The layer dataframe.
        """
        return self.layers[path, layer_name]

    def has(self, path: pathlib.Path) -> bool:
        """Return whether any layer has been stored at *path*.

        Returns:
            True when a layer has been stored at *path*.
        """
        return any(stored_path == path for stored_path, _layer_name in self.layers)


@pytest.fixture
def geo_package_store(
    monkeypatch: pytest.MonkeyPatch,
) -> GeoPackageStore:
    """Install an in-memory stand-in for the fetch command's file storage.

    Returns:
        The store recording written GeoPackage layers.
    """
    store = GeoPackageStore()
    monkeypatch.setattr(peri_scribe.output, "write_geopackage", store.write)
    monkeypatch.setattr(
        peri_scribe.operations,
        "existing_geopackage_filenames",
        store.filenames,
    )
    monkeypatch.setattr(
        peri_scribe.geo_data,
        "read_layer_dataframe",
        store.read_layer,
    )
    monkeypatch.setattr(
        pathlib.Path,
        "mkdir",
        lambda *_arguments, **_keywords: None,
    )
    return store
