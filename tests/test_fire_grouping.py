"""Tests for peri_scribe.fire_grouping."""

from __future__ import annotations

import datetime
import typing

import shapely.geometry
import structlog

import peri_scribe.fire_grouping
import peri_scribe.models
from tests.factories import ACTIVE, INACTIVE, fire_record


def warning_events(
    records: list[peri_scribe.models.FireRecord],
    fires: list[peri_scribe.models.Fire],
) -> list[typing.MutableMapping[str, object]]:
    """Return events logged while warning about inconsistent *records*.

    Args:
        records: The grouped fire records.
        fires: The fires built from the groups.

    Returns:
        The logged events.
    """
    groups = [[0, 1]]
    with structlog.testing.capture_logs() as captured:
        peri_scribe.fire_grouping.warn_for_inconsistent_fires(records, groups, fires)
    return captured


def test_group_fire_records_preserves_first_encountered_order() -> None:
    records = [
        fire_record("A", ACTIVE, identifiers={"id-a"}),
        fire_record("B", ACTIVE, identifiers={"id-b"}),
        fire_record("A", ACTIVE, identifiers={"id-a"}),
    ]
    groups = peri_scribe.fire_grouping.group_fire_records(records)
    assert [group[0].name for group in groups] == ["A", "B"]


def test_group_fire_records_merges_names_differing_only_in_whitespace() -> None:
    location = shapely.geometry.Point(0, 0)
    records = [
        fire_record("PARK FIRE", ACTIVE, geometry=location),
        fire_record("  park   fire ", INACTIVE, geometry=location),
    ]
    groups = peri_scribe.fire_grouping.group_fire_records(records)
    assert groups == [records]


def test_most_common_fire_prefers_unique_fire_identifier_over_guid() -> None:
    unique_id = "2026-nvccd-030683"
    guid = "286b7f1d-8945-4a5d-9d81-5235c18af1fe"
    occurrences = [
        fire_record("Bug", ACTIVE, identifiers={guid}),
        fire_record("Bug", ACTIVE, identifiers={unique_id, guid}),
    ]
    assert peri_scribe.fire_grouping.most_common_fire(occurrences) == (
        peri_scribe.models.Fire(
            name="Bug",
            status=ACTIVE,
            identifier=unique_id,
            aliases=frozenset({unique_id, guid}),
        )
    )


def test_most_common_fire_uses_guid_without_unique_fire_identifier() -> None:
    guid = "286b7f1d-8945-4a5d-9d81-5235c18af1fe"
    occurrences = [fire_record("Bug", ACTIVE, identifiers={guid})]
    assert peri_scribe.fire_grouping.most_common_fire(occurrences) == (
        peri_scribe.models.Fire(
            name="Bug",
            status=ACTIVE,
            identifier=guid,
            aliases=frozenset({guid}),
        )
    )


def test_is_mixed_case() -> None:
    assert peri_scribe.fire_grouping.is_mixed_case("Park Fire")
    assert not peri_scribe.fire_grouping.is_mixed_case("PARK FIRE")
    assert not peri_scribe.fire_grouping.is_mixed_case("park fire")
    assert not peri_scribe.fire_grouping.is_mixed_case("3-1")


def test_geometries_are_compatible() -> None:
    point = shapely.geometry.Point(0, 0)
    assert not peri_scribe.fire_grouping.geometries_are_compatible(None, point)
    assert not peri_scribe.fire_grouping.geometries_are_compatible(
        shapely.geometry.Point(),
        point,
    )
    assert peri_scribe.fire_grouping.geometries_are_compatible(point, point)
    assert peri_scribe.fire_grouping.geometries_are_compatible(
        point,
        shapely.geometry.Point(0.01, 0),
    )
    assert not peri_scribe.fire_grouping.geometries_are_compatible(
        point,
        shapely.geometry.Point(1, 1),
    )


def test_group_fire_records_merges_through_intermediate_locations() -> None:
    # Each adjacent pair is within the proximity tolerance, so the chain of records is
    # one fire even though the ends are farther apart than the tolerance.
    records = [
        fire_record("RIVER", ACTIVE, geometry=shapely.geometry.Point(0, 0)),
        fire_record("RIVER", ACTIVE, geometry=shapely.geometry.Point(0.04, 0)),
        fire_record("RIVER", ACTIVE, geometry=shapely.geometry.Point(0.08, 0)),
    ]
    groups = peri_scribe.fire_grouping.group_fire_records(records)
    assert groups == [records]


def test_group_fire_records_does_not_merge_named_records_without_geometry() -> None:
    # Records without a geometry cannot be spatially compatible, so sharing only a
    # name is not enough to merge them.
    records = [
        fire_record("RIVER", ACTIVE),
        fire_record("RIVER", INACTIVE),
    ]
    groups = peri_scribe.fire_grouping.group_fire_records(records)
    assert groups == [[records[0]], [records[1]]]


def test_group_fire_records_keeps_many_same_named_records_far_apart_separate() -> None:
    # A name shared by many distant fires stays separate for each region; the spatial
    # index must not merge records whose geometries are not actually close.
    records = [
        fire_record(
            "CANYON",
            ACTIVE,
            geometry=shapely.geometry.Point(index, 0),
        )
        for index in range(200)
    ]
    groups = peri_scribe.fire_grouping.group_fire_records(records)
    assert groups == [[record] for record in records]


def test_warn_for_inconsistent_fires_ignores_group_without_geometries() -> None:
    records = [
        fire_record("RIVER", ACTIVE),
        fire_record("RIVER", INACTIVE),
    ]
    fires = [
        peri_scribe.models.Fire(
            name="RIVER",
            status=ACTIVE,
        ),
    ]
    assert warning_events(records, fires) == []


def test_warn_for_inconsistent_fires_logs_outlier_for_record_without_geometry() -> None:
    records = [
        fire_record("RIVER", ACTIVE, geometry=shapely.geometry.Point(0, 0)),
        fire_record("RIVER", INACTIVE),
    ]
    fires = [
        peri_scribe.models.Fire(
            name="RIVER",
            status=ACTIVE,
        ),
    ]
    assert [event["event"] for event in warning_events(records, fires)] == [
        "Fire records span distant locations",
    ]


def test_warn_for_inconsistent_fires_logs_outlier_when_other_geometries_empty() -> None:
    records = [
        fire_record(
            "RIVER",
            ACTIVE,
            geometry=shapely.geometry.Point(),
        ),
        fire_record(
            "RIVER",
            INACTIVE,
            geometry=shapely.geometry.Point(0, 0),
        ),
    ]
    fires = [
        peri_scribe.models.Fire(
            name="RIVER",
            status=ACTIVE,
        ),
    ]
    assert [event["event"] for event in warning_events(records, fires)] == [
        "Fire records span distant locations",
    ]


def test_warn_for_inconsistent_fires_logs_spatial_outlier() -> None:
    records = [
        fire_record("RIVER", ACTIVE, geometry=shapely.geometry.Point(0, 0)),
        fire_record(
            "River",
            ACTIVE,
            identifiers={"67e0a229-1214-4e17-a80d-c819f88013e8"},
            geometry=shapely.geometry.Point(10, 10),
        ),
    ]
    fires = [
        peri_scribe.models.Fire(
            name="River",
            status=ACTIVE,
            identifier="67e0a229-1214-4e17-a80d-c819f88013e8",
        ),
    ]
    assert [event["event"] for event in warning_events(records, fires)] == [
        "Fire records span distant locations",
    ]


def test_warn_for_inconsistent_fires_logs_temporal_outlier() -> None:
    location = shapely.geometry.Point(0, 0)
    records = [
        fire_record(
            "RIVER",
            ACTIVE,
            geometry=location,
            observed_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
        ),
        fire_record(
            "River",
            ACTIVE,
            identifiers={"67e0a229-1214-4e17-a80d-c819f88013e8"},
            geometry=location,
            observed_at=datetime.datetime(2026, 6, 1, tzinfo=datetime.UTC),
        ),
    ]
    fires = [
        peri_scribe.models.Fire(
            name="River",
            status=ACTIVE,
            identifier="67e0a229-1214-4e17-a80d-c819f88013e8",
        ),
    ]
    assert [event["event"] for event in warning_events(records, fires)] == [
        "Fire records span distant times",
    ]
