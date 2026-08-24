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
