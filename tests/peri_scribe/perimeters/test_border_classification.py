"""Tests for peri_scribe.perimeters.border_classification."""

from __future__ import annotations

import datetime
import pathlib

import pytest
import shapely.geometry

import peri_scribe.models
import peri_scribe.perimeters.border_classification
import peri_scribe.sources.administrative_boundaries
import peri_scribe.sources.borders
import tests.peri_scribe.perimeters.border_helpers


CALIFORNIA_BOX = shapely.geometry.box(0.0, 0.0, 100.0, 100.0)

BORDER = shapely.geometry.LineString([(100.0, 0.0), (100.0, 100.0)])

CALIFORNIA_BOX_WGS84 = shapely.geometry.box(-126.0, 31.0, -119.0, 40.0)

CA_BORDER_WGS84 = shapely.geometry.LineString([(-119.0, 38.0), (-119.0, 40.0)])


@pytest.fixture
def wgs84_boundaries() -> peri_scribe.perimeters.border_classification.Boundaries:
    """Return a synthetic California box and border in California Albers.

    Returns:
        The California box and border, reprojected from WGS84.
    """
    return peri_scribe.perimeters.border_classification.Boundaries(
        box=peri_scribe.perimeters.border_classification.reproject_to_california_albers(
            CALIFORNIA_BOX_WGS84,
            4326,
        ),
        border=peri_scribe.perimeters.border_classification.reproject_to_california_albers(
            CA_BORDER_WGS84,
            4326,
        ),
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


def test_source_kind_for_feed_name_recognizes_firis() -> None:
    assert (
        peri_scribe.perimeters.border_classification.source_kind_for_feed_name(
            "CA_Perimeters_NIFC_FIRIS_public_view_0",
        )
        is tests.peri_scribe.perimeters.border_helpers.FIRIS
    )


def test_source_kind_for_feed_name_recognizes_wfigs_perimeter() -> None:
    assert (
        peri_scribe.perimeters.border_classification.source_kind_for_feed_name(
            "WFIGS_Interagency_Perimeters_Current_0",
        )
        is tests.peri_scribe.perimeters.border_helpers.WFIGS_PERIMETER
    )


def test_source_kind_for_feed_name_recognizes_wfigs_location() -> None:
    assert (
        peri_scribe.perimeters.border_classification.source_kind_for_feed_name(
            "WFIGS_Incident_Locations_Current_0",
        )
        is tests.peri_scribe.perimeters.border_helpers.WFIGS_LOCATION
    )


def test_source_kind_for_feed_name_rejects_unknown_source() -> None:
    with pytest.raises(ValueError, match="unknown fire source"):
        peri_scribe.perimeters.border_classification.source_kind_for_feed_name(
            "Other_Source_0",
        )


def test_snapshot_serial_number_parses_leading_serial() -> None:
    path = pathlib.Path("000012,lastEdit=1786990894028.gpkg")
    expected_serial_number = 12
    assert (
        peri_scribe.perimeters.border_classification.snapshot_serial_number(path)
        == expected_serial_number
    )


def test_reproject_to_california_albers_returns_projected_geometry() -> None:
    point = shapely.geometry.Point(-120.0, 39.0)
    result = (
        peri_scribe.perimeters.border_classification.reproject_to_california_albers(
            point,
            4326,
        )
    )
    assert isinstance(result, shapely.geometry.Point)
    assert result != point


def test_reproject_to_california_albers_preserves_z_coordinates() -> None:
    point = shapely.geometry.Point(-120.0, 39.0, 123.0)
    result = (
        peri_scribe.perimeters.border_classification.reproject_to_california_albers(
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
        peri_scribe.sources.administrative_boundaries,
        "load_border_geometry",
        lambda _base_dir: CA_BORDER_WGS84,
    )
    monkeypatch.setattr(
        peri_scribe.sources.borders,
        "california_box_polygon",
        lambda _border: CALIFORNIA_BOX_WGS84,
    )
    loaded = peri_scribe.perimeters.border_classification.load_boundaries(
        pathlib.Path("/base"),
    )
    assert isinstance(loaded.box, shapely.geometry.Polygon)
    assert isinstance(loaded.border, shapely.geometry.LineString)


def test_union_geometry_returns_none_without_geometries(
    boundaries: peri_scribe.perimeters.border_classification.Boundaries,
) -> None:
    assert (
        peri_scribe.perimeters.border_classification.union_geometry(
            [],
            boundaries,
        )
        is None
    )


def test_union_geometry_skips_missing_and_empty_geometries(
    boundaries: peri_scribe.perimeters.border_classification.Boundaries,
) -> None:
    observations = [
        tests.peri_scribe.perimeters.border_helpers.observation(
            tests.peri_scribe.perimeters.border_helpers.FIRIS,
            shapely.geometry.Point(-120.0, 39.0),
        ),
        tests.peri_scribe.perimeters.border_helpers.observation(
            tests.peri_scribe.perimeters.border_helpers.WFIGS_PERIMETER,
            None,
        ),
        tests.peri_scribe.perimeters.border_helpers.observation(
            tests.peri_scribe.perimeters.border_helpers.WFIGS_LOCATION,
            shapely.geometry.Polygon(),
        ),
    ]
    union = peri_scribe.perimeters.border_classification.union_geometry(
        observations,
        boundaries,
    )
    assert isinstance(union, shapely.geometry.Point)


def test_union_geometry_returns_single_geometry_directly(
    boundaries: peri_scribe.perimeters.border_classification.Boundaries,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    location = shapely.geometry.Point(-120.0, 39.0)
    monkeypatch.setattr(
        shapely,
        "union_all",
        lambda _geometries: pytest.fail("union_all must not be called"),
    )
    union = peri_scribe.perimeters.border_classification.union_geometry(
        [
            tests.peri_scribe.perimeters.border_helpers.observation(
                tests.peri_scribe.perimeters.border_helpers.FIRIS,
                location,
            ),
        ],
        boundaries,
    )
    assert union == (
        peri_scribe.perimeters.border_classification.reproject_to_california_albers(
            location,
            peri_scribe.models.NAD83_SPATIAL_REFERENCE_ID,
        )
    )


def test_union_geometry_dedupes_identical_observations(
    boundaries: peri_scribe.perimeters.border_classification.Boundaries,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # One observation inside the California box and one outside, so the parts
    # straddle the box and the true union is needed.
    inside = shapely.geometry.Point(5.0, 5.0)
    outside = shapely.geometry.Point(200.0, 200.0)
    distinct_geometry_count = 2
    union_inputs: list[list[shapely.Geometry]] = []
    original_union_all = shapely.union_all

    def recording_union_all(geometries: list[shapely.Geometry]) -> shapely.Geometry:
        union_inputs.append(list(geometries))
        return original_union_all(geometries)

    monkeypatch.setattr(shapely, "union_all", recording_union_all)
    monkeypatch.setattr(
        peri_scribe.perimeters.border_classification,
        "reproject_to_california_albers",
        lambda geometry, _wkid: geometry,
    )
    union = peri_scribe.perimeters.border_classification.union_geometry(
        [
            tests.peri_scribe.perimeters.border_helpers.observation(
                tests.peri_scribe.perimeters.border_helpers.FIRIS,
                inside,
            ),
            tests.peri_scribe.perimeters.border_helpers.observation(
                tests.peri_scribe.perimeters.border_helpers.FIRIS,
                inside,
            ),
            tests.peri_scribe.perimeters.border_helpers.observation(
                tests.peri_scribe.perimeters.border_helpers.FIRIS,
                outside,
            ),
        ],
        boundaries,
    )
    assert isinstance(union, shapely.geometry.MultiPoint)
    assert len(union.geoms) == distinct_geometry_count
    assert [len(inputs) for inputs in union_inputs] == [distinct_geometry_count]


def test_union_geometry_skips_union_for_one_sided_fire(
    boundaries: peri_scribe.perimeters.border_classification.Boundaries,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        peri_scribe.perimeters.border_classification,
        "reproject_to_california_albers",
        lambda geometry, _wkid: geometry,
    )
    monkeypatch.setattr(
        shapely,
        "union_all",
        lambda _geometries: pytest.fail("union_all must not be called"),
    )
    union = peri_scribe.perimeters.border_classification.union_geometry(
        [
            tests.peri_scribe.perimeters.border_helpers.observation(
                tests.peri_scribe.perimeters.border_helpers.FIRIS,
                shapely.geometry.box(1.0, 1.0, 2.0, 2.0),
            ),
            tests.peri_scribe.perimeters.border_helpers.observation(
                tests.peri_scribe.perimeters.border_helpers.FIRIS,
                shapely.geometry.box(1.0, 1.0, 2.0, 2.0),
            ),
            tests.peri_scribe.perimeters.border_helpers.observation(
                tests.peri_scribe.perimeters.border_helpers.FIRIS,
                shapely.geometry.box(3.0, 3.0, 4.0, 4.0),
            ),
            tests.peri_scribe.perimeters.border_helpers.observation(
                tests.peri_scribe.perimeters.border_helpers.FIRIS,
                shapely.geometry.Point(5.0, 5.0),
            ),
        ],
        boundaries,
    )
    assert isinstance(union, shapely.geometry.GeometryCollection)
    distinct_geometry_count = 3
    assert len(union.geoms) == distinct_geometry_count


def test_union_geometry_keeps_identical_geometries_from_different_sources(
    boundaries: peri_scribe.perimeters.border_classification.Boundaries,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    location = shapely.geometry.Point(5.0, 5.0)
    reprojected: list[tuple[int, bytes]] = []
    original = (
        peri_scribe.perimeters.border_classification.reproject_to_california_albers
    )

    def recording_reproject(geometry: shapely.Geometry, wkid: int) -> shapely.Geometry:
        reprojected.append((wkid, geometry.wkb))
        return original(geometry, wkid)

    monkeypatch.setattr(
        peri_scribe.perimeters.border_classification,
        "reproject_to_california_albers",
        recording_reproject,
    )
    union = peri_scribe.perimeters.border_classification.union_geometry(
        [
            tests.peri_scribe.perimeters.border_helpers.observation(
                tests.peri_scribe.perimeters.border_helpers.FIRIS,
                location,
            ),
            tests.peri_scribe.perimeters.border_helpers.observation(
                tests.peri_scribe.perimeters.border_helpers.WFIGS_PERIMETER,
                location,
            ),
        ],
        boundaries,
    )
    assert isinstance(union, shapely.geometry.GeometryCollection)
    # The identical geometry from each source is re-projected separately, so the
    # deduplication is keyed on the source as well as the geometry.
    source_count = 2
    assert len(reprojected) == source_count
    assert reprojected[0][0] != reprojected[1][0]


def test_classify_crosses_border() -> None:
    geometry = tests.peri_scribe.perimeters.border_helpers.geometry_signal(
        distance_to_boundary_in_meters=0.0,
        outside_area_fraction=0.5,
        outside_area_in_acres=100.0,
        inside_area_fraction=0.5,
        crosses=True,
        near=True,
    )
    extent = tests.peri_scribe.perimeters.border_helpers.extent_signal()
    result = peri_scribe.perimeters.border_classification.classify(
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
    geometry = tests.peri_scribe.perimeters.border_helpers.geometry_signal(
        distance_to_boundary_in_meters=5.0,
        near=True,
    )
    extent = tests.peri_scribe.perimeters.border_helpers.extent_signal()
    result = peri_scribe.perimeters.border_classification.classify(
        geometry=geometry,
        extent=extent,
        identifier=False,
    )
    assert (
        result.classification
        is peri_scribe.models.BorderClassification.INSIDE_CALIFORNIA_NEAR_BORDER
    )


def test_classify_inside_near_border_from_extent_disagreement() -> None:
    geometry = tests.peri_scribe.perimeters.border_helpers.geometry_signal()
    extent = tests.peri_scribe.perimeters.border_helpers.extent_signal(
        wfigs_to_firis_area_ratio=1.5,
        disagrees=True,
    )
    result = peri_scribe.perimeters.border_classification.classify(
        geometry=geometry,
        extent=extent,
        identifier=False,
    )
    assert (
        result.classification
        is peri_scribe.models.BorderClassification.INSIDE_CALIFORNIA_NEAR_BORDER
    )


def test_classify_outside_near_border_from_geometry() -> None:
    geometry = tests.peri_scribe.perimeters.border_helpers.geometry_signal(
        distance_to_boundary_in_meters=2.0,
        outside_area_fraction=1.0,
        outside_area_in_acres=5000.0,
        inside_area_fraction=0.0,
        near=True,
        inside=False,
    )
    extent = tests.peri_scribe.perimeters.border_helpers.extent_signal()
    result = peri_scribe.perimeters.border_classification.classify(
        geometry=geometry,
        extent=extent,
        identifier=False,
    )
    assert (
        result.classification
        is peri_scribe.models.BorderClassification.OUTSIDE_CALIFORNIA_NEAR_BORDER
    )


def test_classify_inside_california() -> None:
    geometry = tests.peri_scribe.perimeters.border_helpers.geometry_signal()
    extent = tests.peri_scribe.perimeters.border_helpers.extent_signal()
    result = peri_scribe.perimeters.border_classification.classify(
        geometry=geometry,
        extent=extent,
        identifier=False,
    )
    assert (
        result.classification
        is peri_scribe.models.BorderClassification.INSIDE_CALIFORNIA
    )


def test_classify_outside_california() -> None:
    geometry = tests.peri_scribe.perimeters.border_helpers.geometry_signal(
        distance_to_boundary_in_meters=2000.0,
        inside_area_fraction=0.0,
        inside=False,
    )
    extent = tests.peri_scribe.perimeters.border_helpers.extent_signal()
    result = peri_scribe.perimeters.border_classification.classify(
        geometry=geometry,
        extent=extent,
        identifier=False,
    )
    assert (
        result.classification
        is peri_scribe.models.BorderClassification.OUTSIDE_CALIFORNIA
    )


def test_classify_identifier_alone_stays_inside_california() -> None:
    geometry = tests.peri_scribe.perimeters.border_helpers.geometry_signal()
    extent = tests.peri_scribe.perimeters.border_helpers.extent_signal()
    result = peri_scribe.perimeters.border_classification.classify(
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
    wgs84_boundaries: peri_scribe.perimeters.border_classification.Boundaries,
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
    result = peri_scribe.perimeters.border_classification.classify_fire(
        records=records,
        record_paths=record_paths,
        boundaries=wgs84_boundaries,
    )
    assert (
        result.classification
        is peri_scribe.models.BorderClassification.CROSSES_CALIFORNIA_BORDER
    )


def test_classify_fire_classifies_inside_california_fire(
    wgs84_boundaries: peri_scribe.perimeters.border_classification.Boundaries,
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
    result = peri_scribe.perimeters.border_classification.classify_fire(
        records=records,
        record_paths=record_paths,
        boundaries=wgs84_boundaries,
    )
    assert (
        result.classification
        is peri_scribe.models.BorderClassification.INSIDE_CALIFORNIA
    )


def test_classify_fire_classifies_outside_california_fire(
    wgs84_boundaries: peri_scribe.perimeters.border_classification.Boundaries,
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
    result = peri_scribe.perimeters.border_classification.classify_fire(
        records=records,
        record_paths=record_paths,
        boundaries=wgs84_boundaries,
    )
    assert (
        result.classification
        is peri_scribe.models.BorderClassification.OUTSIDE_CALIFORNIA
    )


def test_classify_fire_captures_identifier_signal(
    wgs84_boundaries: peri_scribe.perimeters.border_classification.Boundaries,
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
    result = peri_scribe.perimeters.border_classification.classify_fire(
        records=records,
        record_paths=record_paths,
        boundaries=wgs84_boundaries,
    )
    assert peri_scribe.models.BorderSignal.IDENTIFIER_UNIT in result.signals


def test_classify_fire_keeps_coastal_fire_inside(
    wgs84_boundaries: peri_scribe.perimeters.border_classification.Boundaries,
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
    result = peri_scribe.perimeters.border_classification.classify_fire(
        records=records,
        record_paths=record_paths,
        boundaries=wgs84_boundaries,
    )
    assert (
        result.classification
        is peri_scribe.models.BorderClassification.INSIDE_CALIFORNIA
    )
