"""Replay source query interleavings against the real snapshot collector."""

from __future__ import annotations

import dataclasses
import pathlib
import re
import shutil
import typing

import arcgis.features
import pytest

import peri_scribe.sources.feed_state
import peri_scribe.sources.feed_types
import peri_scribe.sources.fetching
import peri_scribe.sources.snapshots
import spatial_data.layers
import tests.helpers.doubles.arcgis
import tests.helpers.doubles.peri_scribe.sources.fetching
import tests.helpers.factories.peri_scribe.sources.fetching


if typing.TYPE_CHECKING:
    import geopandas


FEED_NAME = "snapshot_collection"
INITIAL_VERSIONS = (1, 0)
INITIAL_SNAPSHOT = peri_scribe.sources.snapshots.SourceFile(
    serial_number=0,
    last_edit_timestamp=1,
).relative_path
type RecoveryKey = tuple[tuple[int, ...], int, tuple[int, ...]]


@dataclasses.dataclass(frozen=True, kw_only=True)
class Collection:
    """Keep a fetch's complete observed input and checked persisted result."""

    full: bool
    marker: int
    changed: tuple[int, ...]
    listed: tuple[int, ...]
    selected: tuple[int, ...]
    body: tuple[int, ...]
    response: tuple[int, ...]
    saved: tuple[int, ...]
    receipt: int


@dataclasses.dataclass(frozen=True, kw_only=True)
class CollectionCase:
    """Pair the initial observations with the provider state after it settles."""

    initial: Collection
    remote: tuple[int, ...]
    remote_marker: int


def numbers(value: str) -> tuple[int, ...]:
    """Read the finite sequences and sets emitted by TLC without evaluating code.

    Args:
        value: Raw TLC text for a sequence or integer set.

    Returns:
        Integers in the emitted order.
    """
    return tuple(map(int, re.findall(r"\d+", value)))


def cases(states: list[dict[str, str]]) -> set[CollectionCase]:
    """Keep distinct completed first invocations, including post-query mutations.

    Args:
        states: All checked collection states.

    Returns:
        Executable query plans and the corresponding checked saved rows.
    """
    return {
        CollectionCase(
            initial=Collection(
                full=state["full"] == "TRUE",
                marker=int(state["observedMarker"]),
                changed=numbers(state["changed"]),
                listed=numbers(state["listed"]),
                selected=numbers(state["selected"]),
                body=numbers(state["atBody"]),
                response=numbers(state["response"]),
                saved=numbers(state["saved"]),
                receipt=int(state["receipt"]),
            ),
            remote=numbers(state["remote"]),
            remote_marker=int(state["marker"]),
        )
        for state in states
        if state["phase"] == '"done"' and state["recovery"] == "FALSE"
    }


def completed_recoveries(
    states: list[dict[str, str]],
) -> dict[RecoveryKey, set[tuple[int, ...]]]:
    """Index each complete recovery by its source inventory, marker, and saved base.

    Args:
        states: Every reachable TLC state for the snapshot collector.

    Returns:
        Every distinct completed inventory for each matching set of recovery inputs.
    """
    completed: dict[RecoveryKey, set[tuple[int, ...]]] = {}
    for state in states:
        if state["recovery"] == "TRUE" and state["phase"] == '"done"':
            key = (
                numbers(state["remote"]),
                int(state["observedMarker"]),
                numbers(state["recoveryBase"]),
            )
            completed.setdefault(key, set()).add(numbers(state["saved"]))
    return completed


def features(
    versions: tuple[int, ...],
) -> dict[
    int,
    tests.helpers.factories.peri_scribe.sources.fetching.FetchFeature,
]:
    """Give each abstract row version distinct attributes and stable point geometry.

    Args:
        versions: Version per object, where zero denotes an absent source row.

    Returns:
        Complete raw observations in the production feed schema.
    """
    return {
        identifier: tests.helpers.factories.peri_scribe.sources.fetching.FetchFeature(
            name=f"version{version}",
            active=False,
            modified_minute=0,
            longitude=-120 + identifier,
        )
        for identifier, version in enumerate(versions, 1)
        if version
    }


def write_seed_snapshot(directory: pathlib.Path) -> pathlib.Path:
    """Create the real retained snapshot that supplies each case's private copy.

    Args:
        directory: Isolated directory holding the completed seed file.

    Returns:
        The seed GeoPackage at its normal serial and edit-marker filename.
    """
    snapshot = directory / INITIAL_SNAPSHOT
    snapshot.parent.mkdir(parents=True)
    spatial_data.layers.write_geopackage(
        snapshot,
        [
            spatial_data.layers.LayerData(
                name=FEED_NAME,
                dataframe=tests.helpers.factories.peri_scribe.sources.fetching.fetch_frame(
                    features(INITIAL_VERSIONS),
                ),
            ),
        ],
    )
    return snapshot


class QueryInterleaving(tests.helpers.doubles.arcgis.FeatureLayerStubBase):
    """Expose independently captured ID queries and a later feature response."""

    def __init__(self, case: Collection) -> None:
        """Represent one finite source trace without contacting a service.

        Args:
            case: The TLC state containing each query's observed result.
        """
        super().__init__("https://example.test/FeatureServer/0", object())
        self.case = case
        self.queries: list[str] = []

    def query(self, **kwargs: object) -> arcgis.features.FeatureSet | dict[str, object]:
        """Validate real query routing before returning its checked source response.

        Args:
            kwargs: Parameters generated by the production collection code.

        Returns:
            The selected IDs or raw features from the corresponding source view.
        """
        if kwargs.get("return_ids_only"):
            where = str(kwargs["where"])
            self.queries.append("ids" if where == "1=1" else "changed")
            return {
                "objectIds": self.case.listed if where == "1=1" else self.case.changed,
            }
        self.queries.append("body")
        if not self.case.full:
            assert numbers(str(kwargs["object_ids"])) == self.case.selected
        chosen = (
            self.case.body
            if self.case.full
            else tuple(
                version if identifier in self.case.selected else 0
                for identifier, version in enumerate(self.case.body, 1)
            )
        )
        assert chosen == self.case.response
        return arcgis.features.FeatureSet([
            arcgis.features.Feature(
                attributes=tests.helpers.factories.peri_scribe.sources.fetching.fetch_attributes(
                    identifier,
                    feature,
                ),
                geometry={
                    "x": feature.longitude,
                    "y": 0,
                    "spatialReference": {"wkid": 4326},
                },
            )
            for identifier, feature in features(chosen).items()
        ])


def versions(dataframe: geopandas.GeoDataFrame | None) -> tuple[int, ...]:
    """Expose persisted names as row versions while asserting identity and geometry.

    Args:
        dataframe: The real current-state reader's result.

    Returns:
        Versions ordered by object ID, with zero for missing observations.
    """
    assert dataframe is not None
    found = {}
    for _index, row in dataframe.iterrows():
        identifier = int(row["OBJECTID"])
        assert row.geometry.x == -120 + identifier
        assert row.geometry.y == 0
        found[identifier] = int(str(row["name"]).removeprefix("version"))
    assert len(found) == len(dataframe)
    return tuple(found.get(identifier, 0) for identifier in (1, 2))


def collect(
    case: Collection,
    directory: pathlib.Path,
) -> tuple[peri_scribe.sources.fetching.FeedOutcome, tuple[int, ...], list[str]]:
    """Run the real collector and read back the persisted rows.

    Args:
        case: The observed provider state for this invocation.
        directory: Isolated application root.

    Returns:
        Collection outcome, persisted row versions, and issued query order.
    """
    feed = tests.helpers.doubles.peri_scribe.sources.fetching.FeedStub(
        name=FEED_NAME,
        url="https://example.test/FeatureServer/0",
        last_edit_timestamp=case.marker,
    )
    layer = QueryInterleaving(case)
    configured = typing.cast("peri_scribe.sources.feed_types.Feed", feed)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(arcgis.features, "FeatureLayer", lambda *_args: layer)
        patch.setattr(
            peri_scribe.sources.fetching,
            "open_feed_connection",
            lambda _: None,
        )
        outcome = peri_scribe.sources.fetching.fetch_feed_snapshot(
            configured,
            base_dir=directory,
            year=2026,
            full=case.full,
        )
    source_directory = peri_scribe.sources.snapshots.source_directory_path(
        directory,
        2026,
        FEED_NAME,
    )
    current = peri_scribe.sources.feed_state.read_current_features(
        source_directory,
        configured,
    )
    return outcome, versions(current), layer.queries


def replay_collection(
    case: Collection,
    directory: pathlib.Path,
    seed: pathlib.Path,
) -> None:
    """Record and check one exact initial collection before the provider settles.

    Args:
        case: The complete inputs and expected observations of the initial fetch.
        directory: A private directory whose completed files can seed recoveries.
        seed: The actual initial GeoPackage.
    """
    source_directory = peri_scribe.sources.snapshots.source_directory_path(
        directory,
        2026,
        FEED_NAME,
    )
    previous = source_directory / INITIAL_SNAPSHOT
    previous.parent.mkdir(parents=True)
    shutil.copyfile(seed, previous)
    outcome, saved, queries = collect(case, directory)
    assert saved == case.saved
    assert outcome.changed == (case.saved != INITIAL_VERSIONS)
    sources = peri_scribe.sources.snapshots.existing_source_files(source_directory)
    assert sources[-1].last_edit_timestamp == case.receipt
    expected_queries = (
        ["body"] if case.full else [] if case.marker == 1 else ["changed", "ids"]
    )
    if not case.full and case.selected:
        expected_queries.append("body")
    assert queries == expected_queries
    assert (outcome.error is not None) == (
        bool(case.selected) and case.response == (0, 0)
    )


def replay_recovery(
    case: CollectionCase,
    prefix: pathlib.Path,
    directory: pathlib.Path,
) -> tuple[int, ...]:
    """Recover from private copies of the actual initial collection files.

    Args:
        case: One checked history through initial collection and remote quiescence.
        prefix: The completed initial files for this history.
        directory: The isolated location for this continuation.

    Returns:
        Current stored versions after the post-quiescence full fetch.
    """
    shutil.copytree(prefix, directory)
    recovery = dataclasses.replace(
        case.initial,
        full=True,
        marker=case.remote_marker,
        body=case.remote,
        response=case.remote,
    )
    _outcome, saved, _queries = collect(recovery, directory)
    return saved
