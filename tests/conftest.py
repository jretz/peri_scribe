"""Provide isolated source, storage, logging, and CLI fixtures."""

from __future__ import annotations

import datetime
import http
import json
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
import peri_scribe.logging
import peri_scribe.main
import peri_scribe.models
import peri_scribe.output
import peri_scribe.pipeline_state
import peri_scribe.sources.administrative_boundaries
import peri_scribe.sources.feed_types
import peri_scribe.sources.feeds
import peri_scribe.sources.fetching
import peri_scribe.sources.full_fetch_state
import peri_scribe.sources.snapshots
import peri_scribe.sources.validation
import tests.factories
import tests.main_stubs
from peri_scribe.units import units


if typing.TYPE_CHECKING:
    import arcgis.features
    import pandas as pd


WEB_MERCATOR_WKID = 3857
CALIFORNIA_ALBERS_WKID = 3310
NAD83_WKID = 4269
NAD83_2011_WKID = 6318
NAVD88_HEIGHT_WKID = 5703
UNKNOWN_WKID = 999999

WEB_MERCATOR_MAXIMUM_MAGNITUDE = 20048966.104014598 * units.meters

CLICK_USAGE_ERROR_EXIT_CODE = 2

# Error messages matching the ArcGIS REST API 429 rate-limit response format.
RATE_LIMIT_RETRY_AFTER = 60 * units.seconds
RATE_LIMIT_ERROR_PAYLOAD = {
    "error": {
        "code": http.HTTPStatus.TOO_MANY_REQUESTS,
        "message": "Unable to perform query. Too many requests.",
        "details": [
            (
                "API calls quota exceeded (120975 request units)! maximum allowed "
                "request units (115200) per Minute. "
                f"Retry after {RATE_LIMIT_RETRY_AFTER.m_as('second')} sec."
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
def log_output() -> typing.Iterator[structlog.testing.LogCapture]:
    """Ensure captured log values can be serialized without a custom JSON encoder.

    Yields:
        An object that can be used to inspect captured log entries.
    """
    captured = structlog.testing.LogCapture()
    yield captured
    json.dumps(captured.entries, allow_nan=False)


@pytest.fixture(autouse=True)  # ruff: ignore[pytest-fixture-autouse]
def configure_structlog(
    log_output: structlog.testing.LogCapture,
) -> typing.Iterator[None]:
    """Isolate logging configuration and capture JSON-compatible log entries.

    Args:
        log_output: Captured structured log entries for assertions.

    Yields:
        Control while the test uses its own logging configuration.
    """
    original_configuration = structlog.get_config()
    structlog.configure(
        processors=[
            peri_scribe.logging.serialize_log_values,
            structlog.processors.format_exc_info,
            log_output,
        ],
        wrapper_class=structlog.make_filtering_bound_logger("DEBUG"),
    )
    try:
        yield
    finally:
        structlog.configure(**original_configuration)


@pytest.fixture
def cli_log_output(
    monkeypatch: pytest.MonkeyPatch,
    log_output: structlog.testing.LogCapture,
) -> structlog.testing.LogCapture:
    """Keep CLI invocations using the test's structured log capture.

    Args:
        monkeypatch: Replace dependencies and restore them after the test.
        log_output: Captured structured log entries for assertions.

    Returns:
        The captured CLI log entries.
    """
    monkeypatch.setattr(
        peri_scribe.logging,
        "configure_logging",
        lambda *_args, **_kwargs: None,
    )
    return log_output


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
        geometry=[shapely.geometry.Point(1.0, 2.0), shapely.geometry.Point(3.0, 4.0)],
        crs=pyproj.CRS.from_epsg(tests.factories.WGS84_WKID),
    )


@pytest.fixture
def stub_fire_reader(monkeypatch: pytest.MonkeyPatch) -> tests.factories.StubFireReader:
    """Point the GeoPackage readers at in-memory fires and memberships.

    Args:
        monkeypatch: Replace dependencies and restore them after the test.

    Returns:
        A function that installs stand-ins serving the given fires and memberships per
        GeoPackage path.
    """

    def stub(
        records_by_path: dict[pathlib.Path, list[peri_scribe.models.FireRecord]],
        memberships_by_path: dict[
            pathlib.Path,
            list[peri_scribe.models.ComplexMembership],
        ]
        | None = None,
    ) -> None:
        """Install fire observations and memberships for isolated reader tests.

        Args:
            records_by_path: Fire observations to serve for each GeoPackage path.
            memberships_by_path: Complex memberships to serve per path, or None for no
                memberships.
        """

        def fake_read_geopackage(
            path: pathlib.Path,
        ) -> peri_scribe.geo.package.GeopackageContents:
            """Serve the configured observations without reading a GeoPackage.

            Args:
                path: Path supplied to the intercepted file operation.

            Returns:
                The fire rows and memberships configured for this path.
            """
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

        def fake_geo_package_files(_directory: pathlib.Path) -> list[pathlib.Path]:
            """Expose the configured snapshot paths to the source reader.

            Args:
                _directory: Directory accepted for reader compatibility; configured
                    paths are used.

            Returns:
                The sorted paths containing configured fires or memberships.
            """
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
def runner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> click.testing.CliRunner:
    """Keep CLI-created data and logs inside the test's temporary directory.

    Args:
        monkeypatch: Replace dependencies and restore them after the test.
        tmp_path: Isolated directory for this test's files.

    Returns:
        A runner whose default year directory is isolated from the repository.
    """
    monkeypatch.chdir(tmp_path)
    return click.testing.CliRunner()


@pytest.fixture
def feature_set_with_geometry() -> arcgis.features.FeatureSet:
    """Provide point features with a known WGS84 spatial reference.

    Returns:
        A FeatureSet with two point features in WGS84.
    """
    return tests.factories.wgs84_feature_set([
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

    Args:
        monkeypatch: Replace dependencies and restore them after the test.

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

    Args:
        monkeypatch: Replace dependencies and restore them after the test.

    Returns:
        The two feeds, configured with fire name, status, identifier, and complex
        columns.
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

    Args:
        monkeypatch: Replace dependencies and restore them after the test.

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

    Args:
        monkeypatch: Replace dependencies and restore them after the test.

    Returns:
        The feed, configured with name, status, identifier, mission, and point of origin
        columns.
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
        return peri_scribe.models.LayerData(name=name, dataframe=sample_geo_dataframe())

    return make_layer_data


@pytest.fixture
def geo_package_store(
    monkeypatch: pytest.MonkeyPatch,
) -> tests.factories.GeoPackageStore:
    """Install an in-memory stand-in for the fetch command's file storage.

    Args:
        monkeypatch: Replace dependencies and restore them after the test.

    Returns:
        The store recording written GeoPackage layers.
    """
    store = tests.factories.GeoPackageStore()
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
    monkeypatch.setattr(pathlib.Path, "mkdir", lambda *_args, **_kwargs: None)
    return store


def snapshot_path(
    *,
    feed_name: str = SAMPLE_FEED_NAME,
    serial_number: int = 0,
    last_edit_timestamp: int = tests.main_stubs.SAMPLE_LAST_EDIT_TIMESTAMP,
) -> pathlib.Path:
    """Return the snapshot path fetch writes for a feed and last-edit timestamp.

    Args:
        feed_name: Feed name used in the snapshot directory.
        serial_number: Snapshot sequence number used in the bucket and filename.
        last_edit_timestamp: Layer edit timestamp in milliseconds since the Unix epoch.

    Returns:
        The snapshot path for the 2026 test year and supplied feed metadata.
    """
    return peri_scribe.sources.snapshots.source_geopackage_path(
        tests.main_stubs.BASE_DIRECTORY,
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
    tmp_path: pathlib.Path,
) -> typing.Iterator[None]:
    """Fix the working directory and freeze the current year at 2026.

    Args:
        monkeypatch: Replace dependencies and restore them after the test.
        tmp_path: Isolated directory for this test's files.

    Yields:
        Control while the working directory and current year are isolated.
    """
    monkeypatch.setattr(
        pathlib.Path,
        "cwd",
        staticmethod(lambda: tests.main_stubs.BASE_DIRECTORY),
    )
    append_monthly_log = peri_scribe.logging.append_monthly_log
    monkeypatch.setattr(
        peri_scribe.logging,
        "append_monthly_log",
        lambda _directory, entry: append_monthly_log(tmp_path / "logs", entry),
    )
    with time_machine.travel(
        datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
        tick=False,
    ):
        yield


@pytest.fixture
def run_stubs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> typing.Callable[..., tests.main_stubs.RunStubs]:
    """Install step stubs for the run command.

    Args:
        monkeypatch: The fixture used to replace pipeline steps and state paths.
        tmp_path: The isolated directory for recovery state and the run lock.

    Returns:
        A callable taking whether the fetch changed something, whether the evacuations
        were replaced, and the stored full-fetch state, and returning the installed
        fetch outcome and the lists recording each step's calls.
    """

    def install(
        *,
        changed: bool,
        evacuations_changed: bool = False,
        stored_state: (
            peri_scribe.sources.full_fetch_state.FullFetchState | None
        ) = None,
    ) -> tests.main_stubs.RunStubs:
        """Isolate pipeline stages and capture their invocations.

        Args:
            changed: Whether source collection reports changed fire observations.
            evacuations_changed: Whether evacuation contents differ across the simulated
                fetch.
            stored_state: Previously recorded full-fetch checkpoint, or None if absent.

        Returns:
            The configured fetch outcome and captured pipeline calls.
        """
        monkeypatch.setattr(
            peri_scribe.pipeline_state,
            "state_path",
            lambda _year: tmp_path / "run_state.json",
        )
        monkeypatch.setattr(
            peri_scribe.pipeline_state,
            "lock_path",
            lambda _year: tmp_path / ".run.lock",
        )
        stubs = tests.main_stubs.RunStubs(
            fetch_result=peri_scribe.sources.fetching.FetchResult(
                snapshot_paths=(),
                changed=changed,
            ),
            fetch_calls=[],
            external_calls=[],
            write_state_calls=[],
            ensure_boundary_calls=[],
            history_calls=[],
            scores_calls=[],
            kmz_calls=[],
            report_calls=[],
        )

        def fetch_all_feeds(
            base_directory: pathlib.Path,
            *,
            year: int,
            full: bool = False,
        ) -> peri_scribe.sources.fetching.FetchResult:
            """Capture fetch options and serve the configured source outcome.

            Args:
                base_directory: Root directory containing data grouped by year.
                year: Collection year supplied by the command.
                full: Whether the fetch must collect the complete layer.

            Returns:
                The source fetch outcome selected for this test.
            """
            stubs.fetch_calls.append((base_directory, year, full))
            return stubs.fetch_result

        monkeypatch.setattr(
            peri_scribe.sources.fetching,
            "fetch_all_feeds",
            fetch_all_feeds,
        )

        def read_state(
            _path: pathlib.Path,
        ) -> peri_scribe.sources.full_fetch_state.FullFetchState | None:
            """Serve the configured full-fetch checkpoint without file access.

            Args:
                _path: File path accepted for compatibility; the configured stub outcome
                    is used.

            Returns:
                The configured checkpoint, or None when none has been stored.
            """
            return stored_state

        def write_state(
            path: pathlib.Path,
            *,
            last_full_fetch: datetime.datetime,
        ) -> None:
            """Capture checkpoint updates for pipeline assertions.

            Args:
                path: Path supplied to the intercepted file operation.
                last_full_fetch: Completion time recorded for the most recent full
                    fetch.
            """
            stubs.write_state_calls.append((path, last_full_fetch))

        monkeypatch.setattr(
            peri_scribe.sources.full_fetch_state,
            "read_state",
            read_state,
        )
        monkeypatch.setattr(
            peri_scribe.sources.full_fetch_state,
            "write_state",
            write_state,
        )
        # The stored evacuations digest is observed before and after the external source
        # fetch; the two observations differ only when the fetch replaced the stored
        # evacuations.
        digests = ["before", "after"] if evacuations_changed else ["same", "same"]

        def stored_evacuations_digest(_year_directory: pathlib.Path) -> str | None:
            """Simulate evacuation contents before and after collection.

            Args:
                _year_directory: Year directory accepted for compatibility with the
                    digest reader.

            Returns:
                The next configured digest, or a stable digest after both reads.
            """
            return digests.pop() if digests else "same"

        monkeypatch.setattr(
            peri_scribe.main,
            "stored_evacuations_digest",
            stored_evacuations_digest,
        )
        monkeypatch.setattr(
            peri_scribe.main,
            "fetch_external_source",
            lambda source, year_directory: stubs.external_calls.append((
                source,
                year_directory,
            )),
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
            lambda year, *, unconditional=False: (
                stubs.history_calls.append(year),
                stubs.unconditional_history_calls.append(year)
                if unconditional
                else None,
            ),
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
        monkeypatch.setattr(
            peri_scribe.main,
            "write_reports",
            stubs.report_calls.append,
        )
        return stubs

    return install


@pytest.fixture
def validate_sources_stubs(
    monkeypatch: pytest.MonkeyPatch,
) -> typing.Callable[
    [tuple[peri_scribe.sources.validation.FeedValidationResult, ...]],
    tests.main_stubs.ValidateSourcesStubs,
]:
    """Install step stubs for the validate-sources command.

    Args:
        monkeypatch: Replace dependencies and restore them after the test.

    Returns:
        A callable taking the validation results to serve and returning the recorded
        step calls.
    """

    def install(
        results: tuple[peri_scribe.sources.validation.FeedValidationResult, ...],
    ) -> tests.main_stubs.ValidateSourcesStubs:
        """Isolate validation stages and capture their invocations.

        Args:
            results: Validation findings to return from the simulated comparison.

        Returns:
            The captured complete fetch, incremental fetch, and validation calls.
        """
        stubs = tests.main_stubs.ValidateSourcesStubs(
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
            """Capture complete-fetch requests without collecting remote data.

            Args:
                base_directory: Root directory containing data grouped by year.
                year: Collection year supplied by the command.

            Returns:
                An empty tuple because this stub creates no snapshots.
            """
            stubs.fetch_complete_calls.append((base_directory, year))
            return ()

        def fetch_all_feeds(
            base_directory: pathlib.Path,
            *,
            year: int,
        ) -> peri_scribe.sources.fetching.FetchResult:
            """Capture incremental-fetch requests without collecting remote data.

            Args:
                base_directory: Root directory containing data grouped by year.
                year: Collection year supplied by the command.

            Returns:
                A fetch outcome with no snapshots or source changes.
            """
            stubs.fetch_incremental_calls.append((base_directory, year))
            return peri_scribe.sources.fetching.FetchResult(
                snapshot_paths=(),
                changed=False,
            )

        def validate_complete_sources(
            year_directory: pathlib.Path,
            feeds: object,
        ) -> tuple[peri_scribe.sources.validation.FeedValidationResult, ...]:
            """Capture the validation directory and serve the configured findings.

            Args:
                year_directory: Directory containing the year's source snapshots and
                    derived outputs.
                feeds: Feed configurations to include in the collection or validation.

            Returns:
                The validation findings selected for this test.
            """
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
    """Silence log configuration so validate-sources logs can be captured.

    Args:
        monkeypatch: Replace dependencies and restore them after the test.
    """
    monkeypatch.setattr(
        peri_scribe.logging,
        "configure_logging",
        lambda *_args, **_kwargs: None,
    )
