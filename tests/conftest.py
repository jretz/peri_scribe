from __future__ import annotations

import datetime
import http
import pathlib
import typing

import click.testing
import geopandas
import pyproj
import pytest
import shapely.geometry
import structlog
import time_machine

import peri_scribe.fires.differential
import peri_scribe.fires.scores
import peri_scribe.geo.package
import peri_scribe.geo.reading
import peri_scribe.kml.builder
import peri_scribe.kml.plot_rendering
import peri_scribe.main
import peri_scribe.models
import peri_scribe.output
import peri_scribe.sources.administrative_boundaries
import peri_scribe.sources.feed_types
import peri_scribe.sources.feeds
import peri_scribe.sources.fetching
import peri_scribe.sources.snapshots
import peri_scribe.sources.validation
import tests.factories
import tests.peri_scribe.kml.kml_helpers
from tests.factories import WGS84_WKID, GeoPackageStore, wgs84_feature_set
from tests.main_stubs import (
    BASE_DIRECTORY,
    SAMPLE_LAST_EDIT_TIMESTAMP,
    UpdateKmzStubs,
    ValidateSourcesStubs,
)


if typing.TYPE_CHECKING:
    import arcgis.features
    import pandas as pd


WEB_MERCATOR_WKID = 3857
CALIFORNIA_ALBERS_WKID = 3310
NAD83_WKID = 4269
NAD83_2011_WKID = 6318
NAVD88_HEIGHT_WKID = 5703
UNKNOWN_WKID = 999999

WEB_MERCATOR_MAXIMUM_MAGNITUDE_IN_METERS = 20048966.104014598

CLICK_USAGE_ERROR_EXIT_CODE = 2

# Error messages matching the ArcGIS REST API 429 rate-limit response format.
RATE_LIMIT_RETRY_AFTER_IN_SECONDS = 60
RATE_LIMIT_ERROR_PAYLOAD = {
    "error": {
        "code": http.HTTPStatus.TOO_MANY_REQUESTS,
        "message": "Unable to perform query. Too many requests.",
        "details": [
            (
                "API calls quota exceeded (120975 request units)! maximum allowed "
                "request units (115200) per Minute. "
                f"Retry after {RATE_LIMIT_RETRY_AFTER_IN_SECONDS} sec."
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


@pytest.fixture
def log_output() -> structlog.testing.LogCapture:
    """Captures all log entries during a test.

    Returns:
        An object that can be used to inspect captured log entries.
    """
    return structlog.testing.LogCapture()


@pytest.fixture(autouse=True)
def configure_structlog(log_output: structlog.testing.LogCapture) -> None:
    """Configures structlog to use the LogCapture processor for all tests."""
    structlog.configure(
        processors=[log_output],
        wrapper_class=structlog.make_filtering_bound_logger("DEBUG"),
    )


def sample_feed() -> peri_scribe.sources.feed_types.ArcGISFeed:
    """Return the sample ArcGIS feed.

    Returns:
        The sample ArcGIS feed.
    """
    return peri_scribe.sources.feed_types.ArcGISFeed(
        url=SAMPLE_FEED_URL,
        fire_name_column=SAMPLE_FIRE_NAME_COLUMN,
        status_column=SAMPLE_STATUS_COLUMN,
    )


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
        ) -> peri_scribe.geo.package.GeopackageContents:
            memberships = (memberships_by_path or {}).get(path, [])
            rows = tuple(
                peri_scribe.geo.package.FireRowRecord(
                    record=record,
                    object_id=None,
                    source_name="",
                    attributes={},
                )
                for record in records_by_path.get(path, [])
            )
            return peri_scribe.geo.package.GeopackageContents(
                rows=rows,
                memberships=tuple(memberships),
            )

        def fake_geo_package_files(
            _directory: pathlib.Path,
        ) -> list[pathlib.Path]:
            return sorted(set(records_by_path) | set(memberships_by_path or {}))

        monkeypatch.setattr(
            peri_scribe.geo.package,
            "read_geopackage",
            fake_read_geopackage,
        )
        monkeypatch.setattr(
            peri_scribe.sources.snapshots,
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
def feed() -> peri_scribe.sources.feed_types.ArcGISFeed:
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
    change_columns: tuple[str, ...] = (),
) -> peri_scribe.sources.feed_types.ArcGISFeed:
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
        change_columns: The timestamp columns that change when a feature is edited.

    Returns:
        The ArcGIS feed.
    """
    return peri_scribe.sources.feed_types.ArcGISFeed(
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
        change_columns=change_columns,
    )


def configure_feeds(
    monkeypatch: pytest.MonkeyPatch,
    feeds: list[peri_scribe.sources.feed_types.Feed],
) -> list[peri_scribe.sources.feed_types.Feed]:
    """Point feeds.FEEDS at *feeds* and return them.

    Args:
        monkeypatch: The monkeypatch fixture.
        feeds: The feeds to serve as the configured feeds.

    Returns:
        The configured feeds.
    """
    monkeypatch.setattr(peri_scribe.sources.feeds, "FEEDS", feeds)
    return feeds


@pytest.fixture
def configured_feeds(
    monkeypatch: pytest.MonkeyPatch,
) -> list[peri_scribe.sources.feed_types.Feed]:
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
) -> list[peri_scribe.sources.feed_types.Feed]:
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
) -> list[peri_scribe.sources.feed_types.Feed]:
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
) -> list[peri_scribe.sources.feed_types.Feed]:
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
        peri_scribe.sources.snapshots,
        "existing_source_files",
        store.source_files,
    )
    monkeypatch.setattr(
        peri_scribe.geo.reading,
        "read_layer_dataframe",
        store.read_layer,
    )
    monkeypatch.setattr(
        pathlib.Path,
        "mkdir",
        lambda *_arguments, **_keywords: None,
    )
    return store


@pytest.fixture
def in_process_plot_image_bundles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Render plots in-process instead of in a pool for one test."""
    monkeypatch.setattr(
        peri_scribe.kml.plot_rendering,
        "plot_image_bundles",
        tests.peri_scribe.kml.kml_helpers.serial_plot_image_bundles,
    )


def snapshot_path(
    *,
    feed_name: str = SAMPLE_FEED_NAME,
    serial_number: int = 0,
    last_edit_timestamp: int = SAMPLE_LAST_EDIT_TIMESTAMP,
) -> pathlib.Path:
    """Return the snapshot path fetch writes for a feed and last-edit timestamp.

    Returns:
        The snapshot path, assuming the 2026 test year, no prior snapshots, and a first
        serial number of 0.
    """
    return peri_scribe.sources.snapshots.source_geopackage_path(
        BASE_DIRECTORY,
        2026,
        feed_name,
        peri_scribe.sources.snapshots.SourceFile(
            serial_number=serial_number,
            last_edit_timestamp=last_edit_timestamp,
        ),
    )


@pytest.fixture
def current_year(
    monkeypatch: pytest.MonkeyPatch,
) -> typing.Iterator[None]:
    """Fix the working directory and freeze the current year at 2026."""
    monkeypatch.setattr(
        pathlib.Path,
        "cwd",
        staticmethod(lambda: BASE_DIRECTORY),
    )
    with time_machine.travel(
        datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
        tick=False,
    ):
        yield


@pytest.fixture
def update_kmz_stubs(
    monkeypatch: pytest.MonkeyPatch,
) -> typing.Callable[..., UpdateKmzStubs]:
    """Install step stubs for the update-kmz command.

    Returns:
        A callable taking whether the fetch changed something and whether the
        evacuations were replaced, and returning the installed fetch outcome and the
        lists recording each step's calls.
    """

    def install(
        *,
        changed: bool,
        evacuations_changed: bool = False,
    ) -> UpdateKmzStubs:
        stubs = UpdateKmzStubs(
            fetch_result=peri_scribe.sources.fetching.FetchResult(
                snapshot_paths=(),
                changed=changed,
            ),
            fetch_calls=[],
            external_calls=[],
            ensure_boundary_calls=[],
            history_calls=[],
            scores_calls=[],
            kmz_calls=[],
        )

        def fetch_all_feeds(
            base_directory: pathlib.Path,
            *,
            year: int,
            full: bool = False,
        ) -> peri_scribe.sources.fetching.FetchResult:
            stubs.fetch_calls.append((base_directory, year, full))
            return stubs.fetch_result

        monkeypatch.setattr(
            peri_scribe.sources.fetching,
            "fetch_all_feeds",
            fetch_all_feeds,
        )
        # The stored evacuations digest is observed before and after the external source
        # fetch; the two observations differ only when the fetch replaced the stored
        # evacuations.
        digests = ["before", "after"] if evacuations_changed else ["same", "same"]

        def stored_evacuations_digest(
            _year_directory: pathlib.Path,
        ) -> str | None:
            return digests.pop() if digests else "same"

        monkeypatch.setattr(
            peri_scribe.main,
            "stored_evacuations_digest",
            stored_evacuations_digest,
        )
        monkeypatch.setattr(
            peri_scribe.main,
            "fetch_external_source",
            lambda source, year_directory: stubs.external_calls.append(
                (source, year_directory),
            ),
        )
        monkeypatch.setattr(
            peri_scribe.sources.administrative_boundaries,
            "ensure_administrative_boundaries",
            lambda year_directory=None: stubs.ensure_boundary_calls.append(
                year_directory,
            ),
        )
        monkeypatch.setattr(
            peri_scribe.fires.differential,
            "write_history_of_differential_geography",
            stubs.history_calls.append,
        )
        monkeypatch.setattr(
            peri_scribe.fires.scores,
            "score_fires",
            stubs.scores_calls.append,
        )
        monkeypatch.setattr(
            peri_scribe.kml.builder,
            "create_kmz",
            stubs.kmz_calls.append,
        )
        return stubs

    return install


@pytest.fixture
def validate_sources_stubs(
    monkeypatch: pytest.MonkeyPatch,
) -> typing.Callable[
    [tuple[peri_scribe.sources.validation.FeedValidationResult, ...]],
    ValidateSourcesStubs,
]:
    """Install step stubs for the validate-sources command.

    Returns:
        A callable taking the validation results to serve and returning the recorded
        step calls.
    """

    def install(
        results: tuple[peri_scribe.sources.validation.FeedValidationResult, ...],
    ) -> ValidateSourcesStubs:
        stubs = ValidateSourcesStubs(
            fetch_complete_calls=[],
            fetch_incremental_calls=[],
            validate_calls=[],
            removal_calls=[],
        )

        def fetch_all_feeds_complete(
            base_directory: pathlib.Path,
            *,
            year: int,
        ) -> tuple[pathlib.Path, ...]:
            stubs.fetch_complete_calls.append((base_directory, year))
            return ()

        def fetch_all_feeds(
            base_directory: pathlib.Path,
            *,
            year: int,
        ) -> peri_scribe.sources.fetching.FetchResult:
            stubs.fetch_incremental_calls.append((base_directory, year))
            return peri_scribe.sources.fetching.FetchResult(
                snapshot_paths=(),
                changed=False,
            )

        def validate_complete_sources(
            year_directory: pathlib.Path,
            feeds: object,
        ) -> tuple[peri_scribe.sources.validation.FeedValidationResult, ...]:
            stubs.validate_calls.append(year_directory)
            return results

        monkeypatch.setattr(
            peri_scribe.sources.fetching,
            "fetch_all_feeds_complete",
            fetch_all_feeds_complete,
        )
        monkeypatch.setattr(
            peri_scribe.sources.fetching,
            "fetch_all_feeds",
            fetch_all_feeds,
        )
        monkeypatch.setattr(
            peri_scribe.sources.validation,
            "validate_complete_sources",
            validate_complete_sources,
        )
        monkeypatch.setattr(
            peri_scribe.output,
            "remove_directory_tree",
            stubs.removal_calls.append,
        )
        return stubs

    return install


@pytest.fixture
def validate_sources_setup(monkeypatch: pytest.MonkeyPatch) -> None:
    """Silence log configuration so validate-sources logs can be captured."""
    monkeypatch.setattr(
        peri_scribe.output,
        "configure_logging",
        lambda log_level: log_level,
    )
