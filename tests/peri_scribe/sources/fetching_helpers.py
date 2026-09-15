"""Provide data builders and stand-ins for fetching tests."""

from __future__ import annotations

import dataclasses
import pathlib
import typing

import arcgis.features

import peri_scribe.exceptions
import peri_scribe.output
import peri_scribe.sources.feed_types
import peri_scribe.sources.fetching
import peri_scribe.sources.snapshots
from tests.conftest import SAMPLE_FEED_NAME, SAMPLE_FEED_URL
from tests.factories import FeatureLayerStub, FeatureLayerStubBase
from tests.main_stubs import SAMPLE_LAST_EDIT_TIMESTAMP


if typing.TYPE_CHECKING:
    import pytest


def complete_fetch_feed(index: int) -> peri_scribe.sources.feed_types.ArcGISFeed:
    """Return a feed with a name unique to *index*.

    Args:
        index: The number that distinguishes the feed's name.

    Returns:
        The feed.
    """
    return peri_scribe.sources.feed_types.ArcGISFeed(
        url=(f"https://example.test/ArcGIS/rest/services/Fires{index}/FeatureServer/0"),
        fire_name_column="name",
        status_column="status",
    )


def stub_complete_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the complete fetch's file and network boundaries at in-memory stubs.

    Args:
        monkeypatch: The monkeypatch fixture.
    """
    monkeypatch.setattr(peri_scribe.sources.fetching.arcgis.gis, "GIS", object)
    monkeypatch.setattr(pathlib.Path, "mkdir", lambda *_arguments, **_keywords: None)
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


class MultiQueryLayerStub(FeatureLayerStubBase):
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


class SequenceFeatureLayerStub(FeatureLayerStubBase):
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

    def query(self, **_parameters: object) -> arcgis.features.FeatureSet:
        """Record a download and serve the next available feature set.

        Args:
            _parameters: Query options accepted for compatibility with ArcGIS callers.

        Returns:
            The next feature set, repeating the last after the sequence is exhausted.
        """
        self.events.append("download")
        feature_set = self.feature_sets[
            min(self.call_count, len(self.feature_sets) - 1)
        ]
        self.call_count += 1
        return feature_set


class DeltaFeatureLayerStub(FeatureLayerStubBase):
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

    def query(
        self,
        **parameters: object,
    ) -> arcgis.features.FeatureSet | dict[str, object]:
        """Serve complete rows, changed rows, or their object identifiers.

        Args:
            parameters: Parameters supplied to the intercepted query or command.

        Returns:
            The delta identifiers for ID queries, delta rows for ID filters, or full
            rows.
        """
        if parameters.get("return_ids_only"):
            object_ids = [
                feature.attributes["OBJECTID"] for feature in self.delta.features
            ]
            return {"objectIdFieldName": "OBJECTID", "objectIds": object_ids}
        if parameters.get("object_ids"):
            return self.delta
        return self.full


class RecordingFeatureLayerStub(FeatureLayerStubBase):
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
        name=SAMPLE_FEED_NAME,
        url=SAMPLE_FEED_URL,
        last_edit_timestamp=SAMPLE_LAST_EDIT_TIMESTAMP,
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

    def capture_where(*_arguments: object, **_keywords: object) -> list[int]:
        """Capture the filter used to query rows with missing modification dates.

        Args:
            _arguments: Positional arguments accepted by the substituted dependency.
            _keywords: Keyword arguments accepted by the substituted dependency.

        Returns:
            An empty object-ID list.
        """
        captured.append(str(_keywords["where"]))
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

    def query_ids(*_arguments: object, **_keywords: object) -> list[int]:
        """Serve object identifiers for full and active-row queries.

        Args:
            _arguments: Positional arguments accepted by the substituted dependency.
            _keywords: Keyword arguments accepted by the substituted dependency.

        Returns:
            The configured object identifiers matching the query filter.
        """
        where = str(_keywords["where"])
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


def fail_state_update(*_arguments: object, **_keywords: object) -> None:
    """Simulate failure to persist a feed's current state.

    Args:
        _arguments: Positional arguments accepted by the substituted dependency.
        _keywords: Keyword arguments accepted by the substituted dependency.

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
) -> typing.Callable[..., FeatureLayerStub]:
    """Create a callback with controlled dependencies.

    Make one feed fail while allowing the other to produce observations.

    Args:
        failing: Feed whose layer should raise a query error.
        feature_set_with_geometry: Feature set returned for the successful feed.

    Returns:
        The callback bound to the supplied dependencies.
    """

    def layer_factory(url: str, gis: object) -> FeatureLayerStub:
        """Make one feed fail while allowing the other to produce observations.

        Args:
            url: ArcGIS layer or download URL supplied by the caller.
            gis: GIS connection object supplied to the layer constructor.

        Returns:
            A layer stub that fails or succeeds according to the requested URL.
        """
        if url == failing.url:
            return FeatureLayerStub(
                url,
                gis,
                arcgis.features.FeatureSet([]),
                query_error=RuntimeError("boom"),
            )
        return FeatureLayerStub(url, gis, feature_set_with_geometry)

    return layer_factory
