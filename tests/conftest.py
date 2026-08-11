import typing

import arcgis.features
import click.testing
import geopandas
import pyproj
import pyproj.exceptions
import pytest
import shapely.geometry

import peri_scribe.models


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
