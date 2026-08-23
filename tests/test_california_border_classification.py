"""Tests for peri_scribe.california_border_classification."""

from __future__ import annotations

import datetime
import pathlib

import pytest
import shapely.geometry

import peri_scribe.administrative_boundaries
import peri_scribe.california_border_classification
import peri_scribe.models


CALIFORNIA_BOX = shapely.geometry.box(0.0, 0.0, 100.0, 100.0)
BORDER = shapely.geometry.LineString([(100.0, 0.0), (100.0, 100.0)])

CALIFORNIA_BOX_WGS84 = shapely.geometry.box(-126.0, 31.0, -119.0, 40.0)
CA_BORDER_WGS84 = shapely.geometry.LineString([(-119.0, 38.0), (-119.0, 40.0)])

CONFIG = peri_scribe.california_border_classification.BorderClassificationConfig()

PLANAR_CONFIG = peri_scribe.california_border_classification.BorderClassificationConfig(
    near_border_buffer_in_meters=10.0,
)

FIRIS = peri_scribe.california_border_classification.FireSourceKind.FIRIS_PERIMETER
WFIGS_PERIMETER = (
    peri_scribe.california_border_classification.FireSourceKind.WFIGS_PERIMETER
)
WFIGS_LOCATION = (
    peri_scribe.california_border_classification.FireSourceKind.WFIGS_LOCATION
)


@pytest.fixture
def boundaries() -> peri_scribe.california_border_classification.Boundaries:
    """Return a synthetic California box and border in planar coordinates.

    Returns:
        The California box and the border along its eastern edge.
    """
    return peri_scribe.california_border_classification.Boundaries(
        box=CALIFORNIA_BOX,
        border=BORDER,
    )


@pytest.fixture
def wgs84_boundaries() -> peri_scribe.california_border_classification.Boundaries:
    """Return a synthetic California box and border in California Albers.

    Returns:
        The California box and border, reprojected from WGS84.
    """
    return peri_scribe.california_border_classification.Boundaries(
        box=peri_scribe.california_border_classification.reproject_to_california_albers(
            CALIFORNIA_BOX_WGS84,
            4326,
        ),
        border=peri_scribe.california_border_classification.reproject_to_california_albers(
            CA_BORDER_WGS84,
            4326,
        ),
    )


def observation(
    source: peri_scribe.california_border_classification.FireSourceKind,
    geometry: shapely.geometry.base.BaseGeometry | None,
    *,
    observed_at: datetime.datetime | None = None,
    serial_number: int = 0,
    identifiers: frozenset[str] = frozenset(),
    mission: str | None = None,
    point_of_origin_state: str | None = None,
    point_of_origin_fips: str | None = None,
) -> peri_scribe.california_border_classification.FireObservation:
    """Build a fire observation for a test.

    Returns:
        The fire observation.
    """
    return peri_scribe.california_border_classification.FireObservation(
        source=source,
        geometry=geometry,
        observed_at=observed_at,
        serial_number=serial_number,
        identifiers=identifiers,
        mission=mission,
        point_of_origin_state=point_of_origin_state,
        point_of_origin_fips=point_of_origin_fips,
    )


def classifiable_record(
    *,
    geometry: shapely.geometry.base.BaseGeometry,
    observed_at: datetime.datetime | None = None,
    identifiers: frozenset[str] = frozenset(),
    mission: str | None = None,
    point_of_origin_state: str | None = None,
    point_of_origin_fips: str | None = None,
) -> peri_scribe.models.FireRecord:
    """Build a fire record for classification tests.

    Returns:
        The fire record, named "Fire" and active.
    """
    return peri_scribe.models.FireRecord(
        name="Fire",
        status=peri_scribe.models.FireStatus.ACTIVE,
        identifiers=identifiers,
        geometry=geometry,
        observed_at=observed_at,
        mission=mission,
        point_of_origin_state=point_of_origin_state,
        point_of_origin_fips=point_of_origin_fips,
    )


def geometry_signal(
    *,
    distance_to_boundary_in_meters: float = 100.0,
    outside_area_fraction: float = 0.0,
    outside_area_in_acres: float = 0.0,
    inside_area_fraction: float = 1.0,
    crosses: bool = False,
    near: bool = False,
    inside: bool = True,
) -> peri_scribe.california_border_classification.GeometrySignal:
    """Build a geometry signal, defaulting to a fire fully inside California.

    Returns:
        The geometry signal.
    """
    return peri_scribe.california_border_classification.GeometrySignal(
        distance_to_boundary_in_meters=distance_to_boundary_in_meters,
        outside_area_fraction=outside_area_fraction,
        outside_area_in_acres=outside_area_in_acres,
        inside_area_fraction=inside_area_fraction,
        crosses=crosses,
        near=near,
        inside=inside,
    )


def extent_signal(
    *,
    wfigs_to_firis_area_ratio: float | None = None,
    disagrees: bool = False,
) -> peri_scribe.california_border_classification.ExtentSignal:
    """Build an extent signal, defaulting to no disagreement.

    Returns:
        The extent signal.
    """
    return peri_scribe.california_border_classification.ExtentSignal(
        wfigs_to_firis_area_ratio=wfigs_to_firis_area_ratio,
        disagrees=disagrees,
    )


def test_source_kind_for_feed_name_recognizes_firis() -> None:
    assert (
        peri_scribe.california_border_classification.source_kind_for_feed_name(
            "CA_Perimeters_NIFC_FIRIS_public_view_0",
        )
        is FIRIS
    )


def test_source_kind_for_feed_name_recognizes_wfigs_perimeter() -> None:
    assert (
        peri_scribe.california_border_classification.source_kind_for_feed_name(
            "WFIGS_Interagency_Perimeters_Current_0",
        )
        is WFIGS_PERIMETER
    )


def test_source_kind_for_feed_name_recognizes_wfigs_location() -> None:
    assert (
        peri_scribe.california_border_classification.source_kind_for_feed_name(
            "WFIGS_Incident_Locations_Current_0",
        )
        is WFIGS_LOCATION
    )


def test_source_kind_for_feed_name_rejects_unknown_source() -> None:
    with pytest.raises(ValueError, match="unknown fire source"):
        peri_scribe.california_border_classification.source_kind_for_feed_name(
            "Other_Source_0",
        )


def test_snapshot_serial_number_parses_leading_serial() -> None:
    path = pathlib.Path("000012,lastEdit=1786990894028.gpkg")
    expected_serial_number = 12
    assert (
        peri_scribe.california_border_classification.snapshot_serial_number(path)
        == expected_serial_number
    )


def test_reproject_to_california_albers_returns_projected_geometry() -> None:
    point = shapely.geometry.Point(-120.0, 39.0)
    result = (
        peri_scribe.california_border_classification.reproject_to_california_albers(
            point,
            4326,
        )
    )
    assert isinstance(result, shapely.geometry.Point)
    assert result != point


def test_reproject_to_california_albers_preserves_z_coordinates() -> None:
    point = shapely.geometry.Point(-120.0, 39.0, 123.0)
    result = (
        peri_scribe.california_border_classification.reproject_to_california_albers(
            point,
            4326,
        )
    )
    assert isinstance(result, shapely.geometry.Point)
    assert result.z == pytest.approx(123.0)


def test_load_boundaries_builds_box_and_reprojects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        peri_scribe.administrative_boundaries,
        "load_border_geometry",
        lambda _base_dir: CA_BORDER_WGS84,
    )
    monkeypatch.setattr(
        peri_scribe.administrative_boundaries,
        "california_box_polygon",
        lambda _border: CALIFORNIA_BOX_WGS84,
    )
    loaded = peri_scribe.california_border_classification.load_boundaries(
        pathlib.Path("/base"),
    )
    assert isinstance(loaded.box, shapely.geometry.Polygon)
    assert isinstance(loaded.border, shapely.geometry.LineString)


def test_union_geometry_returns_none_without_geometries() -> None:
    assert peri_scribe.california_border_classification.union_geometry([]) is None


def test_union_geometry_skips_missing_and_empty_geometries() -> None:
    observations = [
        observation(
            FIRIS,
            shapely.geometry.Point(-120.0, 39.0),
        ),
        observation(
            WFIGS_PERIMETER,
            None,
        ),
        observation(
            WFIGS_LOCATION,
            shapely.geometry.Polygon(),
        ),
    ]
    union = peri_scribe.california_border_classification.union_geometry(observations)
    assert isinstance(union, shapely.geometry.Point)


def test_geometry_signal_inside_california(
    boundaries: peri_scribe.california_border_classification.Boundaries,
) -> None:
    result = peri_scribe.california_border_classification.geometry_signal(
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
    boundaries: peri_scribe.california_border_classification.Boundaries,
) -> None:
    result = peri_scribe.california_border_classification.geometry_signal(
        shapely.geometry.box(90.0, 0.0, 99.0, 100.0),
        boundaries,
        PLANAR_CONFIG,
    )
    assert result.inside
    assert not result.crosses
    assert result.near
    assert result.distance_to_boundary_in_meters == pytest.approx(1.0)


def test_geometry_signal_outside_california(
    boundaries: peri_scribe.california_border_classification.Boundaries,
) -> None:
    result = peri_scribe.california_border_classification.geometry_signal(
        shapely.geometry.box(150.0, 0.0, 190.0, 100.0),
        boundaries,
        PLANAR_CONFIG,
    )
    assert not result.inside
    assert result.inside_area_fraction == pytest.approx(0.0)
    assert not result.crosses
    assert not result.near


def test_geometry_signal_outside_near_border(
    boundaries: peri_scribe.california_border_classification.Boundaries,
) -> None:
    result = peri_scribe.california_border_classification.geometry_signal(
        shapely.geometry.box(101.0, 0.0, 102.0, 100.0),
        boundaries,
        PLANAR_CONFIG,
    )
    assert not result.inside
    assert not result.crosses
    assert result.near
    assert result.distance_to_boundary_in_meters == pytest.approx(1.0)


def test_geometry_signal_crosses_border_by_fraction(
    boundaries: peri_scribe.california_border_classification.Boundaries,
) -> None:
    result = peri_scribe.california_border_classification.geometry_signal(
        shapely.geometry.box(90.0, 0.0, 110.0, 100.0),
        boundaries,
        CONFIG,
    )
    assert result.crosses
    assert result.outside_area_fraction == pytest.approx(0.5)
    assert result.inside_area_fraction == pytest.approx(0.5)
    assert result.outside_area_in_acres > 0.0


def test_geometry_signal_crosses_border_by_absolute_area(
    boundaries: peri_scribe.california_border_classification.Boundaries,
) -> None:
    config = peri_scribe.california_border_classification.BorderClassificationConfig(
        outside_area_fraction_threshold=1.0,
        outside_area_threshold_in_acres=0.01,
    )
    result = peri_scribe.california_border_classification.geometry_signal(
        shapely.geometry.box(90.0, 0.0, 110.0, 100.0),
        boundaries,
        config,
    )
    assert result.crosses


def test_geometry_signal_requires_presence_inside_california_to_cross(
    boundaries: peri_scribe.california_border_classification.Boundaries,
) -> None:
    result = peri_scribe.california_border_classification.geometry_signal(
        shapely.geometry.box(150.0, 0.0, 190.0, 100.0),
        boundaries,
        CONFIG,
    )
    assert not result.crosses


def test_geometry_signal_handles_missing_union(
    boundaries: peri_scribe.california_border_classification.Boundaries,
) -> None:
    result = peri_scribe.california_border_classification.geometry_signal(
        None,
        boundaries,
        CONFIG,
    )
    assert not result.inside
    assert not result.crosses
    assert not result.near
    assert result.distance_to_boundary_in_meters == float("inf")


def test_freshest_observation_prefers_later_observation_time() -> None:
    earlier = observation(
        FIRIS,
        shapely.geometry.Point(-120.0, 39.0),
        observed_at=datetime.datetime(2026, 8, 13, tzinfo=datetime.UTC),
    )
    later = observation(
        FIRIS,
        shapely.geometry.Point(-120.0, 39.0),
        observed_at=datetime.datetime(2026, 8, 17, tzinfo=datetime.UTC),
    )
    assert (
        peri_scribe.california_border_classification.freshest_observation([
            earlier,
            later,
        ])
        is later
    )


def test_freshest_observation_breaks_time_ties_by_serial_number() -> None:
    older_snapshot = observation(
        WFIGS_PERIMETER,
        shapely.geometry.Point(-120.0, 39.0),
        observed_at=datetime.datetime(2026, 8, 13, tzinfo=datetime.UTC),
        serial_number=1,
    )
    newer_snapshot = observation(
        WFIGS_PERIMETER,
        shapely.geometry.Point(-120.0, 39.0),
        observed_at=datetime.datetime(2026, 8, 13, tzinfo=datetime.UTC),
        serial_number=2,
    )
    assert (
        peri_scribe.california_border_classification.freshest_observation(
            [older_snapshot, newer_snapshot],
        )
        is newer_snapshot
    )


def test_freshest_observation_treats_missing_time_as_oldest() -> None:
    untimed = observation(
        FIRIS,
        shapely.geometry.Point(-120.0, 39.0),
    )
    timed = observation(
        FIRIS,
        shapely.geometry.Point(-120.0, 39.0),
        observed_at=datetime.datetime(2026, 8, 13, tzinfo=datetime.UTC),
    )
    assert (
        peri_scribe.california_border_classification.freshest_observation([
            untimed,
            timed,
        ])
        is timed
    )


def test_freshest_observation_raises_for_empty_list() -> None:
    with pytest.raises(ValueError, match="empty"):
        peri_scribe.california_border_classification.freshest_observation([])


def test_are_contemporaneous_true_when_both_times_missing() -> None:
    left = observation(
        FIRIS,
        shapely.geometry.Point(-120.0, 39.0),
    )
    right = observation(
        WFIGS_PERIMETER,
        shapely.geometry.Point(-120.0, 39.0),
    )
    assert peri_scribe.california_border_classification.are_contemporaneous(
        left,
        right,
        CONFIG,
    )


def test_are_contemporaneous_false_when_one_time_missing() -> None:
    left = observation(
        FIRIS,
        shapely.geometry.Point(-120.0, 39.0),
        observed_at=datetime.datetime(2026, 8, 13, tzinfo=datetime.UTC),
    )
    right = observation(
        WFIGS_PERIMETER,
        shapely.geometry.Point(-120.0, 39.0),
    )
    assert not peri_scribe.california_border_classification.are_contemporaneous(
        left,
        right,
        CONFIG,
    )


def test_are_contemporaneous_true_within_tolerance() -> None:
    left = observation(
        FIRIS,
        shapely.geometry.Point(-120.0, 39.0),
        observed_at=datetime.datetime(2026, 8, 13, 0, 0, tzinfo=datetime.UTC),
    )
    right = observation(
        WFIGS_PERIMETER,
        shapely.geometry.Point(-120.0, 39.0),
        observed_at=datetime.datetime(2026, 8, 13, 12, 0, tzinfo=datetime.UTC),
    )
    assert peri_scribe.california_border_classification.are_contemporaneous(
        left,
        right,
        CONFIG,
    )


def test_are_contemporaneous_false_beyond_tolerance() -> None:
    left = observation(
        FIRIS,
        shapely.geometry.Point(-120.0, 39.0),
        observed_at=datetime.datetime(2026, 8, 13, tzinfo=datetime.UTC),
    )
    right = observation(
        WFIGS_PERIMETER,
        shapely.geometry.Point(-120.0, 39.0),
        observed_at=datetime.datetime(2026, 8, 17, tzinfo=datetime.UTC),
    )
    assert not peri_scribe.california_border_classification.are_contemporaneous(
        left,
        right,
        CONFIG,
    )


def test_extent_signal_returns_none_without_both_sources() -> None:
    only_firis = [
        observation(
            FIRIS,
            shapely.geometry.box(-120.5, 39.0, -120.0, 39.1),
            observed_at=datetime.datetime(2026, 8, 13, tzinfo=datetime.UTC),
        ),
    ]
    result = peri_scribe.california_border_classification.extent_signal(
        only_firis,
        CONFIG,
    )
    assert result.wfigs_to_firis_area_ratio is None
    assert not result.disagrees


def test_extent_signal_skips_non_contemporaneous_perimeters() -> None:
    firis = observation(
        FIRIS,
        shapely.geometry.box(-120.5, 39.0, -120.0, 39.1),
        observed_at=datetime.datetime(2026, 8, 13, tzinfo=datetime.UTC),
    )
    wfigs = observation(
        WFIGS_PERIMETER,
        shapely.geometry.box(-120.5, 39.0, -119.0, 39.2),
        observed_at=datetime.datetime(2026, 8, 17, tzinfo=datetime.UTC),
    )
    result = peri_scribe.california_border_classification.extent_signal(
        [firis, wfigs],
        CONFIG,
    )
    assert result.wfigs_to_firis_area_ratio is None
    assert not result.disagrees


def test_extent_signal_disagrees_when_wfigs_is_larger() -> None:
    firis = observation(
        FIRIS,
        shapely.geometry.box(-120.5, 39.0, -120.0, 39.1),
        observed_at=datetime.datetime(2026, 8, 13, tzinfo=datetime.UTC),
    )
    wfigs = observation(
        WFIGS_PERIMETER,
        shapely.geometry.box(-120.5, 39.0, -118.5, 39.2),
        observed_at=datetime.datetime(2026, 8, 13, tzinfo=datetime.UTC),
    )
    result = peri_scribe.california_border_classification.extent_signal(
        [firis, wfigs],
        CONFIG,
    )
    assert result.disagrees
    assert result.wfigs_to_firis_area_ratio is not None
    assert result.wfigs_to_firis_area_ratio > CONFIG.extent_ratio_threshold


def test_extent_signal_disagrees_when_symmetric_difference_is_large() -> None:
    firis = observation(
        FIRIS,
        shapely.geometry.box(-120.5, 39.0, -120.0, 39.1),
        observed_at=datetime.datetime(2026, 8, 13, tzinfo=datetime.UTC),
    )
    wfigs = observation(
        WFIGS_PERIMETER,
        shapely.geometry.box(-120.0, 40.0, -119.5, 40.102),
        observed_at=datetime.datetime(2026, 8, 13, tzinfo=datetime.UTC),
    )
    result = peri_scribe.california_border_classification.extent_signal(
        [firis, wfigs],
        CONFIG,
    )
    assert result.disagrees


def test_extent_signal_agrees_when_perimeters_match() -> None:
    geometry = shapely.geometry.box(-120.5, 39.0, -120.0, 39.1)
    firis = observation(
        FIRIS,
        geometry,
        observed_at=datetime.datetime(2026, 8, 13, tzinfo=datetime.UTC),
    )
    wfigs = observation(
        WFIGS_PERIMETER,
        geometry,
        observed_at=datetime.datetime(2026, 8, 13, tzinfo=datetime.UTC),
    )
    result = peri_scribe.california_border_classification.extent_signal(
        [firis, wfigs],
        CONFIG,
    )
    assert not result.disagrees
    assert result.wfigs_to_firis_area_ratio == pytest.approx(1.0)


def test_extent_signal_ignores_zero_area_firis_perimeter() -> None:
    firis = observation(
        FIRIS,
        shapely.geometry.LineString([(-120.5, 39.0), (-120.0, 39.1)]),
        observed_at=datetime.datetime(2026, 8, 13, tzinfo=datetime.UTC),
    )
    wfigs = observation(
        WFIGS_PERIMETER,
        shapely.geometry.box(-120.5, 39.0, -120.0, 39.1),
        observed_at=datetime.datetime(2026, 8, 13, tzinfo=datetime.UTC),
    )
    result = peri_scribe.california_border_classification.extent_signal(
        [firis, wfigs],
        CONFIG,
    )
    assert result.wfigs_to_firis_area_ratio is None
    assert not result.disagrees


def test_unit_state_code_is_out_of_state_detects_nevada() -> None:
    assert peri_scribe.california_border_classification.unit_state_code_is_out_of_state(
        "nvccd",
    )


def test_unit_state_code_is_out_of_state_accepts_california() -> None:
    assert (
        peri_scribe.california_border_classification.unit_state_code_is_out_of_state(
            "cahvt",
        )
        is False
    )


def test_unit_state_code_is_out_of_state_ignores_non_state_codes() -> None:
    assert (
        peri_scribe.california_border_classification.unit_state_code_is_out_of_state(
            "lpf",
        )
        is False
    )


def test_unit_state_code_is_out_of_state_ignores_short_tokens() -> None:
    assert (
        peri_scribe.california_border_classification.unit_state_code_is_out_of_state(
            "c",
        )
        is False
    )


def test_out_of_state_unit_from_reads_identifiers_and_missions() -> None:
    assert peri_scribe.california_border_classification.out_of_state_unit_from(
        frozenset({"2026-nvccd-030683"}),
        None,
    )
    assert peri_scribe.california_border_classification.out_of_state_unit_from(
        frozenset(),
        "2026-NVCCD-030683",
    )
    assert not peri_scribe.california_border_classification.out_of_state_unit_from(
        frozenset({"2026-cahvt-000753"}),
        "CA-LNU-OTHER",
    )


def test_out_of_state_unit_from_uses_mission_state_token() -> None:
    assert peri_scribe.california_border_classification.out_of_state_unit_from(
        frozenset(),
        "NV-CCD-BUG",
    )


def test_out_of_state_unit_from_ignores_mission_name_tokens() -> None:
    assert not peri_scribe.california_border_classification.out_of_state_unit_from(
        frozenset(),
        "CA-HVT-MILEPOST18-N57B",
    )


def test_identifier_signal_detects_out_of_state_point_of_origin() -> None:
    observations = [
        observation(
            WFIGS_LOCATION,
            shapely.geometry.Point(-120.0, 39.0),
            point_of_origin_state="US-NV",
            point_of_origin_fips="32001",
        ),
    ]
    assert peri_scribe.california_border_classification.identifier_signal(observations)


def test_identifier_signal_ignores_california_point_of_origin() -> None:
    observations = [
        observation(
            WFIGS_LOCATION,
            shapely.geometry.Point(-120.0, 39.0),
            point_of_origin_state="US-CA",
            point_of_origin_fips="06035",
        ),
    ]
    assert not peri_scribe.california_border_classification.identifier_signal(
        observations,
    )


def test_identifier_signal_detects_non_california_fips() -> None:
    observations = [
        observation(
            WFIGS_LOCATION,
            shapely.geometry.Point(-120.0, 39.0),
            point_of_origin_state="US-CA",
            point_of_origin_fips="32001",
        ),
    ]
    assert peri_scribe.california_border_classification.identifier_signal(observations)


def test_classify_crosses_border() -> None:
    geometry = geometry_signal(
        distance_to_boundary_in_meters=0.0,
        outside_area_fraction=0.5,
        outside_area_in_acres=100.0,
        inside_area_fraction=0.5,
        crosses=True,
        near=True,
    )
    extent = extent_signal()
    result = peri_scribe.california_border_classification.classify(
        geometry=geometry,
        extent=extent,
        identifier=False,
    )
    assert (
        result.classification
        is peri_scribe.models.BorderClassification.CROSSES_CALIFORNIA_BORDER
    )
    assert peri_scribe.models.BorderSignal.GEOMETRY_OUTSIDE in result.signals


def test_classify_inside_near_border_from_geometry() -> None:
    geometry = geometry_signal(distance_to_boundary_in_meters=5.0, near=True)
    extent = extent_signal()
    result = peri_scribe.california_border_classification.classify(
        geometry=geometry,
        extent=extent,
        identifier=False,
    )
    assert (
        result.classification
        is peri_scribe.models.BorderClassification.INSIDE_CALIFORNIA_NEAR_BORDER
    )


def test_classify_inside_near_border_from_extent_disagreement() -> None:
    geometry = geometry_signal()
    extent = extent_signal(wfigs_to_firis_area_ratio=1.5, disagrees=True)
    result = peri_scribe.california_border_classification.classify(
        geometry=geometry,
        extent=extent,
        identifier=False,
    )
    assert (
        result.classification
        is peri_scribe.models.BorderClassification.INSIDE_CALIFORNIA_NEAR_BORDER
    )


def test_classify_outside_near_border_from_geometry() -> None:
    geometry = geometry_signal(
        distance_to_boundary_in_meters=2.0,
        outside_area_fraction=1.0,
        outside_area_in_acres=5000.0,
        inside_area_fraction=0.0,
        near=True,
        inside=False,
    )
    extent = extent_signal()
    result = peri_scribe.california_border_classification.classify(
        geometry=geometry,
        extent=extent,
        identifier=False,
    )
    assert (
        result.classification
        is peri_scribe.models.BorderClassification.OUTSIDE_CALIFORNIA_NEAR_BORDER
    )


def test_classify_inside_california() -> None:
    geometry = geometry_signal()
    extent = extent_signal()
    result = peri_scribe.california_border_classification.classify(
        geometry=geometry,
        extent=extent,
        identifier=False,
    )
    assert (
        result.classification
        is peri_scribe.models.BorderClassification.INSIDE_CALIFORNIA
    )


def test_classify_outside_california() -> None:
    geometry = geometry_signal(
        distance_to_boundary_in_meters=2000.0,
        inside_area_fraction=0.0,
        inside=False,
    )
    extent = extent_signal()
    result = peri_scribe.california_border_classification.classify(
        geometry=geometry,
        extent=extent,
        identifier=False,
    )
    assert (
        result.classification
        is peri_scribe.models.BorderClassification.OUTSIDE_CALIFORNIA
    )


def test_classify_identifier_alone_stays_inside_california() -> None:
    geometry = geometry_signal()
    extent = extent_signal()
    result = peri_scribe.california_border_classification.classify(
        geometry=geometry,
        extent=extent,
        identifier=True,
    )
    assert (
        result.classification
        is peri_scribe.models.BorderClassification.INSIDE_CALIFORNIA
    )
    assert result.signals == [peri_scribe.models.BorderSignal.IDENTIFIER_UNIT]


def test_classify_fire_classifies_cross_border_fire(
    wgs84_boundaries: peri_scribe.california_border_classification.Boundaries,
) -> None:
    records = [
        classifiable_record(
            geometry=shapely.geometry.box(-120.5, 39.0, -118.5, 39.5),
            observed_at=datetime.datetime(2026, 8, 16, tzinfo=datetime.UTC),
        ),
    ]
    record_paths = [
        pathlib.Path(
            "sources/CA_Perimeters_NIFC_FIRIS_public_view_0/000___/000000,lastEdit=0.gpkg",
        ),
    ]
    result = peri_scribe.california_border_classification.classify_fire(
        records=records,
        record_paths=record_paths,
        boundaries=wgs84_boundaries,
    )
    assert (
        result.classification
        is peri_scribe.models.BorderClassification.CROSSES_CALIFORNIA_BORDER
    )


def test_classify_fire_classifies_inside_california_fire(
    wgs84_boundaries: peri_scribe.california_border_classification.Boundaries,
) -> None:
    records = [
        classifiable_record(
            geometry=shapely.geometry.box(-120.5, 39.0, -120.0, 39.5),
            observed_at=datetime.datetime(2026, 8, 16, tzinfo=datetime.UTC),
        ),
    ]
    record_paths = [
        pathlib.Path(
            "sources/CA_Perimeters_NIFC_FIRIS_public_view_0/000___/000000,lastEdit=0.gpkg",
        ),
    ]
    result = peri_scribe.california_border_classification.classify_fire(
        records=records,
        record_paths=record_paths,
        boundaries=wgs84_boundaries,
    )
    assert (
        result.classification
        is peri_scribe.models.BorderClassification.INSIDE_CALIFORNIA
    )


def test_classify_fire_classifies_outside_california_fire(
    wgs84_boundaries: peri_scribe.california_border_classification.Boundaries,
) -> None:
    records = [
        classifiable_record(
            geometry=shapely.geometry.box(-117.5, 39.0, -116.0, 39.5),
        ),
    ]
    record_paths = [
        pathlib.Path(
            "sources/WFIGS_Interagency_Perimeters_Current_0/000___/000000,lastEdit=0.gpkg",
        ),
    ]
    result = peri_scribe.california_border_classification.classify_fire(
        records=records,
        record_paths=record_paths,
        boundaries=wgs84_boundaries,
    )
    assert (
        result.classification
        is peri_scribe.models.BorderClassification.OUTSIDE_CALIFORNIA
    )


def test_classify_fire_captures_identifier_signal(
    wgs84_boundaries: peri_scribe.california_border_classification.Boundaries,
) -> None:
    records = [
        classifiable_record(
            geometry=shapely.geometry.box(-120.5, 39.0, -120.0, 39.5),
            identifiers=frozenset({"2026-nvccd-030683"}),
        ),
    ]
    record_paths = [
        pathlib.Path(
            "sources/CA_Perimeters_NIFC_FIRIS_public_view_0/000___/000000,lastEdit=0.gpkg",
        ),
    ]
    result = peri_scribe.california_border_classification.classify_fire(
        records=records,
        record_paths=record_paths,
        boundaries=wgs84_boundaries,
    )
    assert peri_scribe.models.BorderSignal.IDENTIFIER_UNIT in result.signals


def test_classify_fire_keeps_coastal_fire_inside(
    wgs84_boundaries: peri_scribe.california_border_classification.Boundaries,
) -> None:
    records = [
        classifiable_record(
            geometry=shapely.geometry.box(-121.5, 39.0, -119.5, 39.5),
        ),
    ]
    record_paths = [
        pathlib.Path(
            "sources/CA_Perimeters_NIFC_FIRIS_public_view_0/000___/000000,lastEdit=0.gpkg",
        ),
    ]
    result = peri_scribe.california_border_classification.classify_fire(
        records=records,
        record_paths=record_paths,
        boundaries=wgs84_boundaries,
    )
    assert (
        result.classification
        is peri_scribe.models.BorderClassification.INSIDE_CALIFORNIA
    )
