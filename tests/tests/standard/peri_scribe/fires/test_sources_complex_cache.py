"""Temporal complex ownership survives real snapshot parsing and record reuse."""

import pathlib
import sqlite3
import unittest.mock

import pytest

import peri_scribe.fires.sources
import peri_scribe.geo.database
import peri_scribe.geo.package
import peri_scribe.sources.feed_types
import peri_scribe.sources.feeds
import tests.helpers.factories.peri_scribe.fires.complex_cache
import tests.helpers.peri_scribe.geo.package


@pytest.mark.parametrize(
    "feed",
    [
        peri_scribe.sources.feeds.WFIGS_PERIMETERS_FEED,
        peri_scribe.sources.feeds.WFIGS_INCIDENT_LOCATIONS_FEED,
    ],
    ids=["perimeter", "location"],
)
@pytest.mark.parametrize("release", [False, True], ids=["transfer", "release"])
@pytest.mark.parametrize(
    "primary_identifier",
    [None, "unknown-primary"],
    ids=["missing-primary", "unknown-primary"],
)
def test_read_fire_sources_resolves_unnamed_relationships_by_secondary_identifier(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    feed: peri_scribe.sources.feed_types.Feed,
    primary_identifier: str | None,
    *,
    release: bool,
) -> None:
    paths = tests.helpers.factories.peri_scribe.fires.complex_cache.alias_snapshots(
        tmp_path,
        feed,
        primary_identifier=primary_identifier,
        release=release,
    )
    parse = unittest.mock.Mock(wraps=peri_scribe.geo.package.read_geopackage)
    monkeypatch.setattr(peri_scribe.geo.package, "read_geopackage", parse)
    cold = peri_scribe.fires.sources.read_fire_sources(tmp_path)
    assert parse.call_count == len(paths)
    parse.reset_mock()
    warm = peri_scribe.fires.sources.read_fire_sources(tmp_path)
    parse.assert_not_called()
    assert warm == cold
    assert len(cold.rows) == 1
    for read in (cold, warm):
        groups = peri_scribe.fires.sources.group_fire_sources(read)
        (child,) = groups.fires
        if release:
            assert child.complex is None
        else:
            assert child.complex is not None
            assert child.complex.identifier == "new-parent"
            assert child.complex.fires == frozenset({child})


@pytest.mark.parametrize(
    "feed",
    [
        peri_scribe.sources.feeds.WFIGS_PERIMETERS_FEED,
        peri_scribe.sources.feeds.WFIGS_INCIDENT_LOCATIONS_FEED,
    ],
    ids=["perimeter", "location"],
)
def test_read_fire_sources_reparses_cached_relationships_missing_secondary_aliases(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    feed: peri_scribe.sources.feed_types.Feed,
) -> None:
    paths = tests.helpers.factories.peri_scribe.fires.complex_cache.alias_snapshots(
        tmp_path,
        feed,
        primary_identifier=None,
        release=True,
    )
    peri_scribe.fires.sources.read_fire_sources(tmp_path)
    database_path = tests.helpers.peri_scribe.geo.package.record_cache_database_path(
        paths[0],
    )
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA user_version = 6")
        connection.execute(
            "DELETE FROM memberships WHERE fire_identifier = 'child-secondary'",
        )
    connection.close()
    # A fresh process must rebuild evidence from unchanged authoritative snapshots.
    peri_scribe.geo.database.RECORD_CACHE_SYNCED.pop(database_path)
    parse = unittest.mock.Mock(wraps=peri_scribe.geo.package.read_geopackage)
    monkeypatch.setattr(peri_scribe.geo.package, "read_geopackage", parse)
    rebuilt = peri_scribe.fires.sources.read_fire_sources(tmp_path)
    assert parse.call_count == len(paths)
    parse.reset_mock()
    warm = peri_scribe.fires.sources.read_fire_sources(tmp_path)
    parse.assert_not_called()
    assert warm == rebuilt
    (child,) = peri_scribe.fires.sources.group_fire_sources(warm).fires
    assert child.complex is None


@pytest.mark.parametrize(
    "feed",
    [
        peri_scribe.sources.feeds.WFIGS_PERIMETERS_FEED,
        peri_scribe.sources.feeds.WFIGS_INCIDENT_LOCATIONS_FEED,
    ],
    ids=["perimeter", "location"],
)
@pytest.mark.parametrize("release", [False, True], ids=["return", "release"])
@pytest.mark.parametrize("reverse", [False, True], ids=["forward", "reverse"])
def test_read_fire_sources_retains_distinct_dated_declarations_in_one_snapshot(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    feed: peri_scribe.sources.feed_types.Feed,
    *,
    release: bool,
    reverse: bool,
) -> None:
    path = tests.helpers.factories.peri_scribe.fires.complex_cache.correction_snapshot(
        tmp_path,
        feed,
        release=release,
        reverse=reverse,
    )
    cold = peri_scribe.fires.sources.read_fire_sources(tmp_path)
    parse = unittest.mock.Mock(wraps=peri_scribe.geo.package.read_geopackage)
    monkeypatch.setattr(peri_scribe.geo.package, "read_geopackage", parse)
    warm = peri_scribe.fires.sources.read_fire_sources(tmp_path)
    parse.assert_not_called()
    assert warm == cold
    assert cold.paths == (path, path)
    assert cold.membership_paths == (path, path, path)
    for read in (cold, warm):
        groups = peri_scribe.fires.sources.group_fire_sources(read)
        (child,) = groups.fires
        if release:
            assert child.complex is None
        else:
            assert child.complex is not None
            assert child.complex.identifier == "first-parent"
            assert child.complex.fires == frozenset({child})


@pytest.mark.parametrize(
    "feed",
    [
        peri_scribe.sources.feeds.WFIGS_PERIMETERS_FEED,
        peri_scribe.sources.feeds.WFIGS_INCIDENT_LOCATIONS_FEED,
    ],
    ids=["perimeter", "location"],
)
@pytest.mark.parametrize("release", [False, True], ids=["transfer", "release"])
def test_read_fire_sources_preserves_complex_chronology_through_record_cache(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    feed: peri_scribe.sources.feed_types.Feed,
    *,
    release: bool,
) -> None:
    paths = tests.helpers.factories.peri_scribe.fires.complex_cache.snapshots(
        tmp_path,
        feed,
        release=release,
    )
    parse = unittest.mock.Mock(wraps=peri_scribe.geo.package.read_geopackage)
    monkeypatch.setattr(peri_scribe.geo.package, "read_geopackage", parse)
    cold = peri_scribe.fires.sources.read_fire_sources(tmp_path)
    assert parse.call_count == len(paths)
    parse.reset_mock()
    warm = peri_scribe.fires.sources.read_fire_sources(tmp_path)
    parse.assert_not_called()
    assert warm == cold
    assert warm.paths == paths
    assert warm.membership_paths == paths
    groups = peri_scribe.fires.sources.group_fire_sources(warm)
    (child,) = groups.fires
    if release:
        assert child.complex is None
    else:
        assert child.complex is not None
        assert child.complex.identifier == "new-parent"
        assert child.complex.fires == frozenset({child})
    assert groups.complex_identifiers == frozenset({"old-parent", "new-parent"})


@pytest.mark.parametrize("release", [False, True], ids=["old-assignment", "release"])
def test_read_fire_sources_keeps_dated_relationships_without_a_parsed_fire_row(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    release: bool,
) -> None:
    feed = peri_scribe.sources.feeds.WFIGS_PERIMETERS_FEED
    paths = tests.helpers.factories.peri_scribe.fires.complex_cache.snapshots(
        tmp_path,
        feed,
        release=release,
        unparsed=2 if release else 1,
    )
    cold = peri_scribe.fires.sources.read_fire_sources(tmp_path)
    parse = unittest.mock.Mock(wraps=peri_scribe.geo.package.read_geopackage)
    monkeypatch.setattr(peri_scribe.geo.package, "read_geopackage", parse)
    warm = peri_scribe.fires.sources.read_fire_sources(tmp_path)
    parse.assert_not_called()
    assert warm == cold
    assert len(warm.rows) == len(paths) - 1
    groups = peri_scribe.fires.sources.group_fire_sources(warm)
    (child,) = groups.fires
    if release:
        assert child.complex is None
    else:
        assert child.complex is not None
        assert child.complex.identifier == "new-parent"
    assert warm.membership_paths == paths
