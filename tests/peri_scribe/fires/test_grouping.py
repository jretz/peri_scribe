"""Tests for peri_scribe.fires.grouping."""

from __future__ import annotations

import datetime

import hypothesis
import hypothesis.strategies
import shapely.geometry
import structlog

import peri_scribe.fires.grouping
import peri_scribe.models
import tests.factories
import tests.peri_scribe.fires.grouping_helpers


def test_most_common_fire_prefers_unique_fire_identifier_over_guid() -> None:
    unique_id = "2026-nvccd-030683"
    guid = "286b7f1d-8945-4a5d-9d81-5235c18af1fe"
    occurrences = [
        tests.factories.fire_record("Bug", tests.factories.ACTIVE, identifiers={guid}),
        tests.factories.fire_record(
            "Bug",
            tests.factories.ACTIVE,
            identifiers={unique_id, guid},
        ),
    ]
    assert peri_scribe.fires.grouping.most_common_fire(occurrences) == (
        peri_scribe.models.Fire(
            name="Bug",
            status=tests.factories.ACTIVE,
            identifier=unique_id,
            aliases=frozenset({unique_id, guid}),
        )
    )


def test_most_common_fire_uses_guid_without_unique_fire_identifier() -> None:
    guid = "286b7f1d-8945-4a5d-9d81-5235c18af1fe"
    occurrences = [
        tests.factories.fire_record("Bug", tests.factories.ACTIVE, identifiers={guid}),
    ]
    assert peri_scribe.fires.grouping.most_common_fire(occurrences) == (
        peri_scribe.models.Fire(
            name="Bug",
            status=tests.factories.ACTIVE,
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
        tests.factories.fire_record("RIVER", tests.factories.ACTIVE),
        tests.factories.fire_record("RIVER", tests.factories.INACTIVE),
    ]
    fires = [peri_scribe.models.Fire(name="RIVER", status=tests.factories.ACTIVE)]
    assert tests.peri_scribe.fires.grouping_helpers.warning_events(records, fires) == []


def test_warn_for_inconsistent_fires_logs_outlier_for_record_without_geometry() -> None:
    records = [
        tests.factories.fire_record(
            "RIVER",
            tests.factories.ACTIVE,
            geometry=shapely.geometry.Point(0, 0),
        ),
        tests.factories.fire_record("RIVER", tests.factories.INACTIVE),
    ]
    fires = [peri_scribe.models.Fire(name="RIVER", status=tests.factories.ACTIVE)]
    assert [
        event["event"]
        for event in tests.peri_scribe.fires.grouping_helpers.warning_events(
            records,
            fires,
        )
    ] == ["Fire records span distant locations"]


def test_warn_for_inconsistent_fires_logs_outlier_when_other_geometries_empty() -> None:
    records = [
        tests.factories.fire_record(
            "RIVER",
            tests.factories.ACTIVE,
            geometry=shapely.geometry.Point(),
        ),
        tests.factories.fire_record(
            "RIVER",
            tests.factories.INACTIVE,
            geometry=shapely.geometry.Point(0, 0),
        ),
    ]
    fires = [peri_scribe.models.Fire(name="RIVER", status=tests.factories.ACTIVE)]
    assert [
        event["event"]
        for event in tests.peri_scribe.fires.grouping_helpers.warning_events(
            records,
            fires,
        )
    ] == ["Fire records span distant locations"]


def test_warn_for_inconsistent_fires_logs_spatial_outlier() -> None:
    records = [
        tests.factories.fire_record(
            "RIVER",
            tests.factories.ACTIVE,
            geometry=shapely.geometry.Point(0, 0),
        ),
        tests.factories.fire_record(
            "River",
            tests.factories.ACTIVE,
            identifiers={"67e0a229-1214-4e17-a80d-c819f88013e8"},
            geometry=shapely.geometry.Point(10, 10),
        ),
    ]
    fires = [
        peri_scribe.models.Fire(
            name="River",
            status=tests.factories.ACTIVE,
            identifier="67e0a229-1214-4e17-a80d-c819f88013e8",
        ),
    ]
    assert [
        event["event"]
        for event in tests.peri_scribe.fires.grouping_helpers.warning_events(
            records,
            fires,
        )
    ] == ["Fire records span distant locations"]


def test_warn_for_inconsistent_fires_logs_temporal_outlier() -> None:
    location = shapely.geometry.Point(0, 0)
    records = [
        tests.factories.fire_record(
            "RIVER",
            tests.factories.ACTIVE,
            geometry=location,
            observed_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
        ),
        tests.factories.fire_record(
            "River",
            tests.factories.ACTIVE,
            identifiers={"67e0a229-1214-4e17-a80d-c819f88013e8"},
            geometry=location,
            observed_at=datetime.datetime(2026, 6, 1, tzinfo=datetime.UTC),
        ),
    ]
    fires = [
        peri_scribe.models.Fire(
            name="River",
            status=tests.factories.ACTIVE,
            identifier="67e0a229-1214-4e17-a80d-c819f88013e8",
        ),
    ]
    assert [
        event["event"]
        for event in tests.peri_scribe.fires.grouping_helpers.warning_events(
            records,
            fires,
        )
    ] == ["Fire records span distant times"]


def test_warn_for_inconsistent_fires_ignores_duplicate_geometry_singleton() -> None:
    records = [
        tests.factories.fire_record(
            "RIVER",
            tests.factories.ACTIVE,
            geometry=shapely.geometry.Point(0, 0),
        ),
        tests.factories.fire_record(
            "RIVER",
            tests.factories.INACTIVE,
            geometry=shapely.geometry.Point(0, 0),
        ),
        tests.factories.fire_record(
            "RIVER",
            tests.factories.INACTIVE,
            identifiers={"67e0a229-1214-4e17-a80d-c819f88013e8"},
            geometry=shapely.geometry.Point(0.1, 0.1),
        ),
    ]
    fires = [
        peri_scribe.models.Fire(
            name="RIVER",
            status=tests.factories.ACTIVE,
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
        tests.factories.fire_record(
            "RIVER",
            tests.factories.ACTIVE,
            geometry=shapely.geometry.Point(0, 0),
        ),
        tests.factories.fire_record(
            "RIVER",
            tests.factories.INACTIVE,
            geometry=shapely.geometry.Point(0, 0),
        ),
        tests.factories.fire_record(
            "RIVER",
            tests.factories.INACTIVE,
            identifiers={"67e0a229-1214-4e17-a80d-c819f88013e8"},
            geometry=shapely.geometry.Point(10, 10),
        ),
    ]
    fires = [
        peri_scribe.models.Fire(
            name="RIVER",
            status=tests.factories.ACTIVE,
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
        tests.factories.fire_record(
            "RIVER",
            tests.factories.ACTIVE,
            identifiers={"a"},
            geometry=location,
        ),
        tests.factories.fire_record(
            "RIVER",
            tests.factories.ACTIVE,
            identifiers={"b"},
            geometry=location,
        ),
        tests.factories.fire_record(
            "RIVER",
            tests.factories.ACTIVE,
            identifiers={"c"},
            geometry=location,
        ),
        tests.factories.fire_record(
            "RIVER",
            tests.factories.ACTIVE,
            identifiers={"d"},
            geometry=shapely.geometry.Point(50, 50),
        ),
    ]
    groups = peri_scribe.fires.grouping.group_fire_record_indices(records)
    assert groups == [[0, 1, 2], [3]]


def test_group_fire_record_indices_unions_distinct_geometry_classes() -> None:
    records = [
        tests.factories.fire_record(
            "RIVER",
            tests.factories.ACTIVE,
            identifiers={"a"},
            geometry=shapely.geometry.Point(0, 0),
        ),
        tests.factories.fire_record(
            "RIVER",
            tests.factories.ACTIVE,
            identifiers={"b"},
            geometry=shapely.geometry.Point(0, 0),
        ),
        tests.factories.fire_record(
            "RIVER",
            tests.factories.ACTIVE,
            identifiers={"c"},
            geometry=shapely.geometry.Point(0.01, 0.01),
        ),
    ]
    groups = peri_scribe.fires.grouping.group_fire_record_indices(records)
    assert groups == [[0, 1, 2]]


@hypothesis.given(records=tests.peri_scribe.fires.grouping_helpers.fire_records())
def test_group_fire_record_indices_matches_connected_components(
    records: list[peri_scribe.models.FireRecord],
) -> None:
    assert peri_scribe.fires.grouping.group_fire_record_indices(records) == (
        tests.peri_scribe.fires.grouping_helpers.reference_groups(records)
    )


@hypothesis.given(
    records=tests.peri_scribe.fires.grouping_helpers.fire_records(),
    data=hypothesis.strategies.data(),
)
def test_group_fire_record_indices_preserves_membership_under_permutation(
    records: list[peri_scribe.models.FireRecord],
    data: hypothesis.strategies.DataObject,
) -> None:
    permutation = data.draw(hypothesis.strategies.permutations(range(len(records))))
    original = peri_scribe.fires.grouping.group_fire_record_indices(records)
    reordered = peri_scribe.fires.grouping.group_fire_record_indices([
        records[index] for index in permutation
    ])
    assert {frozenset(group) for group in original} == {
        frozenset(permutation[index] for index in group) for group in reordered
    }


@hypothesis.given(
    geometries=hypothesis.strategies.lists(
        tests.peri_scribe.fires.grouping_helpers.local_geometries(),
        max_size=15,
    ),
)
def test_matched_within_outlier_tolerance_matches_exhaustive_comparisons(
    geometries: list[shapely.Geometry],
) -> None:
    tolerance = peri_scribe.fires.grouping.FIRE_OUTLIER_TOLERANCE.m_as("degrees")
    expected = {
        index
        for index, geometry in enumerate(geometries)
        if any(
            index != other_index and geometry.distance(other) <= tolerance
            for other_index, other in enumerate(geometries)
        )
    }
    assert (
        peri_scribe.fires.grouping.matched_within_outlier_tolerance(
            list(enumerate(geometries)),
        )
        == expected
    )
