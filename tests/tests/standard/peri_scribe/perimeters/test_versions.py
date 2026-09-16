"""Tests for peri_scribe.perimeters.versions."""

from __future__ import annotations

import dataclasses
import datetime
import pathlib

import pytest
import shapely.geometry

import peri_scribe.models
import peri_scribe.perimeters.classification_data
import peri_scribe.perimeters.versions
import tests.helpers.factories.geometry
import tests.helpers.factories.peri_scribe.perimeters.classification_data
import tests.helpers.factories.peri_scribe.perimeters.versions
import tests.helpers.factories.time


def test_last_edit_time_from_returns_snapshot_time() -> None:
    path = pathlib.Path("000000,lastEdit=1786955463975.gpkg")
    expected = datetime.datetime.fromtimestamp(1786955463975 / 1_000.0, tz=datetime.UTC)
    assert peri_scribe.perimeters.versions.last_edit_time_from(path) == expected


def test_last_edit_time_from_returns_none_for_malformed_name() -> None:
    assert (
        peri_scribe.perimeters.versions.last_edit_time_from(
            pathlib.Path("000000,no-time.gpkg"),
        )
        is None
    )


def test_last_edit_time_from_returns_none_for_non_numeric_last_edit_timestamp() -> None:
    assert (
        peri_scribe.perimeters.versions.last_edit_time_from(
            pathlib.Path("000000,lastEdit=soon.gpkg"),
        )
        is None
    )


def test_last_edit_time_from_returns_none_without_comma() -> None:
    assert (
        peri_scribe.perimeters.versions.last_edit_time_from(
            pathlib.Path("snapshot.gpkg"),
        )
        is None
    )


def test_effective_time_prefers_observation_time() -> None:
    mapping_time = tests.helpers.factories.time.utc(2026, 8, 16, 0, 10)
    snapshot_time = tests.helpers.factories.time.utc(2026, 8, 17, 1, 42)
    observed = tests.helpers.factories.peri_scribe.perimeters.versions.observation(
        observation_time=mapping_time,
        snapshot_time=snapshot_time,
        attributes={
            "poly_DateCurrent": tests.helpers.factories.time.utc(2026, 8, 15, 22),
        },
    )
    assert peri_scribe.perimeters.versions.effective_time(observed) == mapping_time


def test_effective_time_prefers_as_of_date_over_capture_date() -> None:
    # The WFIGS perimeter feed reads poly_DateCurrent (the as-of date) as its
    # observation column; the capture date (poly_PolygonDateTime) describes the record's
    # original mapping and must not shadow the per-version as-of date.
    as_of = tests.helpers.factories.time.utc(2026, 8, 16, 22, 26)
    observed = tests.helpers.factories.peri_scribe.perimeters.versions.observation(
        observation_time=as_of,
        attributes={
            "poly_PolygonDateTime": tests.helpers.factories.time.utc(2026, 8, 10, 0),
        },
    )
    assert peri_scribe.perimeters.versions.effective_time(observed) == as_of


def test_effective_time_falls_back_to_snapshot_when_current_date_is_stale() -> None:
    # A dateless row uses the snapshot timestamp after the observation column is read.
    snapshot_time = tests.helpers.factories.time.utc(2026, 8, 17, 1, 42)
    observed = tests.helpers.factories.peri_scribe.perimeters.versions.observation(
        snapshot_time=snapshot_time,
        attributes={
            "poly_DateCurrent": tests.helpers.factories.time.utc(2026, 8, 16, 0, 10),
        },
    )
    assert peri_scribe.perimeters.versions.effective_time(observed) == snapshot_time


def test_effective_time_prefers_modified_time_over_stale_current_date() -> None:
    modified_time = tests.helpers.factories.time.utc(2026, 8, 17, 23, 18)
    observed = tests.helpers.factories.peri_scribe.perimeters.versions.observation(
        attributes={
            "poly_DateCurrent": tests.helpers.factories.time.utc(2026, 8, 16, 0, 10),
            "EditDate": modified_time,
        },
    )
    assert peri_scribe.perimeters.versions.effective_time(observed) == modified_time


def test_effective_time_falls_back_to_firis_modified_time() -> None:
    modified_time = tests.helpers.factories.time.utc(2026, 8, 17, 23, 18)
    snapshot_time = tests.helpers.factories.time.utc(2026, 8, 23, 3, 17)
    observed = tests.helpers.factories.peri_scribe.perimeters.versions.observation(
        snapshot_time=snapshot_time,
        attributes={"EditDate": modified_time},
    )
    assert peri_scribe.perimeters.versions.effective_time(observed) == modified_time


def test_effective_time_falls_back_to_wfigs_modified_time() -> None:
    modified_time = tests.helpers.factories.time.utc(2026, 8, 17, 23, 18)
    snapshot_time = tests.helpers.factories.time.utc(2026, 8, 23, 3, 17)
    observed = tests.helpers.factories.peri_scribe.perimeters.versions.observation(
        snapshot_time=snapshot_time,
        attributes={"attr_ModifiedOnDateTime_dt": modified_time},
    )
    assert peri_scribe.perimeters.versions.effective_time(observed) == modified_time


def test_effective_time_falls_back_to_snapshot_time() -> None:
    snapshot_time = tests.helpers.factories.time.utc(2026, 8, 17, 1, 42)
    observed = tests.helpers.factories.peri_scribe.perimeters.versions.observation(
        snapshot_time=snapshot_time,
    )
    assert peri_scribe.perimeters.versions.effective_time(observed) == snapshot_time


def test_perimeter_sort_key_orders_by_effective_time() -> None:
    earlier = tests.helpers.factories.peri_scribe.perimeters.versions.observation(
        observation_time=tests.helpers.factories.time.utc(2026, 8, 16, 0, 10),
        serial_number=9,
    )
    later = tests.helpers.factories.peri_scribe.perimeters.versions.observation(
        observation_time=tests.helpers.factories.time.utc(2026, 8, 16, 0, 11),
        serial_number=1,
    )
    assert peri_scribe.perimeters.versions.perimeter_sort_key(earlier) < (
        peri_scribe.perimeters.versions.perimeter_sort_key(later)
    )


def test_geometries_are_equal_compares_shapes() -> None:
    first = tests.helpers.factories.geometry.polygon((0, 0), (1, 0), (1, 1), (0, 0))
    second = tests.helpers.factories.geometry.polygon((0, 0), (1, 0), (1, 1), (0, 0))
    different = tests.helpers.factories.geometry.polygon((0, 0), (2, 0), (2, 1), (0, 0))
    assert peri_scribe.perimeters.versions.geometries_are_equal(first, second)
    assert not peri_scribe.perimeters.versions.geometries_are_equal(first, different)


def test_geometries_are_equal_treats_missing_geometries() -> None:
    assert peri_scribe.perimeters.versions.geometries_are_equal(None, None)
    assert not peri_scribe.perimeters.versions.geometries_are_equal(
        None,
        tests.helpers.factories.geometry.point(0, 0),
    )


def test_geometries_are_equal_treats_empty_geometries() -> None:
    empty = shapely.geometry.Polygon()
    assert peri_scribe.perimeters.versions.geometries_are_equal(empty, empty)
    assert not peri_scribe.perimeters.versions.geometries_are_equal(
        empty,
        tests.helpers.factories.geometry.point(0, 0),
    )


def test_collapse_identical_consecutive_perimeters_collapses_runs() -> None:
    geometry = tests.helpers.factories.geometry.polygon((0, 0), (1, 0), (1, 1), (0, 0))
    older = tests.helpers.factories.peri_scribe.perimeters.versions.observation(
        geometry=geometry,
        observation_time=tests.helpers.factories.time.utc(2026, 8, 16, 0, 10),
        attributes={"area_acres": 10},
    )
    newer = tests.helpers.factories.peri_scribe.perimeters.versions.observation(
        geometry=geometry,
        observation_time=tests.helpers.factories.time.utc(2026, 8, 16, 0, 10),
        serial_number=1,
        attributes={"area_acres": 11},
    )
    versions = (
        peri_scribe.perimeters.versions.collapse_identical_consecutive_perimeters([
            older,
            newer,
        ])
    )
    assert versions == [newer]


def test_collapse_identical_consecutive_perimeters_keeps_distinct_geometries() -> None:
    first = tests.helpers.factories.geometry.polygon((0, 0), (1, 0), (1, 1), (0, 0))
    second = tests.helpers.factories.geometry.polygon((0, 0), (2, 0), (2, 1), (0, 0))
    first_observation = (
        tests.helpers.factories.peri_scribe.perimeters.versions.observation(
            geometry=first,
            observation_time=tests.helpers.factories.time.utc(2026, 8, 16, 0, 10),
        )
    )
    second_observation = (
        tests.helpers.factories.peri_scribe.perimeters.versions.observation(
            geometry=second,
            observation_time=tests.helpers.factories.time.utc(2026, 8, 16, 1, 10),
        )
    )
    versions = (
        peri_scribe.perimeters.versions.collapse_identical_consecutive_perimeters([
            first_observation,
            second_observation,
        ])
    )
    assert versions == [first_observation, second_observation]


def test_observations_are_contemporaneous_within_tolerance() -> None:
    left = tests.helpers.factories.peri_scribe.perimeters.versions.observation(
        observation_time=tests.helpers.factories.time.utc(2026, 8, 16, 0, 10),
    )
    right = tests.helpers.factories.peri_scribe.perimeters.versions.observation(
        observation_time=tests.helpers.factories.time.utc(2026, 8, 16, 4, 10),
    )
    assert peri_scribe.perimeters.versions.observations_are_contemporaneous(left, right)


def test_observations_are_contemporaneous_beyond_tolerance() -> None:
    left = tests.helpers.factories.peri_scribe.perimeters.versions.observation(
        observation_time=tests.helpers.factories.time.utc(2026, 8, 16, 0, 10),
    )
    right = tests.helpers.factories.peri_scribe.perimeters.versions.observation(
        observation_time=tests.helpers.factories.time.utc(2026, 8, 16, 4, 11),
    )
    assert not peri_scribe.perimeters.versions.observations_are_contemporaneous(
        left,
        right,
    )


def test_observations_are_contemporaneous_with_missing_times() -> None:
    assert peri_scribe.perimeters.versions.observations_are_contemporaneous(
        tests.helpers.factories.peri_scribe.perimeters.versions.observation(),
        tests.helpers.factories.peri_scribe.perimeters.versions.observation(),
    )
    assert not peri_scribe.perimeters.versions.observations_are_contemporaneous(
        tests.helpers.factories.peri_scribe.perimeters.versions.observation(
            observation_time=tests.helpers.factories.time.utc(2026, 8, 16, 0, 10),
        ),
        tests.helpers.factories.peri_scribe.perimeters.versions.observation(),
    )


def test_preferred_perimeter_source_prefers_wfigs_outside_california() -> None:
    kinds = [
        peri_scribe.models.BorderClassification.CROSSES_CALIFORNIA_BORDER,
        peri_scribe.models.BorderClassification.OUTSIDE_CALIFORNIA_NEAR_BORDER,
        peri_scribe.models.BorderClassification.OUTSIDE_CALIFORNIA,
    ]
    for kind in kinds:
        assert (
            peri_scribe.perimeters.versions.preferred_perimeter_source(
                tests.helpers.factories.peri_scribe.perimeters.classification_data.classification(
                    kind,
                ),
            )
            is (
                tests.helpers.factories.peri_scribe.perimeters.classification_data
            ).WFIGS_PERIMETER
        )


def test_preferred_perimeter_source_prefers_firis_inside_california() -> None:
    kinds = [
        peri_scribe.models.BorderClassification.INSIDE_CALIFORNIA,
        peri_scribe.models.BorderClassification.INSIDE_CALIFORNIA_NEAR_BORDER,
    ]
    for kind in kinds:
        assert (
            peri_scribe.perimeters.versions.preferred_perimeter_source(
                tests.helpers.factories.peri_scribe.perimeters.classification_data.classification(
                    kind,
                ),
            )
            is (
                tests.helpers.factories.peri_scribe.perimeters.classification_data
            ).FIRIS_PERIMETER
        )


def test_preferred_perimeter_source_defaults_to_firis() -> None:
    assert (
        peri_scribe.perimeters.versions.preferred_perimeter_source(None)
        is (
            tests.helpers.factories.peri_scribe.perimeters.classification_data
        ).FIRIS_PERIMETER
    )


def test_preferred_pair_returns_preferred_first() -> None:
    firis = tests.helpers.factories.peri_scribe.perimeters.versions.observation(
        source_kind=tests.helpers.factories.peri_scribe.perimeters.classification_data.FIRIS_PERIMETER,
    )
    wfigs = tests.helpers.factories.peri_scribe.perimeters.versions.observation(
        source_kind=tests.helpers.factories.peri_scribe.perimeters.classification_data.WFIGS_PERIMETER,
    )
    assert peri_scribe.perimeters.versions.preferred_pair(
        firis,
        wfigs,
        tests.helpers.factories.peri_scribe.perimeters.classification_data.FIRIS_PERIMETER,
    ) == (firis, wfigs)
    assert peri_scribe.perimeters.versions.preferred_pair(
        firis,
        wfigs,
        tests.helpers.factories.peri_scribe.perimeters.classification_data.WFIGS_PERIMETER,
    ) == (wfigs, firis)


def test_merge_observations_merges_attributes_winner_first() -> None:
    winner = tests.helpers.factories.peri_scribe.perimeters.versions.observation(
        source_kind=tests.helpers.factories.peri_scribe.perimeters.classification_data.WFIGS_PERIMETER,
        geometry=tests.helpers.factories.geometry.polygon(
            (0, 0),
            (1, 0),
            (1, 1),
            (0, 0),
        ),
        attributes={"area_acres": 100, "source": "NIFC"},
    )
    loser = tests.helpers.factories.peri_scribe.perimeters.versions.observation(
        source_kind=tests.helpers.factories.peri_scribe.perimeters.classification_data.FIRIS_PERIMETER,
        geometry=tests.helpers.factories.geometry.polygon(
            (0, 0),
            (1, 0),
            (1, 1),
            (0, 0),
        ),
        attributes={"area_acres": 99, "cost": 500},
    )
    merged = peri_scribe.perimeters.versions.merge_observations(winner, loser)
    assert (
        merged.source_kind
        is (
            tests.helpers.factories.peri_scribe.perimeters.classification_data
        ).WFIGS_PERIMETER
    )
    assert merged.attributes == {"area_acres": 100, "source": "NIFC", "cost": 500}


def test_merge_identical_observations_merges_matching_geometry() -> None:
    geometry = tests.helpers.factories.geometry.polygon((0, 0), (1, 0), (1, 1), (0, 0))
    firis = tests.helpers.factories.peri_scribe.perimeters.versions.observation(
        source_kind=tests.helpers.factories.peri_scribe.perimeters.classification_data.FIRIS_PERIMETER,
        geometry=geometry,
        observation_time=tests.helpers.factories.time.utc(2026, 8, 16, 0, 10),
        attributes={"area_acres": 100},
    )
    wfigs = tests.helpers.factories.peri_scribe.perimeters.versions.observation(
        source_kind=tests.helpers.factories.peri_scribe.perimeters.classification_data.WFIGS_PERIMETER,
        geometry=geometry,
        observation_time=tests.helpers.factories.time.utc(2026, 8, 16, 0, 10),
        attributes={"poly_GISAcres": 100, "attr_EstimatedCostToDate": 500},
    )
    merged = peri_scribe.perimeters.versions.merge_identical_observations(
        [firis, wfigs],
        tests.helpers.factories.peri_scribe.perimeters.classification_data.WFIGS_PERIMETER,
    )
    assert [version.source_kind for version in merged] == [
        tests.helpers.factories.peri_scribe.perimeters.classification_data.WFIGS_PERIMETER,
    ]
    assert merged[0].attributes["area_acres"] == firis.attributes["area_acres"]
    assert (
        merged[0].attributes["attr_EstimatedCostToDate"]
        == wfigs.attributes["attr_EstimatedCostToDate"]
    )


def test_drop_losing_source_versions_drops_loser_in_window() -> None:
    firis = tests.helpers.factories.peri_scribe.perimeters.versions.observation(
        source_kind=tests.helpers.factories.peri_scribe.perimeters.classification_data.FIRIS_PERIMETER,
        observation_time=tests.helpers.factories.time.utc(2026, 7, 11, 21, 15),
    )
    wfigs = tests.helpers.factories.peri_scribe.perimeters.versions.observation(
        source_kind=tests.helpers.factories.peri_scribe.perimeters.classification_data.WFIGS_PERIMETER,
        observation_time=tests.helpers.factories.time.utc(2026, 7, 12, 0, 23),
    )
    kept = peri_scribe.perimeters.versions.drop_losing_source_versions(
        [firis, wfigs],
        tests.helpers.factories.peri_scribe.perimeters.classification_data.FIRIS_PERIMETER,
    )
    assert [item.geometry for item in kept] == [firis.geometry]
    assert kept[0].superseded_sources == (f"{wfigs.source_file}#{wfigs.object_id}",)


def test_reconcile_perimeter_versions_merges_identical_and_prefers_wfigs() -> None:
    early = tests.helpers.factories.geometry.polygon((0, 0), (1, 0), (1, 1), (0, 0))
    mid = tests.helpers.factories.geometry.polygon((0, 0), (2, 0), (2, 1), (0, 0))
    late = tests.helpers.factories.geometry.polygon((0, 0), (3, 0), (3, 1), (0, 0))
    firis_observations = [
        tests.helpers.factories.peri_scribe.perimeters.versions.observation(
            geometry=early,
            observation_time=tests.helpers.factories.time.utc(2026, 8, 9, 1),
            attributes={"area_acres": 100},
        ),
        tests.helpers.factories.peri_scribe.perimeters.versions.observation(
            geometry=mid,
            observation_time=tests.helpers.factories.time.utc(2026, 8, 16, 0, 10),
            attributes={"area_acres": 200},
        ),
        tests.helpers.factories.peri_scribe.perimeters.versions.observation(
            geometry=late,
            observation_time=tests.helpers.factories.time.utc(2026, 8, 18, 2, 14),
            attributes={"area_acres": 300},
        ),
    ]
    wfigs_observations = [
        tests.helpers.factories.peri_scribe.perimeters.versions.observation(
            source_kind=tests.helpers.factories.peri_scribe.perimeters.classification_data.WFIGS_PERIMETER,
            geometry=mid,
            observation_time=tests.helpers.factories.time.utc(2026, 8, 16, 0, 10),
            attributes={"poly_GISAcres": 200},
        ),
        tests.helpers.factories.peri_scribe.perimeters.versions.observation(
            source_kind=tests.helpers.factories.peri_scribe.perimeters.classification_data.WFIGS_PERIMETER,
            geometry=late,
            observation_time=tests.helpers.factories.time.utc(2026, 8, 18, 2, 14),
            attributes={"poly_GISAcres": 300},
        ),
    ]
    versions = peri_scribe.perimeters.versions.reconcile_perimeter_versions(
        firis_observations,
        wfigs_observations,
        tests.helpers.factories.peri_scribe.perimeters.classification_data.classification(
            peri_scribe.models.BorderClassification.CROSSES_CALIFORNIA_BORDER,
        ),
    )
    assert [version.source_kind for version in versions] == [
        tests.helpers.factories.peri_scribe.perimeters.classification_data.FIRIS_PERIMETER,
        tests.helpers.factories.peri_scribe.perimeters.classification_data.WFIGS_PERIMETER,
        tests.helpers.factories.peri_scribe.perimeters.classification_data.WFIGS_PERIMETER,
    ]


def test_reconcile_perimeter_versions_prefers_firis_for_inside_near() -> None:
    first = tests.helpers.factories.geometry.polygon((0, 0), (1, 0), (1, 1), (0, 0))
    second = tests.helpers.factories.geometry.polygon((0, 0), (2, 0), (2, 1), (0, 0))
    wfigs_geometry = tests.helpers.factories.geometry.polygon(
        (0, 0),
        (3, 0),
        (3, 1),
        (0, 0),
    )
    firis_observations = [
        tests.helpers.factories.peri_scribe.perimeters.versions.observation(
            geometry=first,
            observation_time=tests.helpers.factories.time.utc(2026, 7, 11, 21, 15),
        ),
        tests.helpers.factories.peri_scribe.perimeters.versions.observation(
            geometry=second,
            observation_time=tests.helpers.factories.time.utc(2026, 7, 11, 21, 32),
        ),
    ]
    wfigs_observations = [
        tests.helpers.factories.peri_scribe.perimeters.versions.observation(
            source_kind=tests.helpers.factories.peri_scribe.perimeters.classification_data.WFIGS_PERIMETER,
            geometry=wfigs_geometry,
            observation_time=tests.helpers.factories.time.utc(2026, 7, 12, 0, 23),
        ),
    ]
    versions = peri_scribe.perimeters.versions.reconcile_perimeter_versions(
        firis_observations,
        wfigs_observations,
        tests.helpers.factories.peri_scribe.perimeters.classification_data.classification(
            peri_scribe.models.BorderClassification.INSIDE_CALIFORNIA_NEAR_BORDER,
        ),
    )
    assert [version.source_kind for version in versions] == [
        tests.helpers.factories.peri_scribe.perimeters.classification_data.FIRIS_PERIMETER,
        tests.helpers.factories.peri_scribe.perimeters.classification_data.FIRIS_PERIMETER,
    ]


def test_attributes_are_equal_compares_keys_and_values() -> None:
    assert peri_scribe.perimeters.versions.attributes_are_equal(
        {"a": 1, "b": 2},
        {"a": 1, "b": 2},
    )
    assert not peri_scribe.perimeters.versions.attributes_are_equal(
        {"a": 1},
        {"a": 1, "b": 2},
    )
    assert not peri_scribe.perimeters.versions.attributes_are_equal({"a": 1}, {"a": 2})


def test_point_versions_folds_geometry_move() -> None:
    first = tests.helpers.factories.peri_scribe.perimeters.versions.observation(
        source_kind=tests.helpers.factories.peri_scribe.perimeters.classification_data.WFIGS_LOCATION,
        geometry=tests.helpers.factories.geometry.point(0, 0),
        snapshot_time=tests.helpers.factories.time.utc(2026, 8, 17, 1),
        attributes={"IncidentSize": 100},
    )
    moved = tests.helpers.factories.peri_scribe.perimeters.versions.observation(
        source_kind=tests.helpers.factories.peri_scribe.perimeters.classification_data.WFIGS_LOCATION,
        geometry=tests.helpers.factories.geometry.point(1, 1),
        snapshot_time=tests.helpers.factories.time.utc(2026, 8, 17, 2),
        serial_number=1,
        attributes={"IncidentSize": 100},
    )
    versions = peri_scribe.perimeters.versions.point_versions([first, moved])
    assert [version.geometry for version in versions] == [
        tests.helpers.factories.geometry.point(1, 1),
    ]
    assert versions[0].snapshot_time == moved.snapshot_time


def test_point_versions_creates_version_on_attribute_change() -> None:
    first = tests.helpers.factories.peri_scribe.perimeters.versions.observation(
        source_kind=tests.helpers.factories.peri_scribe.perimeters.classification_data.WFIGS_LOCATION,
        geometry=tests.helpers.factories.geometry.point(0, 0),
        attributes={"IncidentSize": 100},
    )
    second = tests.helpers.factories.peri_scribe.perimeters.versions.observation(
        source_kind=tests.helpers.factories.peri_scribe.perimeters.classification_data.WFIGS_LOCATION,
        geometry=tests.helpers.factories.geometry.point(0, 0),
        serial_number=1,
        attributes={"IncidentSize": 200},
    )
    versions = peri_scribe.perimeters.versions.point_versions([first, second])
    assert versions == [first, second]


def test_collapse_mapping_revisions_keeps_latest_publication_with_provenance(
    revision_observations: list[peri_scribe.perimeters.versions.SourceObservation],
) -> None:
    result = peri_scribe.perimeters.versions.collapse_mapping_revisions(
        revision_observations,
    )
    assert [row.serial_number for row in result] == [25]
    assert result[0].superseded_sources == ("24.gpkg#1",)


@pytest.mark.parametrize(
    "change",
    [
        "time",
        "source",
        "type",
        "missing_type",
        "geometry",
        "missing_geometry",
        "empty_geometry",
        "invalid_geometry",
        "undated",
    ],
)
def test_revision_pair_preserves_distinct_or_unverifiable_observations(
    revision_observations: list[peri_scribe.perimeters.versions.SourceObservation],
    change: str,
) -> None:
    first, second = revision_observations
    changes = {
        "time": {"observation_time": tests.helpers.factories.time.utc(2026, 9, 7, 22)},
        "source": {"source_kind": peri_scribe.perimeters.versions.WFIGS_PERIMETER},
        "type": {
            "attributes": {"source": "CAL FIRE INTEL FLIGHT DATA", "type": "Other"},
        },
        "missing_type": {"attributes": {}},
        "geometry": {"geometry": tests.helpers.factories.geometry.square(3)},
        "missing_geometry": {"geometry": None},
        "empty_geometry": {"geometry": shapely.Polygon()},
        "invalid_geometry": {
            "geometry": shapely.Polygon([(0, 0), (1, 1), (0, 1), (1, 0), (0, 0)]),
        },
        "undated": {"observation_time": None},
    }
    second = dataclasses.replace(second, **changes[change])
    assert not peri_scribe.perimeters.versions.revision_pair(first, second)


def test_collapse_mapping_revisions_does_not_chain_beyond_window(
    revision_observations: list[peri_scribe.perimeters.versions.SourceObservation],
) -> None:
    first, second = revision_observations
    last = dataclasses.replace(
        second,
        observation_time=tests.helpers.factories.time.utc(2026, 9, 7, 20, 30),
        serial_number=30,
    )
    result = peri_scribe.perimeters.versions.collapse_mapping_revisions([
        first,
        second,
        last,
    ])
    assert [row.serial_number for row in result] == [25, 30]


def test_collapse_mapping_revisions_respects_late_published_correction(
    revision_observations: list[peri_scribe.perimeters.versions.SourceObservation],
) -> None:
    first, second = revision_observations
    first = dataclasses.replace(first, serial_number=30)
    result = peri_scribe.perimeters.versions.collapse_mapping_revisions([first, second])
    assert result[0].geometry == first.geometry
    assert result[0].superseded_sources == ("25.gpkg#1",)


def test_collapse_identical_consecutive_perimeters_preserves_first_mapping_time(
    revision_observations: list[peri_scribe.perimeters.versions.SourceObservation],
) -> None:
    first, second = revision_observations
    second = dataclasses.replace(second, geometry=first.geometry)
    result = peri_scribe.perimeters.versions.collapse_identical_consecutive_perimeters([
        first,
        second,
    ])
    assert result[0].observation_time == first.observation_time
    assert result[0].source_file == second.source_file


def test_collapse_identical_consecutive_perimeters_keeps_new_capture(
    revision_observations: list[peri_scribe.perimeters.versions.SourceObservation],
) -> None:
    first, second = revision_observations
    second = dataclasses.replace(
        second,
        geometry=first.geometry,
        attributes={"poly_PolygonDateTime": second.observation_time},
    )
    assert peri_scribe.perimeters.versions.collapse_identical_consecutive_perimeters([
        first,
        second,
    ]) == [first, second]


def test_new_capture_recognizes_separate_flight_record(
    revision_observations: list[peri_scribe.perimeters.versions.SourceObservation],
) -> None:
    first, second = revision_observations
    assert peri_scribe.perimeters.versions.new_capture(
        first,
        dataclasses.replace(second, object_id=2),
    )


@pytest.mark.parametrize(
    "preferred",
    [
        tests.helpers.factories.peri_scribe.perimeters.classification_data.FIRIS_PERIMETER,
        tests.helpers.factories.peri_scribe.perimeters.classification_data.WFIGS_PERIMETER,
    ],
)
def test_drop_losing_source_versions_compares_across_window_boundaries(
    preferred: peri_scribe.perimeters.classification_data.FireSourceKind,
) -> None:
    other = (
        tests.helpers.factories.peri_scribe.perimeters.classification_data.WFIGS_PERIMETER
        if preferred
        is (
            tests.helpers.factories.peri_scribe.perimeters.classification_data
        ).FIRIS_PERIMETER
        else (
            tests.helpers.factories.peri_scribe.perimeters.classification_data
        ).FIRIS_PERIMETER
    )
    preferred_hour = 3
    records = [
        tests.helpers.factories.peri_scribe.perimeters.versions.observation(
            source_kind=preferred if hour == preferred_hour else other,
            observation_time=tests.helpers.factories.time.utc(2026, 9, 1, hour),
            object_id=hour,
            source_file="mapping.gpkg",
        )
        for hour in [0, 3, 5, 8]
    ]
    result = peri_scribe.perimeters.versions.drop_losing_source_versions(
        records,
        preferred,
    )
    assert [item.object_id for item in result] == [3, 8]
    assert result[0].superseded_sources == ("mapping.gpkg#0", "mapping.gpkg#5")


def test_drop_losing_source_versions_preserves_undated_and_single_source_records() -> (
    None
):
    records = [
        tests.helpers.factories.peri_scribe.perimeters.versions.observation(
            source_kind=tests.helpers.factories.peri_scribe.perimeters.classification_data.WFIGS_PERIMETER,
        ),
    ]
    assert (
        peri_scribe.perimeters.versions.drop_losing_source_versions(
            records,
            tests.helpers.factories.peri_scribe.perimeters.classification_data.FIRIS_PERIMETER,
        )
        == records
    )
    assert (
        peri_scribe.perimeters.versions.drop_losing_source_versions(
            [],
            tests.helpers.factories.peri_scribe.perimeters.classification_data.FIRIS_PERIMETER,
        )
        == []
    )


def test_reconcile_perimeter_versions_rejects_delayed_older_survey_spike(
    delayed_mapping_pair: tuple[
        peri_scribe.perimeters.versions.SourceObservation,
        peri_scribe.perimeters.versions.SourceObservation,
    ],
) -> None:
    flight, delayed = delayed_mapping_pair
    result = peri_scribe.perimeters.versions.reconcile_perimeter_versions(
        [flight],
        [delayed],
        None,
    )
    assert [item.geometry for item in result] == [flight.geometry]
    assert result[0].superseded_sources == ("delayed.gpkg#2",)


@pytest.mark.parametrize(
    "capture",
    [
        None,
        "invalid",
        "2002-09-01T16:48:00",
        "2026-09-03T00:00:00",
        "2026-08-01T00:00:00",
    ],
)
def test_credible_capture_time_rejects_unreliable_dates(capture: str | None) -> None:
    observation = tests.helpers.factories.peri_scribe.perimeters.versions.observation(
        observation_time=tests.helpers.factories.time.utc(2026, 9, 2, 13, 25),
        attributes={"poly_PolygonDateTime": capture},
    )
    assert peri_scribe.perimeters.versions.credible_capture_time(observation) is None


@pytest.mark.parametrize(
    ("capture", "geometry", "superseded"),
    [
        (
            tests.helpers.factories.time.utc(2026, 9, 1, 21, 33),
            shapely.geometry.box(0, 0, 1, 1),
            True,
        ),
        (
            tests.helpers.factories.time.utc(2026, 9, 2, 6),
            shapely.geometry.box(0, 0, 1, 1),
            False,
        ),
        (
            tests.helpers.factories.time.utc(2026, 9, 1, 16, 48),
            shapely.geometry.box(0, 0, 2, 1),
            False,
        ),
    ],
)
def test_mapping_is_superseded_respects_new_surveys_and_changed_footprints(
    delayed_mapping_pair: tuple[
        peri_scribe.perimeters.versions.SourceObservation,
        peri_scribe.perimeters.versions.SourceObservation,
    ],
    capture: datetime.datetime,
    geometry: shapely.geometry.Polygon,
    *,
    superseded: bool,
) -> None:
    flight, delayed = delayed_mapping_pair
    observation = dataclasses.replace(
        delayed,
        geometry=geometry,
        attributes={"poly_PolygonDateTime": capture},
    )
    assert (
        peri_scribe.perimeters.versions.mapping_is_superseded(observation, flight)
        is superseded
    )


def test_mapping_is_superseded_requires_dated_preferred_observation(
    delayed_mapping_pair: tuple[
        peri_scribe.perimeters.versions.SourceObservation,
        peri_scribe.perimeters.versions.SourceObservation,
    ],
) -> None:
    flight, delayed = delayed_mapping_pair
    assert not peri_scribe.perimeters.versions.mapping_is_superseded(
        delayed,
        dataclasses.replace(flight, observation_time=None),
    )


def test_mapping_is_superseded_uses_preferred_survey_time(
    delayed_mapping_pair: tuple[
        peri_scribe.perimeters.versions.SourceObservation,
        peri_scribe.perimeters.versions.SourceObservation,
    ],
) -> None:
    flight, delayed = delayed_mapping_pair
    preferred = dataclasses.replace(
        flight,
        attributes={
            "poly_PolygonDateTime": tests.helpers.factories.time.utc(2026, 9, 1, 10),
        },
    )
    assert not peri_scribe.perimeters.versions.mapping_is_superseded(delayed, preferred)
