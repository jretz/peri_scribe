import typing

import arcgis.features
import click.testing
import geopandas as gpd
import pyproj
import pyproj.exceptions
import pytest
import shapely
import shapely.geometry

import peri_scribe.exceptions
import peri_scribe.geo_data
import peri_scribe.main
import peri_scribe.models
import peri_scribe.spatial_reference


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
        self._properties = properties

    @property
    def properties(self) -> dict[str, object]:
        return self._properties


class FeatureSetStub(arcgis.features.FeatureSet):
    """Minimal stand-in for an ArcGIS FeatureSet exposing spatial_reference."""

    def __init__(self, spatial_reference: object) -> None:
        self._spatial_reference = spatial_reference

    @property
    def spatial_reference(self) -> object:
        return self._spatial_reference


class FeatureLayerStub:
    """Minimal stand-in for an ArcGIS FeatureLayer with a fixed query result."""

    def __init__(
        self,
        url: str,
        gis: object,
        feature_set: arcgis.features.FeatureSet,
        query_error: Exception | None = None,
    ) -> None:
        self._url = url
        self._gis = gis
        self._feature_set = feature_set
        self._query_error = query_error
        self._properties: dict[str, object] = {
            "spatialReference": {"wkid": WGS84_WKID},
        }

    @property
    def properties(self) -> dict[str, object]:
        return self._properties

    def query(self) -> arcgis.features.FeatureSet:
        if self._query_error is not None:
            raise self._query_error
        return self._feature_set


class FailingTransformer:
    """Transformer stand-in whose corner transforms always fail."""

    def transform(
        self,
        _longitude: float,
        _latitude: float,
    ) -> tuple[float, float]:
        message = "transform failed"
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
    """A FeatureSet whose features carry point geometries in WGS84."""
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
    """Build LayerData entries with two point features in WGS84."""

    def make_layer_data(name: str) -> peri_scribe.models.LayerData:
        dataframe = gpd.GeoDataFrame(
            {"name": ["a", "b"]},
            geometry=[
                shapely.geometry.Point(1.0, 2.0),
                shapely.geometry.Point(3.0, 4.0),
            ],
            crs=pyproj.CRS.from_epsg(WGS84_WKID),
        )
        return peri_scribe.models.LayerData(name=name, dataframe=dataframe)

    return make_layer_data
