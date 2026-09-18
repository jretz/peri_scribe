"""Replace fetching dependencies with controlled test doubles."""

from __future__ import annotations

import dataclasses
import pathlib
import sqlite3
import typing

import arcgis.features

import peri_scribe.exceptions
import peri_scribe.output
import peri_scribe.sources.feed_types
import peri_scribe.sources.fetching
import peri_scribe.sources.snapshots
import tests.helpers.doubles.arcgis
import tests.helpers.doubles.concurrency
import tests.helpers.factories.geography
import tests.helpers.factories.peri_scribe.sources.feed_types
import tests.helpers.factories.peri_scribe.sources.fetching
import tests.helpers.factories.peri_scribe.sources.snapshots


if typing.TYPE_CHECKING:
    import pytest


class QueryableFeatureLayer(tests.helpers.doubles.arcgis.FeatureLayerStubBase):
    """Evaluate production filters with SQLite instead of assuming query order."""

    def __init__(
        self,
        database: sqlite3.Connection,
        features: dict[
            int,
            tests.helpers.factories.peri_scribe.sources.fetching.FetchFeature,
        ],
    ) -> None:
        """Keep all service state inside the generated example's database.

        Args:
            database: An isolated in-memory database owned by the test.
            features: Current features exposed by the simulated service.
        """
        super().__init__("https://example.test/FeatureServer/0", object())
        self.database = database
        database.row_factory = sqlite3.Row
        database.execute(
            "CREATE TABLE features (OBJECTID INTEGER PRIMARY KEY, name TEXT, "
            "status TEXT, ModifiedOnDateTime_dt TEXT, longitude REAL)",
        )
        database.executemany(
            "INSERT INTO features VALUES (?, ?, ?, ?, ?)",
            [
                (
                    *tests.helpers.factories.peri_scribe.sources.fetching.fetch_attributes(
                        identifier,
                        feature,
                    ).values(),
                    feature.longitude,
                )
                for identifier, feature in features.items()
            ],
        )

    def query(self, **kwargs: object) -> arcgis.features.FeatureSet | dict[str, object]:
        """Use an independent SQL evaluator for ID selection and feature retrieval.

        Args:
            kwargs: ArcGIS query options emitted by the production fetcher.

        Returns:
            Matching object IDs or a real ArcGIS FeatureSet, without network access.
        """
        predicate = str(kwargs.get("where", "1=1")).replace("timestamp ", "")
        if "object_ids" in kwargs:
            predicate = f"OBJECTID IN ({kwargs['object_ids']})"
        clauses = ["SELECT * FROM features"]
        clauses.extend(("WHERE", predicate, "ORDER BY OBJECTID"))
        rows = self.database.execute(" ".join(clauses)).fetchall()
        if kwargs.get("return_ids_only"):
            return {"objectIds": [row["OBJECTID"] for row in rows]}
        return arcgis.features.FeatureSet([
            arcgis.features.Feature(
                attributes={
                    key: row[key]
                    for key in ("OBJECTID", "name", "status", "ModifiedOnDateTime_dt")
                },
                geometry={
                    "x": row["longitude"],
                    "y": 0.0,
                    "spatialReference": {
                        "wkid": tests.helpers.factories.geography.WGS84_WKID,
                    },
                },
            )
            for row in rows
        ])


def stub_complete_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the complete fetch's file and network boundaries at in-memory stubs.

    Args:
        monkeypatch: The monkeypatch fixture.
    """
    monkeypatch.setattr(peri_scribe.sources.fetching.arcgis.gis, "GIS", object)
    monkeypatch.setattr(pathlib.Path, "mkdir", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        peri_scribe.output,
        "write_geopackage",
        lambda _path, _layers: None,
    )


@dataclasses.dataclass(frozen=True, kw_only=True)
class FeedStub:
    """Minimal feed stand-in with a fixed current last-edit timestamp."""

    name: str
    url: str
    last_edit_timestamp: int | None
    status_column: str = "status"
    change_columns: tuple[str, ...] = ("ModifiedOnDateTime_dt",)
    events: list[str] = dataclasses.field(default_factory=list)

    @property
    def current_last_edit_timestamp(self) -> int | None:
        """The configured edit timestamp, with access recorded for ordering checks.

        Returns:
            The configured layer edit timestamp, or None if unavailable.
        """
        self.events.append("timestamp")
        return self.last_edit_timestamp


class MultiQueryLayerStub(tests.helpers.doubles.arcgis.FeatureLayerStubBase):
    """FeatureLayer stand-in that returns/raises successive results per call."""

    def __init__(
        self,
        url: str,
        gis: object,
        query_outcomes: list[arcgis.features.FeatureSet | Exception],
    ) -> None:
        """Initialize ordered layer outcomes for fetch retry tests.

        Args:
            url: ArcGIS layer or download URL supplied by the caller.
            gis: GIS connection object supplied to the layer constructor.
            query_outcomes: Feature sets or failures served on successive query
                attempts.
        """
        super().__init__(url, gis)
        self.query_outcomes = list(query_outcomes)
        self.call_count = 0

    def query(self) -> arcgis.features.FeatureSet:
        """Serve the next configured query outcome for fetch retry assertions.

        Returns:
            The feature set selected for this attempt.

        Raises:
            The configured outcome, if this attempt was assigned an exception.
        """
        outcome = self.query_outcomes[self.call_count]
        self.call_count += 1
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class SequenceFeatureLayerStub(tests.helpers.doubles.arcgis.FeatureLayerStubBase):
    """FeatureLayer stand-in serving successive feature sets per query."""

    def __init__(
        self,
        url: str,
        gis: object,
        feature_sets: list[arcgis.features.FeatureSet],
        events: list[str] | None = None,
    ) -> None:
        """Initialize successive feature sets and an optional event recorder.

        Args:
            url: ArcGIS layer or download URL supplied by the caller.
            gis: GIS connection object supplied to the layer constructor.
            feature_sets: Feature sets served in order, repeating the final result.
            events: Shared list recording query and timestamp events.
        """
        super().__init__(url, gis)
        self.feature_sets = list(feature_sets)
        self.call_count = 0
        self.events = [] if events is None else events

    def query(self, **_kwargs: object) -> arcgis.features.FeatureSet:
        """Record a download and serve the next available feature set.

        Args:
            _kwargs: Query options accepted for compatibility with ArcGIS callers.

        Returns:
            The next feature set, repeating the last after the sequence is exhausted.
        """
        self.events.append("download")
        feature_set = self.feature_sets[
            min(self.call_count, len(self.feature_sets) - 1)
        ]
        self.call_count += 1
        return feature_set


class DeltaFeatureLayerStub(tests.helpers.doubles.arcgis.FeatureLayerStubBase):
    """FeatureLayer stand-in serving a full set, then an incremental delta."""

    def __init__(
        self,
        url: str,
        gis: object,
        full: arcgis.features.FeatureSet,
        delta: arcgis.features.FeatureSet,
    ) -> None:
        """Initialize full and changed-row responses for incremental-fetch tests.

        Args:
            url: ArcGIS layer or download URL supplied by the caller.
            gis: GIS connection object supplied to the layer constructor.
            full: Complete feature set returned when no incremental filter is supplied.
            delta: Changed features returned by incremental queries.
        """
        super().__init__(url, gis)
        self.full = full
        self.delta = delta

    def query(self, **kwargs: object) -> arcgis.features.FeatureSet | dict[str, object]:
        """Serve complete rows, changed rows, or their object identifiers.

        Args:
            kwargs: Parameters supplied to the intercepted query or command.

        Returns:
            The delta identifiers for ID queries, delta rows for ID filters, or full
            rows.
        """
        if kwargs.get("return_ids_only"):
            object_ids = [
                feature.attributes["OBJECTID"] for feature in self.delta.features
            ]
            return {"objectIdFieldName": "OBJECTID", "objectIds": object_ids}
        if kwargs.get("object_ids"):
            return self.delta
        return self.full


class RecordingFeatureLayerStub(tests.helpers.doubles.arcgis.FeatureLayerStubBase):
    """FeatureLayer stand-in that records when its data is downloaded."""

    def __init__(
        self,
        url: str,
        gis: object,
        feature_set: arcgis.features.FeatureSet,
        events: list[str],
    ) -> None:
        """Initialize a fixed feature set and a shared download-event recorder.

        Args:
            url: ArcGIS layer or download URL supplied by the caller.
            gis: GIS connection object supplied to the layer constructor.
            feature_set: Feature set returned by the controlled query.
            events: Shared list recording query and timestamp events.
        """
        super().__init__(url, gis)
        self.feature_set = feature_set
        self.events = events

    def query(self) -> arcgis.features.FeatureSet:
        """Record the download before serving the configured feature set.

        Returns:
            The configured feature set.
        """
        self.events.append("download")
        return self.feature_set


def sample_feed_stub() -> FeedStub:
    """Return the sample feed stub for fetch-all-feeds tests.

    Returns:
        The sample feed stub.
    """
    return FeedStub(
        name=tests.helpers.factories.peri_scribe.sources.feed_types.SAMPLE_FEED_NAME,
        url=tests.helpers.factories.peri_scribe.sources.feed_types.SAMPLE_FEED_URL,
        last_edit_timestamp=tests.helpers.factories.peri_scribe.sources.snapshots.SAMPLE_LAST_EDIT_TIMESTAMP,
    )


def make_missing_date_filter_recorder(
    *,
    captured: list[str],
) -> typing.Callable[..., list[int]]:
    """Create a callback with controlled dependencies.

    Capture the filter used to query rows with missing modification dates.

    Args:
        captured: Shared list recording filters for rows with missing modification
            dates.

    Returns:
        The callback bound to the supplied dependencies.
    """

    def capture_where(*args: object, **kwargs: object) -> list[int]:
        """Capture the filter used to query rows with missing modification dates.

        Args:
            args: Positional arguments accepted by the substituted dependency.
            kwargs: Keyword arguments accepted by the substituted dependency.

        Returns:
            An empty object-ID list.
        """
        captured.append(str(kwargs["where"]))
        return []

    return capture_where


def make_active_object_id_query(
    *,
    wheres: list[str],
) -> typing.Callable[..., list[int]]:
    """Create a callback with controlled dependencies.

    Serve object identifiers for full and active-row queries.

    Args:
        wheres: Shared list recording filters for complete and active-row ID queries.

    Returns:
        The callback bound to the supplied dependencies.
    """

    def query_ids(*args: object, **kwargs: object) -> list[int]:
        """Serve object identifiers for full and active-row queries.

        Args:
            args: Positional arguments accepted by the substituted dependency.
            kwargs: Keyword arguments accepted by the substituted dependency.

        Returns:
            The configured object identifiers matching the query filter.
        """
        where = str(kwargs["where"])
        wheres.append(where)
        if where == "1=1":
            return [1, 2, 3]
        if "status IN" in where:
            return [2]
        return []

    return query_ids


def make_complete_feed_reader(
    *,
    frames: dict[str, object],
) -> typing.Callable[..., object]:
    """Create a callback with controlled dependencies.

    Validate complete-fetch inputs and serve the requested feed's dataframe.

    Args:
        frames: Controlled complete-fetch outcomes keyed by feed name.

    Returns:
        The callback bound to the supplied dependencies.
    """

    def fetch_feed(
        feed: peri_scribe.sources.feed_types.Feed,
        gis: object,
        existing_source_files: list[peri_scribe.sources.snapshots.SourceFile],
        source_directory: pathlib.Path,
    ) -> object:
        """Validate complete-fetch inputs and serve the requested feed's dataframe.

        Args:
            feed: Feed configuration used to interpret the source observations.
            gis: GIS connection object supplied to the layer constructor.
            existing_source_files: Stored snapshots supplied to the complete-fetch stub.
            source_directory: Destination directory for complete validation snapshots.

        Returns:
            The configured dataframe for the requested feed.
        """
        assert existing_source_files == []
        assert source_directory == pathlib.Path("/base/data/2026/validation")
        return frames[feed.name]

    return fetch_feed


def mixed_feed_outcome(
    feed: peri_scribe.sources.feed_types.Feed,
    gis: object,
    existing_source_files: list[peri_scribe.sources.snapshots.SourceFile],
    source_directory: pathlib.Path,
) -> object:
    """Simulate failed, empty, and successful feeds in one collection.

    Args:
        feed: Feed configuration used to interpret the source observations.
        gis: GIS connection object supplied to the layer constructor.
        existing_source_files: Stored snapshots supplied to the complete-fetch stub.
        source_directory: Destination directory for complete validation snapshots.

    Returns:
        None for the empty feed, otherwise a successful placeholder result.

    Raises:
        peri_scribe.exceptions.FeedFetchError: If the requested feed is the configured
            failure case.
    """
    if feed.name == "Fires0_0":
        message = "Failed to fetch Fires0_0: boom"
        raise peri_scribe.exceptions.FeedFetchError(message)
    if feed.name == "Fires2_0":
        return None
    return object()


def fail_state_update(*args: object, **kwargs: object) -> None:
    """Simulate failure to persist a feed's current state.

    Args:
        args: Positional arguments accepted by the substituted dependency.
        kwargs: Keyword arguments accepted by the substituted dependency.

    Raises:
        RuntimeError: Always, to exercise collection continuation after a state-write
            failure.
    """
    message = "state write failed"
    raise RuntimeError(message)


def make_failing_feed_layer_factory(
    *,
    failing: FeedStub,
    feature_set_with_geometry: arcgis.features.FeatureSet,
) -> typing.Callable[..., tests.helpers.doubles.arcgis.FeatureLayerStub]:
    """Create a callback with controlled dependencies.

    Make one feed fail while allowing the other to produce observations.

    Args:
        failing: Feed whose layer should raise a query error.
        feature_set_with_geometry: Feature set returned for the successful feed.

    Returns:
        The callback bound to the supplied dependencies.
    """

    def layer_factory(
        url: str,
        gis: object,
    ) -> tests.helpers.doubles.arcgis.FeatureLayerStub:
        """Make one feed fail while allowing the other to produce observations.

        Args:
            url: ArcGIS layer or download URL supplied by the caller.
            gis: GIS connection object supplied to the layer constructor.

        Returns:
            A layer stub that fails or succeeds according to the requested URL.
        """
        if url == failing.url:
            return tests.helpers.doubles.arcgis.FeatureLayerStub(
                url,
                gis,
                arcgis.features.FeatureSet([]),
                query_error=RuntimeError("boom"),
            )
        return tests.helpers.doubles.arcgis.FeatureLayerStub(
            url,
            gis,
            feature_set_with_geometry,
        )

    return layer_factory


def fetch_with_probe(
    probe: tests.helpers.doubles.concurrency.ConcurrentCalls,
    feed: peri_scribe.sources.feed_types.Feed,
) -> peri_scribe.sources.fetching.FeedOutcome:
    """Return source outcomes after an observable overlap boundary.

    Args:
        probe: Gates and counters shared by the concurrent operations.
        feed: The source whose outcome should remain in configured order.

    Returns:
        A failure for source 1 and a recognizable path for every other source.
    """
    name = probe.run(feed.name)
    if name == "1":
        return peri_scribe.sources.fetching.FeedOutcome(error="source unavailable")
    return peri_scribe.sources.fetching.FeedOutcome(
        path=pathlib.Path(name),
        changed=True,
    )
