"""Tests for peri_scribe.fires.grouping."""

from __future__ import annotations

import datetime

import shapely.geometry
import structlog

import peri_scribe.fires.grouping
import peri_scribe.geo.parsing
import peri_scribe.models
import peri_scribe.sources.feeds
import tests.helpers.factories.peri_scribe.geo.parsing
import tests.helpers.factories.peri_scribe.models
import tests.helpers.peri_scribe.fires.grouping


def test_group_fire_record_indices_merges_dome_missions_with_nearby_fire() -> None:
    active = tests.helpers.factories.peri_scribe.models.ACTIVE
    geometry = shapely.geometry.Point(-119.5, 37.8)
    records = [
        tests.helpers.factories.peri_scribe.models.fire_record(
            "DOME",
            active,
            identifiers={"2026-caynp-000100"},
            geometry=geometry,
        ),
    ]
    for mission in ("CA-YNP-DOME-N5852K", "CA-YNP-DOME-N874EB"):
        record = peri_scribe.geo.parsing.fire_record_from_row(
            tests.helpers.factories.peri_scribe.geo.parsing.mission_row(mission),
            peri_scribe.sources.feeds.CA_PERIMETERS_FEED,
            geometry,
        )
        assert record is not None
        records.append(record)
    records.append(
        tests.helpers.factories.peri_scribe.models.fire_record(
            "Dome",
            active,
            identifiers={"2026-idscf-260166"},
            geometry=shapely.geometry.Point(-114.5, 45.0),
        ),
    )
    assert peri_scribe.fires.grouping.group_fire_record_indices(records) == [
        [0, 1, 2],
        [3],
    ]


def test_group_fire_record_indices_merges_vista_abbreviated_mission() -> None:
    perimeter = peri_scribe.geo.parsing.fire_record_from_row(
        tests.helpers.factories.peri_scribe.geo.parsing.mission_row("CA-RRU-VISTA-50X"),
        peri_scribe.sources.feeds.CA_PERIMETERS_FEED,
        shapely.geometry.box(-117.3244, 33.7204, -117.3148, 33.7324),
    )
    assert perimeter is not None
    incident = tests.helpers.factories.peri_scribe.models.fire_record(
        "VISTA",
        tests.helpers.factories.peri_scribe.models.ACTIVE,
        identifiers={"2026-carru-062639"},
        geometry=shapely.geometry.box(-117.3244, 33.7192, -117.3142, 33.7324),
    )
    distant_incident = tests.helpers.factories.peri_scribe.models.fire_record(
        "Vista",
        tests.helpers.factories.peri_scribe.models.ACTIVE,
        identifiers={"2026-nmsnf-000515"},
        geometry=shapely.geometry.Point(-106.5419, 36.3334),
    )
    assert peri_scribe.fires.grouping.group_fire_record_indices(
        [perimeter, incident, distant_incident],
    ) == [[0, 1], [2]]


def test_most_common_fire_prefers_unique_fire_identifier_over_guid() -> None:
    unique_id = "2026-nvccd-030683"
    guid = "286b7f1d-8945-4a5d-9d81-5235c18af1fe"
    occurrences = [
        tests.helpers.factories.peri_scribe.models.fire_record(
            "Bug",
            tests.helpers.factories.peri_scribe.models.ACTIVE,
            identifiers={guid},
        ),
        tests.helpers.factories.peri_scribe.models.fire_record(
            "Bug",
            tests.helpers.factories.peri_scribe.models.ACTIVE,
            identifiers={unique_id, guid},
        ),
    ]
    assert peri_scribe.fires.grouping.most_common_fire(occurrences) == (
        peri_scribe.models.Fire(
            name="Bug",
            status=tests.helpers.factories.peri_scribe.models.ACTIVE,
            identifier=unique_id,
            aliases=frozenset({unique_id, guid}),
        )
    )


def test_most_common_fire_uses_guid_without_unique_fire_identifier() -> None:
    guid = "286b7f1d-8945-4a5d-9d81-5235c18af1fe"
    occurrences = [
        tests.helpers.factories.peri_scribe.models.fire_record(
            "Bug",
            tests.helpers.factories.peri_scribe.models.ACTIVE,
            identifiers={guid},
        ),
    ]
    assert peri_scribe.fires.grouping.most_common_fire(occurrences) == (
        peri_scribe.models.Fire(
            name="Bug",
            status=tests.helpers.factories.peri_scribe.models.ACTIVE,
            identifier=guid,
            aliases=frozenset({guid}),
        )
    )


def test_is_mixed_case() -> None:
    assert peri_scribe.fires.grouping.is_mixed_case("Park Fire")
    assert not peri_scribe.fires.grouping.is_mixed_case("PARK FIRE")
    assert not peri_scribe.fires.grouping.is_mixed_case("park fire")
    assert not peri_scribe.fires.grouping.is_mixed_case("3-1")


def test_warn_for_inconsistent_fires_ignores_group_without_geometries() -> None:
    records = [
        tests.helpers.factories.peri_scribe.models.fire_record(
            "RIVER",
            tests.helpers.factories.peri_scribe.models.ACTIVE,
        ),
        tests.helpers.factories.peri_scribe.models.fire_record(
            "RIVER",
            tests.helpers.factories.peri_scribe.models.INACTIVE,
        ),
    ]
    fires = [
        peri_scribe.models.Fire(
            name="RIVER",
            status=tests.helpers.factories.peri_scribe.models.ACTIVE,
        ),
    ]
    assert tests.helpers.peri_scribe.fires.grouping.warning_events(records, fires) == []


def test_warn_for_inconsistent_fires_logs_outlier_for_record_without_geometry() -> None:
    records = [
        tests.helpers.factories.peri_scribe.models.fire_record(
            "RIVER",
            tests.helpers.factories.peri_scribe.models.ACTIVE,
            geometry=shapely.geometry.Point(0, 0),
        ),
        tests.helpers.factories.peri_scribe.models.fire_record(
            "RIVER",
            tests.helpers.factories.peri_scribe.models.INACTIVE,
        ),
    ]
    fires = [
        peri_scribe.models.Fire(
            name="RIVER",
            status=tests.helpers.factories.peri_scribe.models.ACTIVE,
        ),
    ]
    assert [
        event["event"]
        for event in tests.helpers.peri_scribe.fires.grouping.warning_events(
            records,
            fires,
        )
    ] == ["Fire records span distant locations"]


def test_warn_for_inconsistent_fires_logs_outlier_when_other_geometries_empty() -> None:
    records = [
        tests.helpers.factories.peri_scribe.models.fire_record(
            "RIVER",
            tests.helpers.factories.peri_scribe.models.ACTIVE,
            geometry=shapely.geometry.Point(),
        ),
        tests.helpers.factories.peri_scribe.models.fire_record(
            "RIVER",
            tests.helpers.factories.peri_scribe.models.INACTIVE,
            geometry=shapely.geometry.Point(0, 0),
        ),
    ]
    fires = [
        peri_scribe.models.Fire(
            name="RIVER",
            status=tests.helpers.factories.peri_scribe.models.ACTIVE,
        ),
    ]
    assert [
        event["event"]
        for event in tests.helpers.peri_scribe.fires.grouping.warning_events(
            records,
            fires,
        )
    ] == ["Fire records span distant locations"]


def test_warn_for_inconsistent_fires_logs_spatial_outlier() -> None:
    records = [
        tests.helpers.factories.peri_scribe.models.fire_record(
            "RIVER",
            tests.helpers.factories.peri_scribe.models.ACTIVE,
            geometry=shapely.geometry.Point(0, 0),
        ),
        tests.helpers.factories.peri_scribe.models.fire_record(
            "River",
            tests.helpers.factories.peri_scribe.models.ACTIVE,
            identifiers={"67e0a229-1214-4e17-a80d-c819f88013e8"},
            geometry=shapely.geometry.Point(10, 10),
        ),
    ]
    fires = [
        peri_scribe.models.Fire(
            name="River",
            status=tests.helpers.factories.peri_scribe.models.ACTIVE,
            identifier="67e0a229-1214-4e17-a80d-c819f88013e8",
        ),
    ]
    assert [
        event["event"]
        for event in tests.helpers.peri_scribe.fires.grouping.warning_events(
            records,
            fires,
        )
    ] == ["Fire records span distant locations"]


def test_warn_for_inconsistent_fires_logs_temporal_outlier() -> None:
    location = shapely.geometry.Point(0, 0)
    records = [
        tests.helpers.factories.peri_scribe.models.fire_record(
            "RIVER",
            tests.helpers.factories.peri_scribe.models.ACTIVE,
            geometry=location,
            observed_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
        ),
        tests.helpers.factories.peri_scribe.models.fire_record(
            "River",
            tests.helpers.factories.peri_scribe.models.ACTIVE,
            identifiers={"67e0a229-1214-4e17-a80d-c819f88013e8"},
            geometry=location,
            observed_at=datetime.datetime(2026, 6, 1, tzinfo=datetime.UTC),
        ),
    ]
    fires = [
        peri_scribe.models.Fire(
            name="River",
            status=tests.helpers.factories.peri_scribe.models.ACTIVE,
            identifier="67e0a229-1214-4e17-a80d-c819f88013e8",
        ),
    ]
    assert [
        event["event"]
        for event in tests.helpers.peri_scribe.fires.grouping.warning_events(
            records,
            fires,
        )
    ] == ["Fire records span distant times"]


def test_warn_for_inconsistent_fires_ignores_duplicate_geometry_singleton() -> None:
    records = [
        tests.helpers.factories.peri_scribe.models.fire_record(
            "RIVER",
            tests.helpers.factories.peri_scribe.models.ACTIVE,
            geometry=shapely.geometry.Point(0, 0),
        ),
        tests.helpers.factories.peri_scribe.models.fire_record(
            "RIVER",
            tests.helpers.factories.peri_scribe.models.INACTIVE,
            geometry=shapely.geometry.Point(0, 0),
        ),
        tests.helpers.factories.peri_scribe.models.fire_record(
            "RIVER",
            tests.helpers.factories.peri_scribe.models.INACTIVE,
            identifiers={"67e0a229-1214-4e17-a80d-c819f88013e8"},
            geometry=shapely.geometry.Point(0.1, 0.1),
        ),
    ]
    fires = [
        peri_scribe.models.Fire(
            name="RIVER",
            status=tests.helpers.factories.peri_scribe.models.ACTIVE,
            identifier="67e0a229-1214-4e17-a80d-c819f88013e8",
        ),
    ]
    with structlog.testing.capture_logs() as captured:
        peri_scribe.fires.grouping.warn_for_inconsistent_fires(
            records,
            [[0, 1, 2]],
            fires,
        )
    assert captured == []


def test_warn_for_inconsistent_fires_logs_singleton_outlier_among_duplicates() -> None:
    records = [
        tests.helpers.factories.peri_scribe.models.fire_record(
            "RIVER",
            tests.helpers.factories.peri_scribe.models.ACTIVE,
            geometry=shapely.geometry.Point(0, 0),
        ),
        tests.helpers.factories.peri_scribe.models.fire_record(
            "RIVER",
            tests.helpers.factories.peri_scribe.models.INACTIVE,
            geometry=shapely.geometry.Point(0, 0),
        ),
        tests.helpers.factories.peri_scribe.models.fire_record(
            "RIVER",
            tests.helpers.factories.peri_scribe.models.INACTIVE,
            identifiers={"67e0a229-1214-4e17-a80d-c819f88013e8"},
            geometry=shapely.geometry.Point(10, 10),
        ),
    ]
    fires = [
        peri_scribe.models.Fire(
            name="RIVER",
            status=tests.helpers.factories.peri_scribe.models.ACTIVE,
            identifier="67e0a229-1214-4e17-a80d-c819f88013e8",
        ),
    ]
    with structlog.testing.capture_logs() as captured:
        peri_scribe.fires.grouping.warn_for_inconsistent_fires(
            records,
            [[0, 1, 2]],
            fires,
        )
    assert [event["event"] for event in captured] == [
        "Fire records span distant locations",
    ]


def test_group_fire_record_indices_merges_identical_geometry_records() -> None:
    location = shapely.geometry.Point(0, 0)
    records = [
        tests.helpers.factories.peri_scribe.models.fire_record(
            "RIVER",
            tests.helpers.factories.peri_scribe.models.ACTIVE,
            identifiers={"a"},
            geometry=location,
        ),
        tests.helpers.factories.peri_scribe.models.fire_record(
            "RIVER",
            tests.helpers.factories.peri_scribe.models.ACTIVE,
            identifiers={"b"},
            geometry=location,
        ),
        tests.helpers.factories.peri_scribe.models.fire_record(
            "RIVER",
            tests.helpers.factories.peri_scribe.models.ACTIVE,
            identifiers={"c"},
            geometry=location,
        ),
        tests.helpers.factories.peri_scribe.models.fire_record(
            "RIVER",
            tests.helpers.factories.peri_scribe.models.ACTIVE,
            identifiers={"d"},
            geometry=shapely.geometry.Point(50, 50),
        ),
    ]
    groups = peri_scribe.fires.grouping.group_fire_record_indices(records)
    assert groups == [[0, 1, 2], [3]]


def test_group_fire_record_indices_unions_distinct_geometry_classes() -> None:
    records = [
        tests.helpers.factories.peri_scribe.models.fire_record(
            "RIVER",
            tests.helpers.factories.peri_scribe.models.ACTIVE,
            identifiers={"a"},
            geometry=shapely.geometry.Point(0, 0),
        ),
        tests.helpers.factories.peri_scribe.models.fire_record(
            "RIVER",
            tests.helpers.factories.peri_scribe.models.ACTIVE,
            identifiers={"b"},
            geometry=shapely.geometry.Point(0, 0),
        ),
        tests.helpers.factories.peri_scribe.models.fire_record(
            "RIVER",
            tests.helpers.factories.peri_scribe.models.ACTIVE,
            identifiers={"c"},
            geometry=shapely.geometry.Point(0.01, 0.01),
        ),
    ]
    groups = peri_scribe.fires.grouping.group_fire_record_indices(records)
    assert groups == [[0, 1, 2]]
