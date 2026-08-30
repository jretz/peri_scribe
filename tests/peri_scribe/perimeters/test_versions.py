"""Tests for peri_scribe.perimeters.versions."""

from __future__ import annotations

import datetime
import pathlib

import numpy as np
import pytest
import shapely.geometry

import peri_scribe.models
import peri_scribe.perimeters.size_filtering
import peri_scribe.perimeters.versions
import tests.factories


def test_last_edit_time_from_returns_snapshot_time() -> None:
    path = pathlib.Path("000000,lastEdit=1786955463975.gpkg")
    expected = datetime.datetime.fromtimestamp(1786955463975 / 1000.0, tz=datetime.UTC)
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
    mapping_time = tests.factories.utc(2026, 8, 16, 0, 10)
    snapshot_time = tests.factories.utc(2026, 8, 17, 1, 42)
    observed = tests.factories.observation(
        observation_time=mapping_time,
        snapshot_time=snapshot_time,
        attributes={"poly_DateCurrent": tests.factories.utc(2026, 8, 15, 22, 0)},
    )
    assert peri_scribe.perimeters.versions.effective_time(observed) == mapping_time


def test_effective_time_prefers_as_of_date_over_capture_date() -> None:
    # The WFIGS perimeter feed reads poly_DateCurrent (the as-of date) as its
    # observation column; the capture date (poly_PolygonDateTime) describes the
    # record's original mapping and must not shadow the per-version as-of date.
    as_of = tests.factories.utc(2026, 8, 16, 22, 26)
    observed = tests.factories.observation(
        observation_time=as_of,
        attributes={"poly_PolygonDateTime": tests.factories.utc(2026, 8, 10, 0, 0)},
    )
    assert peri_scribe.perimeters.versions.effective_time(observed) == as_of


def test_effective_time_falls_back_to_snapshot_when_current_date_is_stale() -> None:
    # A poly_DateCurrent value left behind in the attributes is no longer consulted
    # once the observation column has read it; a dateless row falls to the snapshot.
    snapshot_time = tests.factories.utc(2026, 8, 17, 1, 42)
    observed = tests.factories.observation(
        snapshot_time=snapshot_time,
        attributes={"poly_DateCurrent": tests.factories.utc(2026, 8, 16, 0, 10)},
    )
    assert peri_scribe.perimeters.versions.effective_time(observed) == snapshot_time


def test_effective_time_prefers_modified_time_over_stale_current_date() -> None:
    modified_time = tests.factories.utc(2026, 8, 17, 23, 18)
    observed = tests.factories.observation(
        attributes={
            "poly_DateCurrent": tests.factories.utc(2026, 8, 16, 0, 10),
            "EditDate": modified_time,
        },
    )
    assert peri_scribe.perimeters.versions.effective_time(observed) == modified_time


def test_effective_time_falls_back_to_firis_modified_time() -> None:
    modified_time = tests.factories.utc(2026, 8, 17, 23, 18)
    snapshot_time = tests.factories.utc(2026, 8, 23, 3, 17)
    observed = tests.factories.observation(
        snapshot_time=snapshot_time,
        attributes={"EditDate": modified_time},
    )
    assert peri_scribe.perimeters.versions.effective_time(observed) == modified_time


def test_effective_time_falls_back_to_wfigs_modified_time() -> None:
    modified_time = tests.factories.utc(2026, 8, 17, 23, 18)
    snapshot_time = tests.factories.utc(2026, 8, 23, 3, 17)
    observed = tests.factories.observation(
        snapshot_time=snapshot_time,
        attributes={"attr_ModifiedOnDateTime_dt": modified_time},
    )
    assert peri_scribe.perimeters.versions.effective_time(observed) == modified_time


def test_effective_time_falls_back_to_snapshot_time() -> None:
    snapshot_time = tests.factories.utc(2026, 8, 17, 1, 42)
    observed = tests.factories.observation(snapshot_time=snapshot_time)
    assert peri_scribe.perimeters.versions.effective_time(observed) == snapshot_time


def test_perimeter_sort_key_orders_by_effective_time() -> None:
    earlier = tests.factories.observation(
        observation_time=tests.factories.utc(2026, 8, 16, 0, 10),
        serial_number=9,
    )
    later = tests.factories.observation(
        observation_time=tests.factories.utc(2026, 8, 16, 0, 11),
        serial_number=1,
    )
    assert peri_scribe.perimeters.versions.perimeter_sort_key(earlier) < (
        peri_scribe.perimeters.versions.perimeter_sort_key(later)
    )


def test_geometries_are_equal_compares_shapes() -> None:
    first = tests.factories.polygon((0, 0), (1, 0), (1, 1), (0, 0))
    second = tests.factories.polygon((0, 0), (1, 0), (1, 1), (0, 0))
    different = tests.factories.polygon((0, 0), (2, 0), (2, 1), (0, 0))
    assert peri_scribe.perimeters.versions.geometries_are_equal(first, second)
    assert not peri_scribe.perimeters.versions.geometries_are_equal(first, different)


def test_geometries_are_equal_treats_missing_geometries() -> None:
    assert peri_scribe.perimeters.versions.geometries_are_equal(None, None)
    assert not peri_scribe.perimeters.versions.geometries_are_equal(
        None,
        tests.factories.point(0, 0),
    )


def test_geometries_are_equal_treats_empty_geometries() -> None:
    empty = shapely.geometry.Polygon()
    assert peri_scribe.perimeters.versions.geometries_are_equal(empty, empty)
    assert not peri_scribe.perimeters.versions.geometries_are_equal(
        empty,
        tests.factories.point(0, 0),
    )


def test_collapse_identical_consecutive_perimeters_collapses_runs() -> None:
    geometry = tests.factories.polygon((0, 0), (1, 0), (1, 1), (0, 0))
    older = tests.factories.observation(
        geometry=geometry,
        observation_time=tests.factories.utc(2026, 8, 16, 0, 10),
        serial_number=0,
        attributes={"area_acres": 10},
    )
    newer = tests.factories.observation(
        geometry=geometry,
        observation_time=tests.factories.utc(2026, 8, 16, 0, 10),
        serial_number=1,
        attributes={"area_acres": 11},
    )
    versions = (
        peri_scribe.perimeters.versions.collapse_identical_consecutive_perimeters(
            [older, newer],
        )
    )
    assert versions == [newer]


def test_collapse_identical_consecutive_perimeters_keeps_distinct_geometries() -> None:
    first = tests.factories.polygon((0, 0), (1, 0), (1, 1), (0, 0))
    second = tests.factories.polygon((0, 0), (2, 0), (2, 1), (0, 0))
    first_observation = tests.factories.observation(
        geometry=first,
        observation_time=tests.factories.utc(2026, 8, 16, 0, 10),
    )
    second_observation = tests.factories.observation(
        geometry=second,
        observation_time=tests.factories.utc(2026, 8, 16, 1, 10),
    )
    versions = (
        peri_scribe.perimeters.versions.collapse_identical_consecutive_perimeters(
            [first_observation, second_observation],
        )
    )
    assert versions == [first_observation, second_observation]


def test_observations_are_contemporaneous_within_tolerance() -> None:
    left = tests.factories.observation(
        observation_time=tests.factories.utc(2026, 8, 16, 0, 10),
    )
    right = tests.factories.observation(
        observation_time=tests.factories.utc(2026, 8, 16, 4, 10),
    )
    assert peri_scribe.perimeters.versions.observations_are_contemporaneous(left, right)


def test_observations_are_contemporaneous_beyond_tolerance() -> None:
    left = tests.factories.observation(
        observation_time=tests.factories.utc(2026, 8, 16, 0, 10),
    )
    right = tests.factories.observation(
        observation_time=tests.factories.utc(2026, 8, 16, 4, 11),
    )
    assert not peri_scribe.perimeters.versions.observations_are_contemporaneous(
        left,
        right,
    )


def test_observations_are_contemporaneous_with_missing_times() -> None:
    assert peri_scribe.perimeters.versions.observations_are_contemporaneous(
        tests.factories.observation(),
        tests.factories.observation(),
    )
    assert not peri_scribe.perimeters.versions.observations_are_contemporaneous(
        tests.factories.observation(
            observation_time=tests.factories.utc(2026, 8, 16, 0, 10),
        ),
        tests.factories.observation(),
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
                tests.factories.classification(kind),
            )
            is tests.factories.WFIGS_PERIMETER
        )


def test_preferred_perimeter_source_prefers_firis_inside_california() -> None:
    kinds = [
        peri_scribe.models.BorderClassification.INSIDE_CALIFORNIA,
        peri_scribe.models.BorderClassification.INSIDE_CALIFORNIA_NEAR_BORDER,
    ]
    for kind in kinds:
        assert (
            peri_scribe.perimeters.versions.preferred_perimeter_source(
                tests.factories.classification(kind),
            )
            is tests.factories.FIRIS_PERIMETER
        )


def test_preferred_perimeter_source_defaults_to_firis() -> None:
    assert (
        peri_scribe.perimeters.versions.preferred_perimeter_source(None)
        is tests.factories.FIRIS_PERIMETER
    )


def test_preferred_pair_returns_preferred_first() -> None:
    firis = tests.factories.observation(source_kind=tests.factories.FIRIS_PERIMETER)
    wfigs = tests.factories.observation(source_kind=tests.factories.WFIGS_PERIMETER)
    assert peri_scribe.perimeters.versions.preferred_pair(
        firis,
        wfigs,
        tests.factories.FIRIS_PERIMETER,
    ) == (firis, wfigs)
    assert peri_scribe.perimeters.versions.preferred_pair(
        firis,
        wfigs,
        tests.factories.WFIGS_PERIMETER,
    ) == (wfigs, firis)


def test_merge_observations_merges_attributes_winner_first() -> None:
    winner = tests.factories.observation(
        source_kind=tests.factories.WFIGS_PERIMETER,
        geometry=tests.factories.polygon((0, 0), (1, 0), (1, 1), (0, 0)),
        attributes={"area_acres": 100, "source": "NIFC"},
    )
    loser = tests.factories.observation(
        source_kind=tests.factories.FIRIS_PERIMETER,
        geometry=tests.factories.polygon((0, 0), (1, 0), (1, 1), (0, 0)),
        attributes={"area_acres": 99, "cost": 500},
    )
    merged = peri_scribe.perimeters.versions.merge_observations(winner, loser)
    assert merged.source_kind is tests.factories.WFIGS_PERIMETER
    assert merged.attributes == {"area_acres": 100, "source": "NIFC", "cost": 500}


def test_merge_identical_observations_merges_matching_geometry() -> None:
    geometry = tests.factories.polygon((0, 0), (1, 0), (1, 1), (0, 0))
    firis = tests.factories.observation(
        source_kind=tests.factories.FIRIS_PERIMETER,
        geometry=geometry,
        observation_time=tests.factories.utc(2026, 8, 16, 0, 10),
        attributes={"area_acres": 100},
    )
    wfigs = tests.factories.observation(
        source_kind=tests.factories.WFIGS_PERIMETER,
        geometry=geometry,
        observation_time=tests.factories.utc(2026, 8, 16, 0, 10),
        attributes={"poly_GISAcres": 100, "attr_EstimatedCostToDate": 500},
    )
    merged = peri_scribe.perimeters.versions.merge_identical_observations(
        [firis, wfigs],
        tests.factories.WFIGS_PERIMETER,
    )
    assert [version.source_kind for version in merged] == [
        tests.factories.WFIGS_PERIMETER,
    ]
    assert merged[0].attributes["area_acres"] == firis.attributes["area_acres"]
    assert (
        merged[0].attributes["attr_EstimatedCostToDate"]
        == wfigs.attributes["attr_EstimatedCostToDate"]
    )


def test_keep_preferred_in_window_drops_loser_when_both_sources_present() -> None:
    firis = tests.factories.observation(source_kind=tests.factories.FIRIS_PERIMETER)
    wfigs = tests.factories.observation(source_kind=tests.factories.WFIGS_PERIMETER)
    kept = peri_scribe.perimeters.versions.keep_preferred_in_window(
        [firis, wfigs],
        tests.factories.WFIGS_PERIMETER,
    )
    assert kept == [wfigs]


def test_keep_preferred_in_window_keeps_single_source_window() -> None:
    firis = tests.factories.observation(source_kind=tests.factories.FIRIS_PERIMETER)
    kept = peri_scribe.perimeters.versions.keep_preferred_in_window(
        [firis],
        tests.factories.WFIGS_PERIMETER,
    )
    assert kept == [firis]


def test_drop_losing_source_versions_drops_loser_in_window() -> None:
    firis = tests.factories.observation(
        source_kind=tests.factories.FIRIS_PERIMETER,
        observation_time=tests.factories.utc(2026, 7, 11, 21, 15),
    )
    wfigs = tests.factories.observation(
        source_kind=tests.factories.WFIGS_PERIMETER,
        observation_time=tests.factories.utc(2026, 7, 12, 0, 23),
    )
    kept = peri_scribe.perimeters.versions.drop_losing_source_versions(
        [firis, wfigs],
        tests.factories.FIRIS_PERIMETER,
    )
    assert kept == [firis]


def test_reconcile_perimeter_versions_merges_identical_and_prefers_wfigs() -> None:
    early = tests.factories.polygon((0, 0), (1, 0), (1, 1), (0, 0))
    mid = tests.factories.polygon((0, 0), (2, 0), (2, 1), (0, 0))
    late = tests.factories.polygon((0, 0), (3, 0), (3, 1), (0, 0))
    firis_observations = [
        tests.factories.observation(
            geometry=early,
            observation_time=tests.factories.utc(2026, 8, 9, 1, 0),
            attributes={"area_acres": 100},
        ),
        tests.factories.observation(
            geometry=mid,
            observation_time=tests.factories.utc(2026, 8, 16, 0, 10),
            attributes={"area_acres": 200},
        ),
        tests.factories.observation(
            geometry=late,
            observation_time=tests.factories.utc(2026, 8, 18, 2, 14),
            attributes={"area_acres": 300},
        ),
    ]
    wfigs_observations = [
        tests.factories.observation(
            source_kind=tests.factories.WFIGS_PERIMETER,
            geometry=mid,
            observation_time=tests.factories.utc(2026, 8, 16, 0, 10),
            attributes={"poly_GISAcres": 200},
        ),
        tests.factories.observation(
            source_kind=tests.factories.WFIGS_PERIMETER,
            geometry=late,
            observation_time=tests.factories.utc(2026, 8, 18, 2, 14),
            attributes={"poly_GISAcres": 300},
        ),
    ]
    versions = peri_scribe.perimeters.versions.reconcile_perimeter_versions(
        firis_observations,
        wfigs_observations,
        tests.factories.classification(
            peri_scribe.models.BorderClassification.CROSSES_CALIFORNIA_BORDER,
        ),
    )
    assert [version.source_kind for version in versions] == [
        tests.factories.FIRIS_PERIMETER,
        tests.factories.WFIGS_PERIMETER,
        tests.factories.WFIGS_PERIMETER,
    ]


def test_reconcile_perimeter_versions_prefers_firis_for_inside_near() -> None:
    first = tests.factories.polygon((0, 0), (1, 0), (1, 1), (0, 0))
    second = tests.factories.polygon((0, 0), (2, 0), (2, 1), (0, 0))
    wfigs_geometry = tests.factories.polygon((0, 0), (3, 0), (3, 1), (0, 0))
    firis_observations = [
        tests.factories.observation(
            geometry=first,
            observation_time=tests.factories.utc(2026, 7, 11, 21, 15),
        ),
        tests.factories.observation(
            geometry=second,
            observation_time=tests.factories.utc(2026, 7, 11, 21, 32),
        ),
    ]
    wfigs_observations = [
        tests.factories.observation(
            source_kind=tests.factories.WFIGS_PERIMETER,
            geometry=wfigs_geometry,
            observation_time=tests.factories.utc(2026, 7, 12, 0, 23),
        ),
    ]
    versions = peri_scribe.perimeters.versions.reconcile_perimeter_versions(
        firis_observations,
        wfigs_observations,
        tests.factories.classification(
            peri_scribe.models.BorderClassification.INSIDE_CALIFORNIA_NEAR_BORDER,
        ),
    )
    assert [version.source_kind for version in versions] == [
        tests.factories.FIRIS_PERIMETER,
        tests.factories.FIRIS_PERIMETER,
    ]


def test_geometry_area_in_acres_returns_area_for_polygon() -> None:
    geometry = tests.factories.polygon((0, 0), (1, 0), (1, 1), (0, 0))
    area = peri_scribe.perimeters.size_filtering.geometry_area_in_acres(geometry)
    assert area is not None
    assert area > 0


def test_geometry_area_in_acres_returns_none_without_geometry() -> None:
    assert peri_scribe.perimeters.size_filtering.geometry_area_in_acres(None) is None
    assert (
        peri_scribe.perimeters.size_filtering.geometry_area_in_acres(
            shapely.geometry.Polygon(),
        )
        is None
    )


def test_computed_area_in_acres_returns_first_positive_value() -> None:
    area = peri_scribe.perimeters.size_filtering.computed_area_in_acres(
        {"poly_Acres_AutoCalc": 123, "poly_GISAcres": 456, "area_acres": 789},
    )
    assert area == pytest.approx(123)


def test_computed_area_in_acres_skips_missing_and_nonpositive() -> None:
    area = peri_scribe.perimeters.size_filtering.computed_area_in_acres(
        {"poly_Acres_AutoCalc": 0, "poly_GISAcres": None, "area_acres": 456},
    )
    assert area == pytest.approx(456)


def test_computed_area_in_acres_returns_none_without_sizes() -> None:
    assert peri_scribe.perimeters.size_filtering.computed_area_in_acres({}) is None


def test_incident_size_in_acres_returns_first_positive_value() -> None:
    size = peri_scribe.perimeters.size_filtering.incident_size_in_acres(
        {"attr_IncidentSize": 100, "attr_FinalAcres": 200},
    )
    assert size == pytest.approx(100)


def test_incident_size_in_acres_skips_missing_and_nonpositive() -> None:
    size = peri_scribe.perimeters.size_filtering.incident_size_in_acres(
        {"attr_IncidentSize": np.nan, "attr_FinalAcres": 200},
    )
    assert size == pytest.approx(200)


def test_incident_size_in_acres_returns_none_without_sizes() -> None:
    assert peri_scribe.perimeters.size_filtering.incident_size_in_acres({}) is None


def test_perimeter_is_implausibly_small_flags_collapsed_geometry() -> None:
    tiny = tests.factories.polygon((0, 0), (0.0001, 0), (0.0001, 0.0001), (0, 0))
    version = tests.factories.observation(
        geometry=tiny,
        attributes={"area_acres": 1000},
    )
    assert peri_scribe.perimeters.size_filtering.perimeter_is_implausibly_small(version)


def test_perimeter_is_implausibly_small_flags_small_incident_size() -> None:
    tiny = tests.factories.polygon((0, 0), (0.0001, 0), (0.0001, 0.0001), (0, 0))
    version = tests.factories.observation(
        geometry=tiny,
        attributes={"attr_IncidentSize": 100_000},
    )
    assert peri_scribe.perimeters.size_filtering.perimeter_is_implausibly_small(version)


def test_perimeter_is_implausibly_small_keeps_matching_geometry() -> None:
    large = tests.factories.polygon((0, 0), (1, 0), (1, 1), (0, 0))
    version = tests.factories.observation(
        geometry=large,
        attributes={"area_acres": 3_000_000},
    )
    assert not peri_scribe.perimeters.size_filtering.perimeter_is_implausibly_small(
        version,
    )


def test_perimeter_is_implausibly_small_keeps_incident_running_ahead() -> None:
    medium = tests.factories.polygon((0, 0), (0.01, 0), (0.01, 0.01), (0, 0))
    version = tests.factories.observation(
        geometry=medium,
        attributes={"attr_IncidentSize": 4000},
    )
    assert not peri_scribe.perimeters.size_filtering.perimeter_is_implausibly_small(
        version,
    )


def test_perimeter_is_implausibly_small_keeps_without_reported_size() -> None:
    tiny = tests.factories.polygon((0, 0), (0.0001, 0), (0.0001, 0.0001), (0, 0))
    version = tests.factories.observation(geometry=tiny, attributes={})
    assert not peri_scribe.perimeters.size_filtering.perimeter_is_implausibly_small(
        version,
    )


def test_perimeter_is_implausibly_small_keeps_without_geometry() -> None:
    version = tests.factories.observation(
        geometry=None,
        attributes={"area_acres": 1000},
    )
    assert not peri_scribe.perimeters.size_filtering.perimeter_is_implausibly_small(
        version,
    )


def test_drop_implausibly_small_perimeters_drops_collapsed() -> None:
    tiny = tests.factories.polygon((0, 0), (0.0001, 0), (0.0001, 0.0001), (0, 0))
    large = tests.factories.polygon((0, 0), (1, 0), (1, 1), (0, 0))
    observations = [
        tests.factories.observation(
            geometry=large,
            attributes={"area_acres": 3_000_000},
        ),
        tests.factories.observation(geometry=tiny, attributes={"area_acres": 1000}),
    ]
    survivors = peri_scribe.perimeters.size_filtering.drop_implausibly_small_perimeters(
        observations,
    )
    assert survivors == [observations[0]]


def test_attributes_are_equal_compares_keys_and_values() -> None:
    assert peri_scribe.perimeters.versions.attributes_are_equal(
        {"a": 1, "b": 2},
        {"a": 1, "b": 2},
    )
    assert not peri_scribe.perimeters.versions.attributes_are_equal(
        {"a": 1},
        {"a": 1, "b": 2},
    )
    assert not peri_scribe.perimeters.versions.attributes_are_equal(
        {"a": 1},
        {"a": 2},
    )


def test_point_versions_folds_geometry_move() -> None:
    first = tests.factories.observation(
        source_kind=tests.factories.WFIGS_LOCATION,
        geometry=tests.factories.point(0, 0),
        snapshot_time=tests.factories.utc(2026, 8, 17, 1, 0),
        serial_number=0,
        attributes={"IncidentSize": 100},
    )
    moved = tests.factories.observation(
        source_kind=tests.factories.WFIGS_LOCATION,
        geometry=tests.factories.point(1, 1),
        snapshot_time=tests.factories.utc(2026, 8, 17, 2, 0),
        serial_number=1,
        attributes={"IncidentSize": 100},
    )
    versions = peri_scribe.perimeters.versions.point_versions([first, moved])
    assert [version.geometry for version in versions] == [tests.factories.point(1, 1)]
    assert versions[0].snapshot_time == moved.snapshot_time


def test_point_versions_creates_version_on_attribute_change() -> None:
    first = tests.factories.observation(
        source_kind=tests.factories.WFIGS_LOCATION,
        geometry=tests.factories.point(0, 0),
        serial_number=0,
        attributes={"IncidentSize": 100},
    )
    second = tests.factories.observation(
        source_kind=tests.factories.WFIGS_LOCATION,
        geometry=tests.factories.point(0, 0),
        serial_number=1,
        attributes={"IncidentSize": 200},
    )
    versions = peri_scribe.perimeters.versions.point_versions([first, second])
    assert versions == [first, second]
