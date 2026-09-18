"""Tests for peri_scribe.perimeters.border_classification."""

from __future__ import annotations

import datetime
import pathlib

import pytest
import shapely.geometry

import peri_scribe.models
import peri_scribe.perimeters.border_classification
import peri_scribe.perimeters.classification_data
import peri_scribe.sources.administrative_boundaries
import peri_scribe.sources.borders
import tests.helpers.assertions.peri_scribe.perimeters.classification
import tests.helpers.doubles.peri_scribe.perimeters.classification
import tests.helpers.factories.peri_scribe.perimeters.classification
import tests.helpers.factories.peri_scribe.perimeters.signals
import tests.helpers.reference.peri_scribe.perimeters.classification
from peri_scribe.units import units


@pytest.mark.parametrize(
    ("shapes", "order"),
    tests.helpers.factories.peri_scribe.perimeters.classification.overlapping_observation_cases(),
    ids=[
        "overlap-across-hole",
        "repeated-overlap",
        "touching-holes-with-repeated-mapping",
    ],
)
def test_unioned_observation_geometry_preserves_overlapping_and_repeated_parts(
    shapes: list[shapely.Geometry],
    order: tuple[int, ...],
) -> None:
    observations = [
        tests.helpers.factories.peri_scribe.perimeters.signals.observation(
            tests.helpers.factories.peri_scribe.perimeters.signals.FIRIS,
            shapes[index],
            serial_number=serial,
        )
        for serial, index in enumerate(order)
    ]
    actual = peri_scribe.perimeters.border_classification.unioned_observation_geometry(
        observations,
        tests.helpers.factories.peri_scribe.perimeters.classification.projected_boundaries(),
    )
    expected = (
        tests.helpers.reference.peri_scribe.perimeters.classification
    ).full_projected_union(
        observations,
    )
    assert actual is not None
    assert expected is not None
    tests.helpers.assertions.peri_scribe.perimeters.classification.assert_same_projected_coverage(
        actual,
        expected,
    )


@pytest.mark.parametrize(
    "shapes",
    tests.helpers.factories.peri_scribe.perimeters.classification.overlapping_hole_observation_cases(),
    ids=["identical-repeats", "different-ring-encodings"],
)
def test_unioned_observation_geometry_preserves_gap_between_touching_holes(
    shapes: list[shapely.Polygon],
) -> None:
    observations = [
        tests.helpers.factories.peri_scribe.perimeters.signals.observation(
            tests.helpers.factories.peri_scribe.perimeters.signals.FIRIS,
            shape,
            serial_number=serial,
        )
        for serial, shape in enumerate(shapes)
    ]
    actual = peri_scribe.perimeters.border_classification.unioned_observation_geometry(
        observations,
        tests.helpers.factories.peri_scribe.perimeters.classification.projected_boundaries(),
    )
    reference = (
        tests.helpers.reference.peri_scribe.perimeters.classification
    ).full_projected_union(observations)
    gap = shapely.Point(157639.4796050014, -55831.13224623485)
    assert actual is not None
    assert reference is not None
    assert not actual.covers(gap)
    assert not reference.covers(gap)


def test_source_kind_for_feed_name_recognizes_firis() -> None:
    assert (
        peri_scribe.perimeters.border_classification.source_kind_for_feed_name(
            "CA_Perimeters_NIFC_FIRIS_public_view_0",
        )
        is tests.helpers.factories.peri_scribe.perimeters.signals.FIRIS
    )


def test_source_kind_for_feed_name_recognizes_wfigs_perimeter() -> None:
    assert (
        peri_scribe.perimeters.border_classification.source_kind_for_feed_name(
            "WFIGS_Interagency_Perimeters_Current_0",
        )
        is tests.helpers.factories.peri_scribe.perimeters.signals.WFIGS_PERIMETER
    )


def test_source_kind_for_feed_name_recognizes_wfigs_location() -> None:
    assert (
        peri_scribe.perimeters.border_classification.source_kind_for_feed_name(
            "WFIGS_Incident_Locations_Current_0",
        )
        is tests.helpers.factories.peri_scribe.perimeters.signals.WFIGS_LOCATION
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


def test_load_boundaries_builds_box_and_reprojects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        peri_scribe.sources.administrative_boundaries,
        "load_border_geometry",
        lambda _base_dir: (
            tests.helpers.factories.peri_scribe.perimeters.classification.CA_BORDER_WGS84
        ),
    )
    monkeypatch.setattr(
        peri_scribe.sources.borders,
        "california_box_polygon",
        lambda _border: (
            tests.helpers.factories.peri_scribe.perimeters.classification.CALIFORNIA_BOX_WGS84
        ),
    )
    loaded = peri_scribe.perimeters.border_classification.load_boundaries(
        pathlib.Path("/base"),
    )
    assert isinstance(loaded.box, shapely.geometry.Polygon)
    assert isinstance(loaded.border, shapely.geometry.LineString)


def test_unioned_observation_geometry_returns_none_without_geometries(
    boundaries: peri_scribe.perimeters.classification_data.Boundaries,
) -> None:
    assert (
        peri_scribe.perimeters.border_classification.unioned_observation_geometry(
            [],
            boundaries,
        )
        is None
    )


def test_unioned_observation_geometry_skips_missing_and_empty_geometries(
    boundaries: peri_scribe.perimeters.classification_data.Boundaries,
) -> None:
    observations = [
        tests.helpers.factories.peri_scribe.perimeters.signals.observation(
            tests.helpers.factories.peri_scribe.perimeters.signals.FIRIS,
            shapely.geometry.Point(-120.0, 39.0),
        ),
        tests.helpers.factories.peri_scribe.perimeters.signals.observation(
            tests.helpers.factories.peri_scribe.perimeters.signals.WFIGS_PERIMETER,
            None,
        ),
        tests.helpers.factories.peri_scribe.perimeters.signals.observation(
            tests.helpers.factories.peri_scribe.perimeters.signals.WFIGS_LOCATION,
            shapely.geometry.Polygon(),
        ),
    ]
    union = peri_scribe.perimeters.border_classification.unioned_observation_geometry(
        observations,
        boundaries,
    )
    assert isinstance(union, shapely.geometry.Point)


def test_unioned_observation_geometry_returns_single_geometry_directly(
    boundaries: peri_scribe.perimeters.classification_data.Boundaries,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    location = shapely.geometry.Point(-120.0, 39.0)
    monkeypatch.setattr(
        shapely,
        "union_all",
        lambda _geometries: pytest.fail("union_all must not be called"),
    )
    union = peri_scribe.perimeters.border_classification.unioned_observation_geometry(
        [
            tests.helpers.factories.peri_scribe.perimeters.signals.observation(
                tests.helpers.factories.peri_scribe.perimeters.signals.FIRIS,
                location,
            ),
        ],
        boundaries,
    )
    assert union == (
        peri_scribe.perimeters.classification_data.reproject_to_california_albers(
            location,
            peri_scribe.models.NAD83_SPATIAL_REFERENCE_ID,
        )
    )


def test_unioned_observation_geometry_dedupes_identical_observations(
    boundaries: peri_scribe.perimeters.classification_data.Boundaries,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # One observation inside the California box and one outside, so the parts straddle
    # the box and the true union is needed.
    inside = shapely.geometry.Point(5.0, 5.0)
    outside = shapely.geometry.Point(200.0, 200.0)
    distinct_geometry_count = 2
    union_inputs: list[list[shapely.Geometry]] = []
    original_union_all = shapely.union_all

    recording_union_all = (
        tests.helpers.doubles.peri_scribe.perimeters.classification.make_union_recorder(
            union_inputs=union_inputs,
            original_union_all=original_union_all,
        )
    )

    monkeypatch.setattr(shapely, "union_all", recording_union_all)
    monkeypatch.setattr(
        peri_scribe.perimeters.classification_data,
        "reproject_to_california_albers",
        lambda geometry, _wkid: geometry,
    )
    union = peri_scribe.perimeters.border_classification.unioned_observation_geometry(
        [
            tests.helpers.factories.peri_scribe.perimeters.signals.observation(
                tests.helpers.factories.peri_scribe.perimeters.signals.FIRIS,
                inside,
            ),
            tests.helpers.factories.peri_scribe.perimeters.signals.observation(
                tests.helpers.factories.peri_scribe.perimeters.signals.FIRIS,
                inside,
            ),
            tests.helpers.factories.peri_scribe.perimeters.signals.observation(
                tests.helpers.factories.peri_scribe.perimeters.signals.FIRIS,
                outside,
            ),
        ],
        boundaries,
    )
    assert isinstance(union, shapely.geometry.MultiPoint)
    assert len(union.geoms) == distinct_geometry_count
    assert [len(inputs) for inputs in union_inputs] == [distinct_geometry_count]


def test_unioned_observation_geometry_skips_union_for_one_sided_fire(
    boundaries: peri_scribe.perimeters.classification_data.Boundaries,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        peri_scribe.perimeters.classification_data,
        "reproject_to_california_albers",
        lambda geometry, _wkid: geometry,
    )
    monkeypatch.setattr(
        shapely,
        "union_all",
        lambda _geometries: pytest.fail("union_all must not be called"),
    )
    union = peri_scribe.perimeters.border_classification.unioned_observation_geometry(
        [
            tests.helpers.factories.peri_scribe.perimeters.signals.observation(
                tests.helpers.factories.peri_scribe.perimeters.signals.FIRIS,
                shapely.geometry.box(1.0, 1.0, 2.0, 2.0),
            ),
            tests.helpers.factories.peri_scribe.perimeters.signals.observation(
                tests.helpers.factories.peri_scribe.perimeters.signals.FIRIS,
                shapely.geometry.box(1.0, 1.0, 2.0, 2.0),
            ),
            tests.helpers.factories.peri_scribe.perimeters.signals.observation(
                tests.helpers.factories.peri_scribe.perimeters.signals.FIRIS,
                shapely.geometry.box(3.0, 3.0, 4.0, 4.0),
            ),
            tests.helpers.factories.peri_scribe.perimeters.signals.observation(
                tests.helpers.factories.peri_scribe.perimeters.signals.FIRIS,
                shapely.geometry.Point(5.0, 5.0),
            ),
        ],
        boundaries,
    )
    assert isinstance(union, shapely.geometry.GeometryCollection)
    distinct_geometry_count = 3
    assert len(union.geoms) == distinct_geometry_count


def test_unioned_observation_geometry_keeps_identical_geometries_from_different_sources(
    boundaries: peri_scribe.perimeters.classification_data.Boundaries,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    location = shapely.geometry.Point(5.0, 5.0)
    reprojected: list[tuple[int, bytes]] = []
    original = peri_scribe.perimeters.classification_data.reproject_to_california_albers

    monkeypatch.setattr(
        peri_scribe.perimeters.classification_data,
        "reproject_to_california_albers",
        tests.helpers.doubles.peri_scribe.perimeters.classification.make_reproject_recorder(
            reprojected=reprojected,
            original=original,
        ),
    )
    union = peri_scribe.perimeters.border_classification.unioned_observation_geometry(
        [
            tests.helpers.factories.peri_scribe.perimeters.signals.observation(
                tests.helpers.factories.peri_scribe.perimeters.signals.FIRIS,
                location,
            ),
            tests.helpers.factories.peri_scribe.perimeters.signals.observation(
                tests.helpers.factories.peri_scribe.perimeters.signals.WFIGS_PERIMETER,
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
    geometry = tests.helpers.factories.peri_scribe.perimeters.signals.geometry_signal(
        distance_to_boundary=0.0,
        outside_area_fraction=0.5,
        outside_area=100.0,
        inside_area_fraction=0.5,
        crosses=True,
        near=True,
    )
    extent = tests.helpers.factories.peri_scribe.perimeters.signals.extent_signal()
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
    geometry = tests.helpers.factories.peri_scribe.perimeters.signals.geometry_signal(
        distance_to_boundary=5.0,
        near=True,
    )
    extent = tests.helpers.factories.peri_scribe.perimeters.signals.extent_signal()
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
    geometry = tests.helpers.factories.peri_scribe.perimeters.signals.geometry_signal()
    extent = tests.helpers.factories.peri_scribe.perimeters.signals.extent_signal(
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
    geometry = tests.helpers.factories.peri_scribe.perimeters.signals.geometry_signal(
        distance_to_boundary=2.0,
        outside_area_fraction=1.0,
        outside_area=5_000.0,
        inside_area_fraction=0.0,
        near=True,
        inside=False,
    )
    extent = tests.helpers.factories.peri_scribe.perimeters.signals.extent_signal()
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
    geometry = tests.helpers.factories.peri_scribe.perimeters.signals.geometry_signal()
    extent = tests.helpers.factories.peri_scribe.perimeters.signals.extent_signal()
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
    geometry = tests.helpers.factories.peri_scribe.perimeters.signals.geometry_signal(
        distance_to_boundary=2_000.0,
        inside_area_fraction=0.0,
        inside=False,
    )
    extent = tests.helpers.factories.peri_scribe.perimeters.signals.extent_signal()
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
    geometry = tests.helpers.factories.peri_scribe.perimeters.signals.geometry_signal()
    extent = tests.helpers.factories.peri_scribe.perimeters.signals.extent_signal()
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
    wgs84_boundaries: peri_scribe.perimeters.classification_data.Boundaries,
) -> None:
    records = [
        tests.helpers.factories.peri_scribe.perimeters.classification.classifiable_record(
            geometry=shapely.geometry.box(-120.5, 39.0, -118.5, 39.5),
            observed_at=datetime.datetime(2026, 8, 16, tzinfo=datetime.UTC),
        ),
    ]
    record_paths = [
        pathlib.Path(
            "sources/CA_Perimeters_NIFC_FIRIS_public_view_0/"
            "000___/000000,lastEdit=0.gpkg",
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
    wgs84_boundaries: peri_scribe.perimeters.classification_data.Boundaries,
) -> None:
    records = [
        tests.helpers.factories.peri_scribe.perimeters.classification.classifiable_record(
            geometry=shapely.geometry.box(-120.5, 39.0, -120.0, 39.5),
            observed_at=datetime.datetime(2026, 8, 16, tzinfo=datetime.UTC),
        ),
    ]
    record_paths = [
        pathlib.Path(
            "sources/CA_Perimeters_NIFC_FIRIS_public_view_0/"
            "000___/000000,lastEdit=0.gpkg",
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


@pytest.mark.parametrize(
    ("buffer_kilometers", "expected"),
    [
        (1, peri_scribe.models.BorderClassification.INSIDE_CALIFORNIA),
        (200, peri_scribe.models.BorderClassification.INSIDE_CALIFORNIA_NEAR_BORDER),
    ],
)
def test_classify_fire_respects_configured_border_buffer(
    wgs84_boundaries: peri_scribe.perimeters.classification_data.Boundaries,
    buffer_kilometers: int,
    expected: peri_scribe.models.BorderClassification,
) -> None:
    records = [
        tests.helpers.factories.peri_scribe.perimeters.classification.classifiable_record(
            geometry=shapely.geometry.box(-120.5, 39.0, -120.0, 39.5),
        ),
    ]
    result = peri_scribe.perimeters.border_classification.classify_fire(
        records=records,
        record_paths=[
            pathlib.Path(
                "sources/WFIGS_Interagency_Perimeters_Current_0/"
                "000___/000000,lastEdit=0.gpkg",
            ),
        ],
        boundaries=wgs84_boundaries,
        config=peri_scribe.perimeters.classification_data.BorderClassificationConfig(
            near_border_buffer=buffer_kilometers * units.km,
        ),
    )
    assert result.classification is expected


def test_classify_fire_classifies_outside_california_fire(
    wgs84_boundaries: peri_scribe.perimeters.classification_data.Boundaries,
) -> None:
    records = [
        tests.helpers.factories.peri_scribe.perimeters.classification.classifiable_record(
            geometry=shapely.geometry.box(-117.5, 39.0, -116.0, 39.5),
        ),
    ]
    record_paths = [
        pathlib.Path(
            "sources/WFIGS_Interagency_Perimeters_Current_0/"
            "000___/000000,lastEdit=0.gpkg",
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
    wgs84_boundaries: peri_scribe.perimeters.classification_data.Boundaries,
) -> None:
    records = [
        tests.helpers.factories.peri_scribe.perimeters.classification.classifiable_record(
            geometry=shapely.geometry.box(-120.5, 39.0, -120.0, 39.5),
            identifiers=frozenset({"2026-nvccd-030683"}),
        ),
    ]
    record_paths = [
        pathlib.Path(
            "sources/CA_Perimeters_NIFC_FIRIS_public_view_0/"
            "000___/000000,lastEdit=0.gpkg",
        ),
    ]
    result = peri_scribe.perimeters.border_classification.classify_fire(
        records=records,
        record_paths=record_paths,
        boundaries=wgs84_boundaries,
    )
    assert peri_scribe.models.BorderSignal.IDENTIFIER_UNIT in result.signals


def test_classify_fire_keeps_coastal_fire_inside(
    wgs84_boundaries: peri_scribe.perimeters.classification_data.Boundaries,
) -> None:
    records = [
        tests.helpers.factories.peri_scribe.perimeters.classification.classifiable_record(
            geometry=shapely.geometry.box(-121.5, 39.0, -119.5, 39.5),
        ),
    ]
    record_paths = [
        pathlib.Path(
            "sources/CA_Perimeters_NIFC_FIRIS_public_view_0/"
            "000___/000000,lastEdit=0.gpkg",
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
