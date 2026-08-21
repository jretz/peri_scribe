from __future__ import annotations

import http
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
import peri_scribe.feeds
import peri_scribe.geo_package
import peri_scribe.models
import peri_scribe.output
import peri_scribe.snapshots


if typing.TYPE_CHECKING:
    import pandas as pd

    import tests.factories


WGS84_WKID = 4326
WEB_MERCATOR_WKID = 3857
CALIFORNIA_ALBERS_WKID = 3310
NAD83_WKID = 4269
NAVD88_HEIGHT_WKID = 5703
UNKNOWN_WKID = 999999

WEB_MERCATOR_MAXIMUM_MAGNITUDE_IN_METERS = 20048966.104014598

CLICK_USAGE_ERROR_EXIT_CODE = 2

# Error messages matching the ArcGIS REST API 429 rate-limit response format.
RATE_LIMIT_RETRY_AFTER_SECONDS = 60
RATE_LIMIT_ERROR_PAYLOAD = {
    "error": {
        "code": http.HTTPStatus.TOO_MANY_REQUESTS,
        "message": "Unable to perform query. Too many requests.",
        "details": [
            (
                "API calls quota exceeded (120975 request units)! maximum allowed "
                "request units (115200) per Minute. "
                f"Retry after {RATE_LIMIT_RETRY_AFTER_SECONDS} sec."
            ),
        ],
    },
}
LOOSE_429_ERROR_PAYLOAD = {
    "error": {
        "code": http.HTTPStatus.TOO_MANY_REQUESTS,
        "message": "Too many requests.",
    },
}

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


def sample_feed() -> peri_scribe.feed_types.ArcGISFeed:
    """Return the sample ArcGIS feed.

    Returns:
        The sample ArcGIS feed.
    """
    return peri_scribe.feed_types.ArcGISFeed(
        url=SAMPLE_FEED_URL,
        fire_name_column=SAMPLE_FIRE_NAME_COLUMN,
        status_column=SAMPLE_STATUS_COLUMN,
    )


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


class FeatureLayerStubBase:
    """Base stand-in for an ArcGIS FeatureLayer exposing WGS84 properties."""

    def __init__(self, url: str, gis: object) -> None:
        self.url = url
        self.gis = gis
        self.layer_properties: dict[str, object] = {
            "spatialReference": {"wkid": WGS84_WKID},
        }

    @property
    def properties(self) -> dict[str, object]:
        return self.layer_properties


class FeatureLayerStub(FeatureLayerStubBase):
    """Minimal stand-in for an ArcGIS FeatureLayer with a fixed query result."""

    def __init__(
        self,
        url: str,
        gis: object,
        feature_set: arcgis.features.FeatureSet,
        query_error: Exception | None = None,
    ) -> None:
        super().__init__(url, gis)
        self.feature_set = feature_set
        self.query_error = query_error

    def query(
        self,
        **parameters: object,
    ) -> arcgis.features.FeatureSet | dict[str, object]:
        if self.query_error is not None:
            raise self.query_error
        if parameters.get("return_ids_only"):
            return {"objectIdFieldName": "OBJECTID", "objectIds": [1, 2]}
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


def wgs84_feature_set(
    points: list[tuple[int | None, str, float, float]],
) -> arcgis.features.FeatureSet:
    """Build a WGS84 FeatureSet from (OBJECTID, name, x, y) point rows.

    Args:
        points: The OBJECTID (None to omit it), name, longitude, and latitude of
            each feature.

    Returns:
        The FeatureSet.
    """
    features = []
    for object_id, name, x, y in points:
        attributes: dict[str, object] = {"name": name}
        if object_id is not None:
            attributes["OBJECTID"] = object_id
        features.append(
            arcgis.features.Feature(
                geometry={
                    "x": x,
                    "y": y,
                    "spatialReference": {"wkid": WGS84_WKID},
                },
                attributes=attributes,
            ),
        )
    return arcgis.features.FeatureSet(features)


def sample_geo_dataframe() -> geopandas.GeoDataFrame:
    """Return the canonical two-point WGS84 GeoDataFrame.

    Returns:
        A GeoDataFrame with two point features in WGS84.
    """
    return geopandas.GeoDataFrame(
        {"name": ["a", "b"]},
        geometry=[
            shapely.geometry.Point(1.0, 2.0),
            shapely.geometry.Point(3.0, 4.0),
        ],
        crs=pyproj.CRS.from_epsg(WGS84_WKID),
    )


@pytest.fixture
def stub_fire_reader(
    monkeypatch: pytest.MonkeyPatch,
) -> tests.factories.StubFireReader:
    """Point the GeoPackage readers at in-memory fires and memberships.

    Returns:
        A function that installs stand-ins serving the given fires and
        memberships per GeoPackage path.
    """

    def stub(
        records_by_path: dict[pathlib.Path, list[peri_scribe.models.FireRecord]],
        memberships_by_path: dict[
            pathlib.Path,
            list[peri_scribe.models.ComplexMembership],
        ]
        | None = None,
    ) -> None:
        def fake_read_geopackage(
            path: pathlib.Path,
        ) -> peri_scribe.geo_package.GeopackageContents:
            memberships = (memberships_by_path or {}).get(path, [])
            rows = tuple(
                peri_scribe.geo_package.FireRowRecord(
                    record=record,
                    object_id=None,
                    source_name="",
                    attributes={},
                )
                for record in records_by_path.get(path, [])
            )
            return peri_scribe.geo_package.GeopackageContents(
                rows=rows,
                memberships=tuple(memberships),
            )

        def fake_geo_package_files(
            _directory: pathlib.Path,
        ) -> list[pathlib.Path]:
            return sorted(set(records_by_path) | set(memberships_by_path or {}))

        monkeypatch.setattr(
            peri_scribe.geo_package,
            "read_geopackage",
            fake_read_geopackage,
        )
        monkeypatch.setattr(
            peri_scribe.snapshots,
            "geo_package_files",
            fake_geo_package_files,
        )

    return stub


@pytest.fixture
def runner() -> click.testing.CliRunner:
    return click.testing.CliRunner()


@pytest.fixture
def feature_set_with_geometry() -> arcgis.features.FeatureSet:
    """A FeatureSet whose features carry point geometries in WGS84.

    Returns:
        A FeatureSet with two point features in WGS84.
    """
    return wgs84_feature_set([
        (None, "a", 1.0, 2.0),
        (None, "b", 3.0, 4.0),
    ])


@pytest.fixture
def feed() -> peri_scribe.feed_types.ArcGISFeed:
    """Return the sample ArcGIS feed.

    Returns:
        The sample ArcGIS feed.
    """
    return sample_feed()


FIRES_ONE_URL = "https://example.test/ArcGIS/rest/services/Fires_One/FeatureServer/0"
FIRES_TWO_URL = "https://example.test/ArcGIS/rest/services/Fires_Two/FeatureServer/0"


def arc_gis_feed(
    url: str,
    fire_name_column: str,
    status_column: str,
    *,
    fire_identifier_columns: tuple[str, ...] = (),
    mission_column: str | None = None,
    observation_time_column: str | None = None,
    point_of_origin_state_column: str | None = None,
    point_of_origin_fips_column: str | None = None,
    complex_identifier_column: str | None = None,
    complex_name_column: str | None = None,
    is_complex_child_column: str | None = None,
    modified_column: str | None = None,
) -> peri_scribe.feed_types.ArcGISFeed:
    """Build an ArcGIS feed with the given name and status columns.

    Args:
        url: The feed's REST URL.
        fire_name_column: The column holding each fire's name.
        status_column: The column holding each fire's status.
        fire_identifier_columns: The columns holding fire identifiers.
        mission_column: The column holding each fire's mission.
        observation_time_column: The column holding each fire's observation time.
        point_of_origin_state_column: The column holding the point of origin state.
        point_of_origin_fips_column: The column holding the point of origin FIPS.
        complex_identifier_column: The column holding each complex's identifier.
        complex_name_column: The column holding each complex's name.
        is_complex_child_column: The column marking complex child rows.
        modified_column: The column holding each feature's modified time.

    Returns:
        The ArcGIS feed.
    """
    return peri_scribe.feed_types.ArcGISFeed(
        url=url,
        fire_name_column=fire_name_column,
        status_column=status_column,
        fire_identifier_columns=fire_identifier_columns,
        mission_column=mission_column,
        observation_time_column=observation_time_column,
        point_of_origin_state_column=point_of_origin_state_column,
        point_of_origin_fips_column=point_of_origin_fips_column,
        complex_identifier_column=complex_identifier_column,
        complex_name_column=complex_name_column,
        is_complex_child_column=is_complex_child_column,
        modified_column=modified_column,
    )


def configure_feeds(
    monkeypatch: pytest.MonkeyPatch,
    feeds: list[peri_scribe.feed_types.Feed],
) -> list[peri_scribe.feed_types.Feed]:
    """Point feeds.FEEDS at *feeds* and return them.

    Args:
        monkeypatch: The monkeypatch fixture.
        feeds: The feeds to serve as the configured feeds.

    Returns:
        The configured feeds.
    """
    monkeypatch.setattr(peri_scribe.feeds, "FEEDS", feeds)
    return feeds


@pytest.fixture
def configured_feeds(
    monkeypatch: pytest.MonkeyPatch,
) -> list[peri_scribe.feed_types.Feed]:
    """Point feeds.FEEDS at two configured feeds for GeoPackage reading.

    Returns:
        The two feeds, configured with fire name and status columns.
    """
    return configure_feeds(
        monkeypatch,
        [
            arc_gis_feed(FIRES_ONE_URL, "incident_name", "displayStatus"),
            arc_gis_feed(FIRES_TWO_URL, "IncidentName", "ActiveFireCandidate"),
        ],
    )


@pytest.fixture
def configured_feeds_with_identifiers(
    monkeypatch: pytest.MonkeyPatch,
) -> list[peri_scribe.feed_types.Feed]:
    """Point feeds.FEEDS at feeds with identifier and complex columns.

    The first feed is CA-layer-like, with an identifier column only. The second is
    WFIGS-like, with identifier and complex columns.

    Returns:
        The two feeds, configured with fire name, status, identifier, and
        complex columns.
    """
    return configure_feeds(
        monkeypatch,
        [
            arc_gis_feed(
                FIRES_ONE_URL,
                "incident_name",
                "displayStatus",
                fire_identifier_columns=("incident_number",),
            ),
            arc_gis_feed(
                FIRES_TWO_URL,
                "IncidentName",
                "ActiveFireCandidate",
                fire_identifier_columns=("IrwinID",),
                complex_identifier_column="CpxID",
                complex_name_column="CpxName",
                is_complex_child_column="IsCpxChild",
            ),
        ],
    )


@pytest.fixture
def configured_feeds_with_mission(
    monkeypatch: pytest.MonkeyPatch,
) -> list[peri_scribe.feed_types.Feed]:
    """Point feeds.FEEDS at a CA-layer-like feed with mission and time columns.

    Returns:
        The feed, configured with name, status, identifier, mission, and observation
        time columns.
    """
    return configure_feeds(
        monkeypatch,
        [
            arc_gis_feed(
                FIRES_ONE_URL,
                "incident_name",
                "displayStatus",
                fire_identifier_columns=("incident_number",),
                mission_column="mission",
                observation_time_column="poly_DateCurrent",
            ),
        ],
    )


@pytest.fixture
def configured_feeds_with_point_of_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> list[peri_scribe.feed_types.Feed]:
    """Point feeds.FEEDS at a WFIGS-like feed with point of origin columns.

    Returns:
        The feed, configured with name, status, identifier, mission, and point of
        origin columns.
    """
    return configure_feeds(
        monkeypatch,
        [
            arc_gis_feed(
                FIRES_TWO_URL,
                "IncidentName",
                "ActiveFireCandidate",
                fire_identifier_columns=("IrwinID",),
                mission_column="mission",
                point_of_origin_state_column="POOState",
                point_of_origin_fips_column="POOFips",
            ),
        ],
    )


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
            peri_scribe.geo_package.geopandas,
            "list_layers",
            lambda _path: layers,
        )
        monkeypatch.setattr(
            peri_scribe.geo_package.geopandas,
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
        return peri_scribe.models.LayerData(
            name=name,
            dataframe=sample_geo_dataframe(),
        )

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
        peri_scribe.snapshots,
        "existing_geopackage_filenames",
        store.filenames,
    )
    monkeypatch.setattr(
        peri_scribe.geo_package,
        "read_layer_dataframe",
        store.read_layer,
    )
    monkeypatch.setattr(
        pathlib.Path,
        "mkdir",
        lambda *_arguments, **_keywords: None,
    )
    return store
