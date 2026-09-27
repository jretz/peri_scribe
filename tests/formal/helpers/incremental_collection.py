"""Connect the proved ID policy to real ArcGIS query selection and row comparison."""

from __future__ import annotations

import contextlib
import dataclasses
import datetime
import itertools
import pathlib
import sqlite3
import typing

import pytest
import shapely

import arcgis_access.exceptions
import peri_scribe.sources.changes
import peri_scribe.sources.feed_state
import peri_scribe.sources.feed_types
import peri_scribe.sources.fetching
import peri_scribe.sources.snapshots
import tests.helpers.doubles.peri_scribe.sources.fetching
import tests.helpers.factories.peri_scribe.sources.feed_types
import tests.helpers.factories.peri_scribe.sources.fetching


if typing.TYPE_CHECKING:
    import arcgis.features


@dataclasses.dataclass(frozen=True, kw_only=True)
class Case:
    """Independent stored and current source facts for a stable service view."""

    stored: dict[int, tests.helpers.factories.peri_scribe.sources.fetching.FetchFeature]
    current: dict[
        int,
        tests.helpers.factories.peri_scribe.sources.fetching.FetchFeature,
    ]
    full: bool


def cases() -> list[Case]:
    """Cover every combination of the three selection routes and content differences.

    Returns:
        Cases with known and unknown inactive spellings, deleted IDs, and overlap edges.
    """
    result: list[Case] = []
    feature = tests.helpers.factories.peri_scribe.sources.fetching.FetchFeature
    for (
        present,
        previous_active,
        active,
        modified,
        name,
        longitude,
        known,
        full,
    ) in itertools.product(
        (False, True),
        (False, True),
        (False, True),
        (-6, -5, -4, None),
        (0, 1),
        (0, 1),
        (False, True),
        (False, True),
    ):
        stored = {0: feature(name="0", active=True, modified_minute=0, longitude=0)}
        if known:
            stored[1] = feature(
                name="0",
                active=False,
                modified_minute=0,
                longitude=0,
            )
        current = dict(stored)
        if present:
            stored[2] = feature(
                name="0",
                active=previous_active,
                modified_minute=-6,
                longitude=0,
            )
        current[2] = feature(
            name=str(name),
            active=active,
            modified_minute=modified,
            longitude=longitude,
        )
        result.append(Case(stored=stored, current=current, full=full))
    for full in (False, True):
        stored = {0: feature(name="0", active=True, modified_minute=0, longitude=0)}
        result.append(Case(stored=stored, current={}, full=full))
    return result


def serialize(
    features: dict[
        int,
        tests.helpers.factories.peri_scribe.sources.fetching.FetchFeature,
    ],
) -> str:
    """Encode normalized source facts for Lean without deriving expected selections.

    Args:
        features: Rows keyed by unique object ID.

    Returns:
        The oracle's row list transport.
    """
    return (
        ";".join(
            f"{identifier},{feature.name},{int(feature.active)},"
            f"{'null' if feature.modified_minute is None else feature.modified_minute},"
            f"{feature.longitude}"
            for identifier, feature in sorted(features.items())
        )
        or "-"
    )


def command(case: Case) -> str:
    """Request the proved selection with the anchored high-water mark minus overlap.

    Args:
        case: Stored/current facts; the anchor's timestamp is always minute zero.

    Returns:
        A complete Lean selection request.
    """
    return (
        f"select {int(case.full)} -5 {serialize(case.stored)} {serialize(case.current)}"
    )


def replay(case: Case, expected: tuple[int, ...]) -> None:
    """Compare real fetching, SQL, normalization and geometry against the Lean result.

    Args:
        case: Stable source facts.
        expected: Object IDs returned by the compiled Lean definition.
    """
    stored_frame = tests.helpers.factories.peri_scribe.sources.fetching.fetch_frame(
        case.stored,
    )
    with (
        contextlib.closing(sqlite3.connect(":memory:")) as database,
        pytest.MonkeyPatch.context() as patch,
    ):
        layer = (
            tests.helpers.doubles.peri_scribe.sources.fetching.QueryableFeatureLayer(
                database,
                case.current,
            )
        )
        patch.setattr(
            peri_scribe.sources.feed_state,
            "read_current_features",
            lambda _directory, _feed: stored_frame,
        )
        try:
            actual = peri_scribe.sources.fetching.fetch_feed_dataframe(
                tests.helpers.factories.peri_scribe.sources.feed_types.change_feed(),
                typing.cast("arcgis.features.FeatureLayer", layer),
                [
                    peri_scribe.sources.snapshots.SourceFile(
                        serial_number=0,
                        last_edit_timestamp=0,
                    ),
                ],
                pathlib.Path("/unused-source-directory"),
                full=case.full,
            )
        except arcgis_access.exceptions.NoFeaturesError:
            assert case.full
            assert not case.current
            assert not expected
            return
    if not expected:
        assert actual is None
        return
    assert actual is not None
    assert tuple(actual.OBJECTID) == expected, case
    for _, row in actual.iterrows():
        feature = case.current[row.OBJECTID]
        assert row["name"] == feature.name
        assert row["status"] == ("Active" if feature.active else "Inactive")
        assert row[actual.geometry.name] == shapely.Point(feature.longitude, 0)
        assert peri_scribe.sources.changes.modified_datetime_from(
            row["ModifiedOnDateTime_dt"],
        ) == moment(feature.modified_minute)


def moment(minute: int | None) -> datetime.datetime | None:
    """Convert the finite time domain into real UTC datetimes.

    Args:
        minute: Offset from the fixture's reference time, or a missing timestamp.

    Returns:
        The corresponding UTC datetime, or None.
    """
    if minute is None:
        return None
    return (
        tests.helpers.factories.peri_scribe.sources.fetching.FETCH_REFERENCE_TIME
        + datetime.timedelta(minutes=minute)
    )


def metadata_query(*, full: bool, same: bool, directory: pathlib.Path) -> bool:
    """Observe the real metadata shortcut while replacing only network/data boundaries.

    Args:
        full: Whether to bypass incremental shortcuts.
        same: Whether an actual snapshot with matching metadata already exists.
        directory: Isolated snapshot root.

    Returns:
        Whether fetch_feed_snapshot queried source content.
    """
    timestamp = 1000
    feed = tests.helpers.doubles.peri_scribe.sources.fetching.FeedStub(
        name="metadata",
        url="https://example.test/feed",
        last_edit_timestamp=timestamp,
    )
    path = peri_scribe.sources.snapshots.source_geopackage_path(
        directory,
        2026,
        feed.name,
        peri_scribe.sources.snapshots.SourceFile(
            serial_number=0,
            last_edit_timestamp=timestamp if same else timestamp - 1,
        ),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    calls: list[bool] = []
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(
            peri_scribe.sources.fetching,
            "open_feed_connection",
            lambda _: None,
        )
        patch.setattr(
            peri_scribe.sources.fetching,
            "fetch_feed",
            lambda *_args, **_kwargs: calls.append(True),
        )
        outcome = peri_scribe.sources.fetching.fetch_feed_snapshot(
            typing.cast("peri_scribe.sources.feed_types.Feed", feed),
            base_dir=directory,
            year=2026,
            full=full,
        )
    assert outcome.error is None
    assert not outcome.changed
    return bool(calls)


def sql_time(minute: int | None) -> str | None:
    """Encode source timestamps for the independent SQLite predicate evaluator.

    Args:
        minute: The relative timestamp, or a missing value.

    Returns:
        ArcGIS-style UTC text, or SQL NULL.
    """
    value = moment(minute)
    return None if value is None else value.strftime("%Y-%m-%dT%H:%M:%SZ")
