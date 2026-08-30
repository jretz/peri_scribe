"""Tests for peri_scribe.perimeters.border_classification."""

from __future__ import annotations

import datetime

import pytest
import shapely.geometry

import peri_scribe.perimeters.border_classification
import peri_scribe.perimeters.signals
import tests.peri_scribe.perimeters.border_helpers


CONFIG = peri_scribe.perimeters.border_classification.BorderClassificationConfig()

PLANAR_CONFIG = peri_scribe.perimeters.border_classification.BorderClassificationConfig(
    near_border_buffer_in_meters=10.0,
)


def test_geometry_signal_inside_california(
    boundaries: peri_scribe.perimeters.border_classification.Boundaries,
) -> None:
    result = peri_scribe.perimeters.signals.geometry_signal(
        shapely.geometry.box(0.0, 0.0, 50.0, 50.0),
        boundaries,
        PLANAR_CONFIG,
    )
    assert result.inside
    assert result.inside_area_fraction == pytest.approx(1.0)
    assert not result.crosses
    assert not result.near
    assert result.outside_area_fraction == pytest.approx(0.0)
    assert result.outside_area_in_acres == pytest.approx(0.0)
    assert result.distance_to_boundary_in_meters == pytest.approx(50.0)


def test_geometry_signal_inside_near_border(
    boundaries: peri_scribe.perimeters.border_classification.Boundaries,
) -> None:
    result = peri_scribe.perimeters.signals.geometry_signal(
        shapely.geometry.box(90.0, 0.0, 99.0, 100.0),
        boundaries,
        PLANAR_CONFIG,
    )
    assert result.inside
    assert not result.crosses
    assert result.near
    assert result.distance_to_boundary_in_meters == pytest.approx(1.0)


def test_geometry_signal_outside_california(
    boundaries: peri_scribe.perimeters.border_classification.Boundaries,
) -> None:
    result = peri_scribe.perimeters.signals.geometry_signal(
        shapely.geometry.box(150.0, 0.0, 190.0, 100.0),
        boundaries,
        PLANAR_CONFIG,
    )
    assert not result.inside
    assert result.inside_area_fraction == pytest.approx(0.0)
    assert not result.crosses
    assert not result.near


def test_geometry_signal_outside_near_border(
    boundaries: peri_scribe.perimeters.border_classification.Boundaries,
) -> None:
    result = peri_scribe.perimeters.signals.geometry_signal(
        shapely.geometry.box(101.0, 0.0, 102.0, 100.0),
        boundaries,
        PLANAR_CONFIG,
    )
    assert not result.inside
    assert not result.crosses
    assert result.near
    assert result.distance_to_boundary_in_meters == pytest.approx(1.0)


def test_geometry_signal_crosses_border_by_fraction(
    boundaries: peri_scribe.perimeters.border_classification.Boundaries,
) -> None:
    result = peri_scribe.perimeters.signals.geometry_signal(
        shapely.geometry.box(90.0, 0.0, 110.0, 100.0),
        boundaries,
        CONFIG,
    )
    assert result.crosses
    assert result.outside_area_fraction == pytest.approx(0.5)
    assert result.inside_area_fraction == pytest.approx(0.5)
    assert result.outside_area_in_acres > 0.0


def test_geometry_signal_crosses_border_by_absolute_area(
    boundaries: peri_scribe.perimeters.border_classification.Boundaries,
) -> None:
    config = peri_scribe.perimeters.border_classification.BorderClassificationConfig(
        outside_area_fraction_threshold=1.0,
        outside_area_threshold_in_acres=0.01,
    )
    result = peri_scribe.perimeters.signals.geometry_signal(
        shapely.geometry.box(90.0, 0.0, 110.0, 100.0),
        boundaries,
        config,
    )
    assert result.crosses


def test_geometry_signal_requires_presence_inside_california_to_cross(
    boundaries: peri_scribe.perimeters.border_classification.Boundaries,
) -> None:
    result = peri_scribe.perimeters.signals.geometry_signal(
        shapely.geometry.box(150.0, 0.0, 190.0, 100.0),
        boundaries,
        CONFIG,
    )
    assert not result.crosses


def test_geometry_signal_handles_missing_union(
    boundaries: peri_scribe.perimeters.border_classification.Boundaries,
) -> None:
    result = peri_scribe.perimeters.signals.geometry_signal(
        None,
        boundaries,
        CONFIG,
    )
    assert not result.inside
    assert not result.crosses
    assert not result.near
    assert result.distance_to_boundary_in_meters == float("inf")


def test_geometry_signal_one_sided_inside_collection(
    boundaries: peri_scribe.perimeters.border_classification.Boundaries,
) -> None:
    union = shapely.geometry.GeometryCollection([
        shapely.geometry.box(1.0, 1.0, 2.0, 2.0),
        shapely.geometry.box(3.0, 3.0, 4.0, 4.0),
        shapely.geometry.Point(5.0, 5.0),
    ])
    result = peri_scribe.perimeters.signals.geometry_signal(
        union,
        boundaries,
        PLANAR_CONFIG,
    )
    assert result.inside
    assert result.inside_area_fraction == pytest.approx(1.0)
    assert result.outside_area_fraction == pytest.approx(0.0)
    assert result.outside_area_in_acres == pytest.approx(0.0)
    assert not result.crosses
    assert result.distance_to_boundary_in_meters == pytest.approx(95.0)


def test_geometry_signal_one_sided_outside_collection(
    boundaries: peri_scribe.perimeters.border_classification.Boundaries,
) -> None:
    union = shapely.geometry.GeometryCollection([
        shapely.geometry.box(150.0, 0.0, 160.0, 10.0),
        shapely.geometry.Point(200.0, 200.0),
    ])
    result = peri_scribe.perimeters.signals.geometry_signal(
        union,
        boundaries,
        PLANAR_CONFIG,
    )
    assert not result.inside
    assert result.inside_area_fraction == pytest.approx(0.0)
    assert result.outside_area_fraction == pytest.approx(1.0)
    assert not result.crosses
    assert result.distance_to_boundary_in_meters == pytest.approx(50.0)


def test_geometry_signal_one_sided_inside_point_only(
    boundaries: peri_scribe.perimeters.border_classification.Boundaries,
) -> None:
    union = shapely.geometry.GeometryCollection([
        shapely.geometry.Point(5.0, 5.0),
    ])
    result = peri_scribe.perimeters.signals.geometry_signal(
        union,
        boundaries,
        PLANAR_CONFIG,
    )
    assert not result.inside
    assert result.inside_area_fraction == pytest.approx(0.0)
    assert result.outside_area_fraction == pytest.approx(0.0)
    assert not result.crosses


def test_geometry_signal_one_sided_outside_point_only(
    boundaries: peri_scribe.perimeters.border_classification.Boundaries,
) -> None:
    union = shapely.geometry.GeometryCollection([
        shapely.geometry.Point(200.0, 200.0),
    ])
    result = peri_scribe.perimeters.signals.geometry_signal(
        union,
        boundaries,
        PLANAR_CONFIG,
    )
    assert not result.inside
    assert result.inside_area_fraction == pytest.approx(0.0)
    assert result.outside_area_fraction == pytest.approx(0.0)
    assert not result.crosses


def test_geometry_signal_one_sided_near_border(
    boundaries: peri_scribe.perimeters.border_classification.Boundaries,
) -> None:
    union = shapely.geometry.GeometryCollection([
        shapely.geometry.box(101.0, 0.0, 102.0, 100.0),
    ])
    result = peri_scribe.perimeters.signals.geometry_signal(
        union,
        boundaries,
        PLANAR_CONFIG,
    )
    assert result.near
    assert not result.inside
    assert not result.crosses
    assert result.distance_to_boundary_in_meters == pytest.approx(1.0)


def test_freshest_observation_prefers_later_observation_time() -> None:
    earlier = tests.peri_scribe.perimeters.border_helpers.observation(
        tests.peri_scribe.perimeters.border_helpers.FIRIS,
        shapely.geometry.Point(-120.0, 39.0),
        observed_at=datetime.datetime(2026, 8, 13, tzinfo=datetime.UTC),
    )
    later = tests.peri_scribe.perimeters.border_helpers.observation(
        tests.peri_scribe.perimeters.border_helpers.FIRIS,
        shapely.geometry.Point(-120.0, 39.0),
        observed_at=datetime.datetime(2026, 8, 17, tzinfo=datetime.UTC),
    )
    assert (
        peri_scribe.perimeters.signals.freshest_observation([
            earlier,
            later,
        ])
        is later
    )


def test_freshest_observation_breaks_time_ties_by_serial_number() -> None:
    older_snapshot = tests.peri_scribe.perimeters.border_helpers.observation(
        tests.peri_scribe.perimeters.border_helpers.WFIGS_PERIMETER,
        shapely.geometry.Point(-120.0, 39.0),
        observed_at=datetime.datetime(2026, 8, 13, tzinfo=datetime.UTC),
        serial_number=1,
    )
    newer_snapshot = tests.peri_scribe.perimeters.border_helpers.observation(
        tests.peri_scribe.perimeters.border_helpers.WFIGS_PERIMETER,
        shapely.geometry.Point(-120.0, 39.0),
        observed_at=datetime.datetime(2026, 8, 13, tzinfo=datetime.UTC),
        serial_number=2,
    )
    assert (
        peri_scribe.perimeters.signals.freshest_observation(
            [older_snapshot, newer_snapshot],
        )
        is newer_snapshot
    )


def test_freshest_observation_treats_missing_time_as_oldest() -> None:
    untimed = tests.peri_scribe.perimeters.border_helpers.observation(
        tests.peri_scribe.perimeters.border_helpers.FIRIS,
        shapely.geometry.Point(-120.0, 39.0),
    )
    timed = tests.peri_scribe.perimeters.border_helpers.observation(
        tests.peri_scribe.perimeters.border_helpers.FIRIS,
        shapely.geometry.Point(-120.0, 39.0),
        observed_at=datetime.datetime(2026, 8, 13, tzinfo=datetime.UTC),
    )
    assert (
        peri_scribe.perimeters.signals.freshest_observation([
            untimed,
            timed,
        ])
        is timed
    )


def test_freshest_observation_raises_for_empty_list() -> None:
    with pytest.raises(ValueError, match="empty"):
        peri_scribe.perimeters.signals.freshest_observation([])


def test_are_contemporaneous_true_when_both_times_missing() -> None:
    left = tests.peri_scribe.perimeters.border_helpers.observation(
        tests.peri_scribe.perimeters.border_helpers.FIRIS,
        shapely.geometry.Point(-120.0, 39.0),
    )
    right = tests.peri_scribe.perimeters.border_helpers.observation(
        tests.peri_scribe.perimeters.border_helpers.WFIGS_PERIMETER,
        shapely.geometry.Point(-120.0, 39.0),
    )
    assert peri_scribe.perimeters.signals.are_contemporaneous(
        left,
        right,
        CONFIG,
    )


def test_are_contemporaneous_false_when_one_time_missing() -> None:
    left = tests.peri_scribe.perimeters.border_helpers.observation(
        tests.peri_scribe.perimeters.border_helpers.FIRIS,
        shapely.geometry.Point(-120.0, 39.0),
        observed_at=datetime.datetime(2026, 8, 13, tzinfo=datetime.UTC),
    )
    right = tests.peri_scribe.perimeters.border_helpers.observation(
        tests.peri_scribe.perimeters.border_helpers.WFIGS_PERIMETER,
        shapely.geometry.Point(-120.0, 39.0),
    )
    assert not peri_scribe.perimeters.signals.are_contemporaneous(
        left,
        right,
        CONFIG,
    )


def test_are_contemporaneous_true_within_tolerance() -> None:
    left = tests.peri_scribe.perimeters.border_helpers.observation(
        tests.peri_scribe.perimeters.border_helpers.FIRIS,
        shapely.geometry.Point(-120.0, 39.0),
        observed_at=datetime.datetime(2026, 8, 13, 0, 0, tzinfo=datetime.UTC),
    )
    right = tests.peri_scribe.perimeters.border_helpers.observation(
        tests.peri_scribe.perimeters.border_helpers.WFIGS_PERIMETER,
        shapely.geometry.Point(-120.0, 39.0),
        observed_at=datetime.datetime(2026, 8, 13, 12, 0, tzinfo=datetime.UTC),
    )
    assert peri_scribe.perimeters.signals.are_contemporaneous(
        left,
        right,
        CONFIG,
    )


def test_are_contemporaneous_false_beyond_tolerance() -> None:
    left = tests.peri_scribe.perimeters.border_helpers.observation(
        tests.peri_scribe.perimeters.border_helpers.FIRIS,
        shapely.geometry.Point(-120.0, 39.0),
        observed_at=datetime.datetime(2026, 8, 13, tzinfo=datetime.UTC),
    )
    right = tests.peri_scribe.perimeters.border_helpers.observation(
        tests.peri_scribe.perimeters.border_helpers.WFIGS_PERIMETER,
        shapely.geometry.Point(-120.0, 39.0),
        observed_at=datetime.datetime(2026, 8, 17, tzinfo=datetime.UTC),
    )
    assert not peri_scribe.perimeters.signals.are_contemporaneous(
        left,
        right,
        CONFIG,
    )


def test_extent_signal_returns_none_without_both_sources() -> None:
    only_firis = [
        tests.peri_scribe.perimeters.border_helpers.observation(
            tests.peri_scribe.perimeters.border_helpers.FIRIS,
            shapely.geometry.box(-120.5, 39.0, -120.0, 39.1),
            observed_at=datetime.datetime(2026, 8, 13, tzinfo=datetime.UTC),
        ),
    ]
    result = peri_scribe.perimeters.signals.extent_signal(
        only_firis,
        CONFIG,
    )
    assert result.wfigs_to_firis_area_ratio is None
    assert not result.disagrees


def test_extent_signal_skips_non_contemporaneous_perimeters() -> None:
    firis = tests.peri_scribe.perimeters.border_helpers.observation(
        tests.peri_scribe.perimeters.border_helpers.FIRIS,
        shapely.geometry.box(-120.5, 39.0, -120.0, 39.1),
        observed_at=datetime.datetime(2026, 8, 13, tzinfo=datetime.UTC),
    )
    wfigs = tests.peri_scribe.perimeters.border_helpers.observation(
        tests.peri_scribe.perimeters.border_helpers.WFIGS_PERIMETER,
        shapely.geometry.box(-120.5, 39.0, -119.0, 39.2),
        observed_at=datetime.datetime(2026, 8, 17, tzinfo=datetime.UTC),
    )
    result = peri_scribe.perimeters.signals.extent_signal(
        [firis, wfigs],
        CONFIG,
    )
    assert result.wfigs_to_firis_area_ratio is None
    assert not result.disagrees


def test_extent_signal_disagrees_when_wfigs_is_larger() -> None:
    firis = tests.peri_scribe.perimeters.border_helpers.observation(
        tests.peri_scribe.perimeters.border_helpers.FIRIS,
        shapely.geometry.box(-120.5, 39.0, -120.0, 39.1),
        observed_at=datetime.datetime(2026, 8, 13, tzinfo=datetime.UTC),
    )
    wfigs = tests.peri_scribe.perimeters.border_helpers.observation(
        tests.peri_scribe.perimeters.border_helpers.WFIGS_PERIMETER,
        shapely.geometry.box(-120.5, 39.0, -118.5, 39.2),
        observed_at=datetime.datetime(2026, 8, 13, tzinfo=datetime.UTC),
    )
    result = peri_scribe.perimeters.signals.extent_signal(
        [firis, wfigs],
        CONFIG,
    )
    assert result.disagrees
    assert result.wfigs_to_firis_area_ratio is not None
    assert result.wfigs_to_firis_area_ratio > CONFIG.extent_ratio_threshold


def test_extent_signal_disagrees_when_symmetric_difference_is_large() -> None:
    firis = tests.peri_scribe.perimeters.border_helpers.observation(
        tests.peri_scribe.perimeters.border_helpers.FIRIS,
        shapely.geometry.box(-120.5, 39.0, -120.0, 39.1),
        observed_at=datetime.datetime(2026, 8, 13, tzinfo=datetime.UTC),
    )
    wfigs = tests.peri_scribe.perimeters.border_helpers.observation(
        tests.peri_scribe.perimeters.border_helpers.WFIGS_PERIMETER,
        shapely.geometry.box(-120.0, 40.0, -119.5, 40.102),
        observed_at=datetime.datetime(2026, 8, 13, tzinfo=datetime.UTC),
    )
    result = peri_scribe.perimeters.signals.extent_signal(
        [firis, wfigs],
        CONFIG,
    )
    assert result.disagrees


def test_extent_signal_agrees_when_perimeters_match() -> None:
    geometry = shapely.geometry.box(-120.5, 39.0, -120.0, 39.1)
    firis = tests.peri_scribe.perimeters.border_helpers.observation(
        tests.peri_scribe.perimeters.border_helpers.FIRIS,
        geometry,
        observed_at=datetime.datetime(2026, 8, 13, tzinfo=datetime.UTC),
    )
    wfigs = tests.peri_scribe.perimeters.border_helpers.observation(
        tests.peri_scribe.perimeters.border_helpers.WFIGS_PERIMETER,
        geometry,
        observed_at=datetime.datetime(2026, 8, 13, tzinfo=datetime.UTC),
    )
    result = peri_scribe.perimeters.signals.extent_signal(
        [firis, wfigs],
        CONFIG,
    )
    assert not result.disagrees
    assert result.wfigs_to_firis_area_ratio == pytest.approx(1.0)


def test_extent_signal_ignores_zero_area_firis_perimeter() -> None:
    firis = tests.peri_scribe.perimeters.border_helpers.observation(
        tests.peri_scribe.perimeters.border_helpers.FIRIS,
        shapely.geometry.LineString([(-120.5, 39.0), (-120.0, 39.1)]),
        observed_at=datetime.datetime(2026, 8, 13, tzinfo=datetime.UTC),
    )
    wfigs = tests.peri_scribe.perimeters.border_helpers.observation(
        tests.peri_scribe.perimeters.border_helpers.WFIGS_PERIMETER,
        shapely.geometry.box(-120.5, 39.0, -120.0, 39.1),
        observed_at=datetime.datetime(2026, 8, 13, tzinfo=datetime.UTC),
    )
    result = peri_scribe.perimeters.signals.extent_signal(
        [firis, wfigs],
        CONFIG,
    )
    assert result.wfigs_to_firis_area_ratio is None
    assert not result.disagrees


def test_unit_state_code_is_out_of_state_detects_nevada() -> None:
    assert peri_scribe.perimeters.signals.unit_state_code_is_out_of_state(
        "nvccd",
    )


def test_unit_state_code_is_out_of_state_accepts_california() -> None:
    assert (
        peri_scribe.perimeters.signals.unit_state_code_is_out_of_state(
            "cahvt",
        )
        is False
    )


def test_unit_state_code_is_out_of_state_ignores_non_state_codes() -> None:
    assert (
        peri_scribe.perimeters.signals.unit_state_code_is_out_of_state(
            "lpf",
        )
        is False
    )


def test_unit_state_code_is_out_of_state_ignores_short_tokens() -> None:
    assert (
        peri_scribe.perimeters.signals.unit_state_code_is_out_of_state(
            "c",
        )
        is False
    )


def test_out_of_state_unit_from_reads_identifiers_and_missions() -> None:
    assert peri_scribe.perimeters.signals.out_of_state_unit_from(
        frozenset({"2026-nvccd-030683"}),
        None,
    )
    assert peri_scribe.perimeters.signals.out_of_state_unit_from(
        frozenset(),
        "2026-NVCCD-030683",
    )
    assert not peri_scribe.perimeters.signals.out_of_state_unit_from(
        frozenset({"2026-cahvt-000753"}),
        "CA-LNU-OTHER",
    )


def test_out_of_state_unit_from_uses_mission_state_token() -> None:
    assert peri_scribe.perimeters.signals.out_of_state_unit_from(
        frozenset(),
        "NV-CCD-BUG",
    )


def test_out_of_state_unit_from_ignores_mission_name_tokens() -> None:
    assert not peri_scribe.perimeters.signals.out_of_state_unit_from(
        frozenset(),
        "CA-HVT-MILEPOST18-N57B",
    )


def test_identifier_signal_detects_out_of_state_point_of_origin() -> None:
    observations = [
        tests.peri_scribe.perimeters.border_helpers.observation(
            tests.peri_scribe.perimeters.border_helpers.WFIGS_LOCATION,
            shapely.geometry.Point(-120.0, 39.0),
            point_of_origin_state="US-NV",
            point_of_origin_fips="32001",
        ),
    ]
    assert peri_scribe.perimeters.signals.identifier_signal(observations)


def test_identifier_signal_ignores_california_point_of_origin() -> None:
    observations = [
        tests.peri_scribe.perimeters.border_helpers.observation(
            tests.peri_scribe.perimeters.border_helpers.WFIGS_LOCATION,
            shapely.geometry.Point(-120.0, 39.0),
            point_of_origin_state="US-CA",
            point_of_origin_fips="06035",
        ),
    ]
    assert not peri_scribe.perimeters.signals.identifier_signal(
        observations,
    )


def test_identifier_signal_detects_non_california_fips() -> None:
    observations = [
        tests.peri_scribe.perimeters.border_helpers.observation(
            tests.peri_scribe.perimeters.border_helpers.WFIGS_LOCATION,
            shapely.geometry.Point(-120.0, 39.0),
            point_of_origin_state="US-CA",
            point_of_origin_fips="32001",
        ),
    ]
    assert peri_scribe.perimeters.signals.identifier_signal(observations)
