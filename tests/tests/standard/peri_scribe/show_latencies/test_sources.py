"""Source polygon dates identify new availability independently of geometry changes."""

from __future__ import annotations

import contextlib
import datetime
import json
import pathlib
import sqlite3

import pytest

import peri_scribe.show_latencies.sources
import peri_scribe.sources.feeds
import tests.helpers.factories.peri_scribe.show_latencies.evidence
import tests.helpers.factories.peri_scribe.show_latencies.sources


def test_read_versions_counts_new_ids_and_polygon_dates_without_decoding_geometry(
    tmp_path: pathlib.Path,
) -> None:
    feed = peri_scribe.sources.feeds.WFIGS_PERIMETERS_FEED
    records = [
        tests.helpers.factories.peri_scribe.show_latencies.sources.record(feed),
        tests.helpers.factories.peri_scribe.show_latencies.sources.record(feed, 2),
        tests.helpers.factories.peri_scribe.show_latencies.sources.record(
            feed,
            surveyed=10,
        ),
        tests.helpers.factories.peri_scribe.show_latencies.sources.record(
            feed,
            created=20,
        ),
    ]
    paths = [
        tests.helpers.factories.peri_scribe.show_latencies.sources.snapshot(
            tmp_path,
            feed,
            index,
            index * 10,
            [record],
        )
        for index, record in enumerate(records)
    ]
    publications = peri_scribe.show_latencies.sources.read_versions(
        tmp_path,
        tests.helpers.factories.peri_scribe.show_latencies.evidence.WINDOW,
    )
    assert [publication.source_file for publication in publications] == [
        str(path.relative_to(tmp_path / "sources")) for path in paths
    ]


def test_read_versions_ignores_cost_point_and_repeated_metadata_updates(
    tmp_path: pathlib.Path,
) -> None:
    feed = peri_scribe.sources.feeds.WFIGS_PERIMETERS_FEED
    record = tests.helpers.factories.peri_scribe.show_latencies.sources.record(feed)
    tests.helpers.factories.peri_scribe.show_latencies.sources.snapshot(
        tmp_path,
        feed,
        1,
        -10,
        [record],
    )
    tests.helpers.factories.peri_scribe.show_latencies.sources.snapshot(
        tmp_path,
        feed,
        2,
        10,
        [
            {
                **record,
                "attr_EstimatedCostToDate": 100,
                "attr_ModifiedOnDateTime_dt": "new",
            },
        ],
    )
    points = peri_scribe.sources.feeds.WFIGS_INCIDENT_LOCATIONS_FEED
    tests.helpers.factories.peri_scribe.show_latencies.sources.snapshot(
        tmp_path,
        points,
        3,
        20,
        [tests.helpers.factories.peri_scribe.show_latencies.sources.record(points)],
        geometry_type="POINT",
    )
    assert not peri_scribe.show_latencies.sources.read_versions(
        tmp_path,
        tests.helpers.factories.peri_scribe.show_latencies.evidence.WINDOW,
    )


def test_read_versions_without_polygon_dates_counts_each_object_only_once(
    tmp_path: pathlib.Path,
) -> None:
    feed = peri_scribe.sources.feeds.CA_PERIMETERS_FEED
    record = tests.helpers.factories.peri_scribe.show_latencies.sources.record(
        feed,
        surveyed=None,
    )
    paths = [
        tests.helpers.factories.peri_scribe.show_latencies.sources.snapshot(
            tmp_path,
            feed,
            serial,
            serial * 10,
            [dict(record, EditDate=str(serial))],
        )
        for serial in (1, 2)
    ]
    publications = peri_scribe.show_latencies.sources.read_versions(
        tmp_path,
        tests.helpers.factories.peri_scribe.show_latencies.evidence.WINDOW,
    )
    assert [publication.source_file for publication in publications] == [
        str(paths[0].relative_to(tmp_path / "sources")),
    ]


def test_read_versions_uses_earliest_publication_with_inclusive_window_bounds(
    tmp_path: pathlib.Path,
) -> None:
    feed = peri_scribe.sources.feeds.CA_PERIMETERS_FEED
    for serial, seconds in enumerate((0, -10, 3600, 3601)):
        tests.helpers.factories.peri_scribe.show_latencies.sources.snapshot(
            tmp_path,
            feed,
            serial,
            seconds,
            [
                tests.helpers.factories.peri_scribe.show_latencies.sources.record(
                    feed,
                    serial,
                ),
            ],
        )
    publications = peri_scribe.show_latencies.sources.read_versions(
        tmp_path,
        tests.helpers.factories.peri_scribe.show_latencies.evidence.WINDOW,
    )
    assert [publication.published for publication in publications] == [
        tests.helpers.factories.peri_scribe.show_latencies.evidence.WINDOW.start,
        tests.helpers.factories.peri_scribe.show_latencies.evidence.WINDOW.end,
    ]


def test_read_versions_merges_indexed_aliases_and_retains_new_fire_identifiers(
    tmp_path: pathlib.Path,
) -> None:
    feed = peri_scribe.sources.feeds.CA_PERIMETERS_FEED
    tests.helpers.factories.peri_scribe.show_latencies.sources.snapshot(
        tmp_path,
        feed,
        1,
        10,
        [
            tests.helpers.factories.peri_scribe.show_latencies.sources.record(
                feed,
                identifier=" {ALIASED} ",
            ),
            tests.helpers.factories.peri_scribe.show_latencies.sources.record(
                feed,
                2,
                identifier="NEW-FIRE",
            ),
        ],
    )
    (tmp_path / "sources/fires.json").write_text(
        json.dumps({
            "fires": [
                {
                    "identifier": "canonical",
                    "name": "First",
                    "aliases": [" {ALIASED} ", ""],
                },
                {"identifier": None, "name": "Nameless Alias", "aliases": ["another"]},
            ],
        }),
    )
    publications = peri_scribe.show_latencies.sources.read_versions(
        tmp_path,
        tests.helpers.factories.peri_scribe.show_latencies.evidence.WINDOW,
    )
    assert [publication.identifier for publication in publications] == [
        "canonical",
        "new-fire",
    ]


@pytest.mark.parametrize(
    "geometry",
    [None, b"", b"bad header", b"GP\x00\x11empty geometry"],
)
def test_snapshot_versions_excludes_missing_empty_or_invalid_polygon_headers(
    tmp_path: pathlib.Path,
    geometry: bytes | None,
) -> None:
    feed = peri_scribe.sources.feeds.CA_PERIMETERS_FEED
    path = tests.helpers.factories.peri_scribe.show_latencies.sources.snapshot(
        tmp_path,
        feed,
        1,
        10,
        [
            tests.helpers.factories.peri_scribe.show_latencies.sources.record(
                feed,
                geometry=geometry,
            ),
        ],
    )
    assert not tuple(
        peri_scribe.show_latencies.sources.snapshot_versions(path, feed, {}),
    )


@pytest.mark.parametrize("geometry_type", ["POINT", "absent"])
def test_snapshot_versions_excludes_nonpolygon_layers(
    tmp_path: pathlib.Path,
    geometry_type: str,
) -> None:
    feed = peri_scribe.sources.feeds.CA_PERIMETERS_FEED
    path = tests.helpers.factories.peri_scribe.show_latencies.sources.snapshot(
        tmp_path,
        feed,
        1,
        10,
        [tests.helpers.factories.peri_scribe.show_latencies.sources.record(feed)],
        geometry_type=geometry_type,
    )
    if geometry_type == "absent":
        with contextlib.closing(sqlite3.connect(path)) as connection:
            connection.execute("DELETE FROM gpkg_geometry_columns")
            connection.commit()
    assert not tuple(
        peri_scribe.show_latencies.sources.snapshot_versions(path, feed, {}),
    )


@pytest.mark.parametrize(
    ("name", "mission", "expected"),
    [
        (" Bear Fire ", None, "name:bear fire"),
        (None, "CA-NOD-STEER-N874EB", "name:steer"),
        (None, None, "record:CA_Perimeters_NIFC_FIRIS_public_view_0#1"),
    ],
)
def test_snapshot_versions_preserves_fires_without_assigned_identifiers(
    tmp_path: pathlib.Path,
    name: str | None,
    mission: str | None,
    expected: str,
) -> None:
    feed = peri_scribe.sources.feeds.CA_PERIMETERS_FEED
    row = tests.helpers.factories.peri_scribe.show_latencies.sources.record(
        feed,
        identifier=None,
        name=name,
    )
    row["mission"] = mission
    path = tests.helpers.factories.peri_scribe.show_latencies.sources.snapshot(
        tmp_path,
        feed,
        1,
        10,
        [row],
    )
    result = tuple(peri_scribe.show_latencies.sources.snapshot_versions(path, feed, {}))
    assert result[0][1] == expected


def test_snapshot_versions_allows_missing_object_identifier_and_optional_dates(
    tmp_path: pathlib.Path,
) -> None:
    feed = peri_scribe.sources.feeds.WFIGS_PERIMETERS_FEED
    row = tests.helpers.factories.peri_scribe.show_latencies.sources.record(feed, None)
    del row["poly_DateCurrent"]
    del row["poly_CreateDate"]
    path = tests.helpers.factories.peri_scribe.show_latencies.sources.snapshot(
        tmp_path,
        feed,
        1,
        10,
        [row],
        geometry_type="MULTIPOLYGON",
    )
    result = tuple(peri_scribe.show_latencies.sources.snapshot_versions(path, feed, {}))
    assert result == (
        (
            peri_scribe.show_latencies.sources.Version(
                object_id="fire",
                surveyed=None,
                created=None,
            ),
            "fire",
        ),
    )


def test_snapshot_versions_normalizes_equivalent_timezone_spellings(
    tmp_path: pathlib.Path,
) -> None:
    feed = peri_scribe.sources.feeds.WFIGS_PERIMETERS_FEED
    row = tests.helpers.factories.peri_scribe.show_latencies.sources.record(feed)
    row["poly_DateCurrent"] = "2026-09-01T05:00:00-07:00"
    path = tests.helpers.factories.peri_scribe.show_latencies.sources.snapshot(
        tmp_path,
        feed,
        1,
        10,
        [row],
    )
    result = tuple(peri_scribe.show_latencies.sources.snapshot_versions(path, feed, {}))
    assert result[0][0].surveyed == datetime.datetime(
        2026,
        9,
        1,
        12,
        tzinfo=datetime.UTC,
    )


def test_read_versions_resolves_same_names_only_within_their_indexed_source_paths(
    tmp_path: pathlib.Path,
) -> None:
    feed = peri_scribe.sources.feeds.CA_PERIMETERS_FEED
    paths = [
        tests.helpers.factories.peri_scribe.show_latencies.sources.snapshot(
            tmp_path,
            feed,
            serial,
            serial * 10,
            [
                tests.helpers.factories.peri_scribe.show_latencies.sources.record(
                    feed,
                    serial,
                    identifier=None,
                ),
            ],
        )
        for serial in (1, 2, 3)
    ]
    (tmp_path / "sources/fires.json").write_text(
        json.dumps({
            "fires": [
                {
                    "identifier": identifier,
                    "name": "First",
                    "paths": [str(path.relative_to(tmp_path / "sources"))],
                }
                for path, identifier in zip(
                    paths[:2],
                    ("fire-a", "fire-b"),
                    strict=True,
                )
            ],
        }),
    )
    publications = peri_scribe.show_latencies.sources.read_versions(
        tmp_path,
        tests.helpers.factories.peri_scribe.show_latencies.evidence.WINDOW,
    )
    assert [publication.identifier for publication in publications] == [
        "fire-a",
        "fire-b",
        "name:first",
    ]


@pytest.mark.parametrize(
    ("first_identifier", "second_identifier"),
    [("known", "known"), ("known", "another"), (None, None)],
)
def test_read_versions_keeps_ambiguous_indexed_names_scoped_to_source_records(
    tmp_path: pathlib.Path,
    first_identifier: str | None,
    second_identifier: str | None,
) -> None:
    feed = peri_scribe.sources.feeds.CA_PERIMETERS_FEED
    path = tests.helpers.factories.peri_scribe.show_latencies.sources.snapshot(
        tmp_path,
        feed,
        1,
        10,
        [
            tests.helpers.factories.peri_scribe.show_latencies.sources.record(
                feed,
                object_id,
                identifier=None,
            )
            for object_id in (1, 2)
        ],
    )
    (tmp_path / "sources/fires.json").write_text(
        json.dumps({
            "fires": [
                {
                    "identifier": identifier,
                    "name": " First ",
                    "paths": [str(path.relative_to(tmp_path / "sources"))],
                }
                for identifier in (first_identifier, second_identifier)
            ],
        }),
    )
    publications = peri_scribe.show_latencies.sources.read_versions(
        tmp_path,
        tests.helpers.factories.peri_scribe.show_latencies.evidence.WINDOW,
    )
    expected = (
        ["known", "known"]
        if second_identifier == "known"
        else [f"record:{feed.name}#{object_id}" for object_id in (1, 2)]
    )
    assert [publication.identifier for publication in publications] == expected


def test_read_versions_reuses_each_unidentified_index_entry_across_its_source_paths(
    tmp_path: pathlib.Path,
) -> None:
    feed = peri_scribe.sources.feeds.CA_PERIMETERS_FEED
    paths = [
        tests.helpers.factories.peri_scribe.show_latencies.sources.snapshot(
            tmp_path,
            feed,
            serial,
            serial * 10,
            [
                tests.helpers.factories.peri_scribe.show_latencies.sources.record(
                    feed,
                    serial,
                    identifier=None,
                    name="Bear",
                ),
            ],
        )
        for serial in (1, 2, 3, 4)
    ]
    relative = [str(path.relative_to(tmp_path / "sources")) for path in paths]
    (tmp_path / "sources/fires.json").write_text(
        json.dumps({
            "fires": [
                {"identifier": None, "name": "Bear", "paths": relative[::2]},
                {"identifier": None, "name": "Bear", "paths": relative[1::2]},
            ],
        }),
    )
    publications = peri_scribe.show_latencies.sources.read_versions(
        tmp_path,
        tests.helpers.factories.peri_scribe.show_latencies.evidence.WINDOW,
    )
    first, second, first_again, second_again = publications
    assert first.identifier == first_again.identifier
    assert second.identifier == second_again.identifier
    assert first.identifier != second.identifier
