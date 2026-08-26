"""Shared stubs for the peri_scribe.main command tests."""

from __future__ import annotations

import dataclasses
import pathlib
import typing

from tests.factories import FeatureLayerStubBase


if typing.TYPE_CHECKING:
    import arcgis.features

    import peri_scribe.fetching


SAMPLE_LAST_EDIT_TIMESTAMP = 2

# The base directory fetch resolves from ``pathlib.Path.cwd()``, which is mocked to
# this value so snapshots never touch the real filesystem.
BASE_DIRECTORY = pathlib.Path("/fetch")

# A FeatureLayer factory, as installed for the fetch command's layer construction.
LayerFactory = typing.Callable[[str, object], object]


class MultiQueryLayerStub(FeatureLayerStubBase):
    """FeatureLayer stand-in that returns/raises successive results per call."""

    def __init__(
        self,
        url: str,
        gis: object,
        query_outcomes: list[arcgis.features.FeatureSet | Exception],
    ) -> None:
        super().__init__(url, gis)
        self.query_outcomes = list(query_outcomes)
        self.call_count = 0

    def query(self) -> arcgis.features.FeatureSet:
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
        super().__init__(url, gis)
        self.feature_sets = list(feature_sets)
        self.call_count = 0
        self.events = [] if events is None else events

    def query(
        self,
        **_parameters: object,
    ) -> arcgis.features.FeatureSet:
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
        super().__init__(url, gis)
        self.full = full
        self.delta = delta

    def query(
        self,
        **parameters: object,
    ) -> arcgis.features.FeatureSet | dict[str, object]:
        if parameters.get("return_ids_only"):
            object_ids = [
                feature.attributes["OBJECTID"] for feature in self.delta.features
            ]
            return {"objectIdFieldName": "OBJECTID", "objectIds": object_ids}
        if parameters.get("object_ids"):
            return self.delta
        return self.full


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
        self.events.append("timestamp")
        return self.last_edit_timestamp


class RecordingFeatureLayerStub(FeatureLayerStubBase):
    """FeatureLayer stand-in that records when its data is downloaded."""

    def __init__(
        self,
        url: str,
        gis: object,
        feature_set: arcgis.features.FeatureSet,
        events: list[str],
    ) -> None:
        super().__init__(url, gis)
        self.feature_set = feature_set
        self.events = events

    def query(self) -> arcgis.features.FeatureSet:
        self.events.append("download")
        return self.feature_set


@dataclasses.dataclass(frozen=True, kw_only=True)
class FullPipelineStubs:
    """Fetch outcome and recorded step calls for full-pipeline tests."""

    fetch_result: peri_scribe.fetching.FetchResult
    fetch_calls: list[tuple[pathlib.Path, int, bool]]
    ensure_boundary_calls: list[pathlib.Path | None]
    history_calls: list[pathlib.Path]
    kmz_calls: list[pathlib.Path]


@dataclasses.dataclass(frozen=True, kw_only=True)
class FetchStubs:
    """Feed and FeatureLayer installers for fetch tests."""

    feeds: typing.Callable[..., None]
    feature_layers: typing.Callable[[LayerFactory], None]


@dataclasses.dataclass(frozen=True, kw_only=True)
class ValidateSourcesStubs:
    """Recorded step calls for validate-sources tests."""

    fetch_complete_calls: list[tuple[pathlib.Path, int]]
    fetch_incremental_calls: list[tuple[pathlib.Path, int]]
    validate_calls: list[pathlib.Path]
    removal_calls: list[pathlib.Path]
