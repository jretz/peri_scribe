import datetime
import json
import pathlib

import geopandas
import numpy as np
import pytest
import shapely.geometry

import peri_scribe.california_border_classification
import peri_scribe.classification
import peri_scribe.fire_history
import peri_scribe.fire_sources
import peri_scribe.geo_data
import peri_scribe.models
import peri_scribe.output
import peri_scribe.snapshots
import tests.factories


ACTIVE = peri_scribe.models.FireStatus.ACTIVE

FIRIS_PERIMETER = (
    peri_scribe.california_border_classification.FireSourceKind.FIRIS_PERIMETER
)
WFIGS_PERIMETER = (
    peri_scribe.california_border_classification.FireSourceKind.WFIGS_PERIMETER
)
WFIGS_LOCATION = (
    peri_scribe.california_border_classification.FireSourceKind.WFIGS_LOCATION
)

FIRIS_FEED_NAME = "CA_Perimeters_NIFC_FIRIS_public_view_0"
WFIGS_LOCATION_FEED_NAME = "WFIGS_Incident_Locations_Current_0"

OUTPUT_WKID = 4326

ITEM_VALUE = 7


def polygon(*points: tuple[float, float]) -> shapely.geometry.Polygon:
    """Return a polygon from *points*.

    Args:
        points: The polygon's exterior points.

    Returns:
        The polygon.
    """
    return shapely.geometry.Polygon(points)


def point(x: float, y: float) -> shapely.geometry.Point:
    """Return a point at *x*, *y*.

    Args:
        x: The longitude.
        y: The latitude.

    Returns:
        The point.
    """
    return shapely.geometry.Point(x, y)


def observation(
    *,
    source_kind: peri_scribe.california_border_classification.FireSourceKind = (
        FIRIS_PERIMETER
    ),
    geometry: shapely.geometry.base.BaseGeometry | None = None,
    observation_time: datetime.datetime | None = None,
    snapshot_time: datetime.datetime | None = None,
    serial_number: int = 0,
    object_id: int | None = 1,
    source_file: str = "source.gpkg",
    attributes: dict[str, object] | None = None,
) -> peri_scribe.fire_history.SourceObservation:
    """Build a source observation for a test.

    Args:
        source_kind: The observation's source kind.
        geometry: The observation's geometry.
        observation_time: The mapping time.
        snapshot_time: The snapshot watermark time.
        serial_number: The snapshot serial number.
        object_id: The source row's OBJECTID.
        source_file: The source file path.
        attributes: The row's attributes.

    Returns:
        The observation.
    """
    return peri_scribe.fire_history.SourceObservation(
        source_kind=source_kind,
        geometry=geometry,
        observation_time=observation_time,
        snapshot_time=snapshot_time,
        serial_number=serial_number,
        object_id=object_id,
        source_file=source_file,
        attributes={} if attributes is None else attributes,
    )


def fire(
    name: str = "Bug",
    identifier: str | None = "2026-nvccd-030683",
) -> peri_scribe.models.Fire:
    """Build a fire for a test.

    Args:
        name: The fire's name.
        identifier: The fire's canonical identifier.

    Returns:
        The fire.
    """
    return peri_scribe.models.Fire(
        name=name,
        status=ACTIVE,
        identifier=identifier,
        aliases=frozenset({identifier}) if identifier is not None else frozenset(),
    )


def classification(
    kind: peri_scribe.models.BorderClassification,
) -> peri_scribe.models.FireClassification:
    """Build a border classification for a test.

    Args:
        kind: The classification kind.

    Returns:
        The classification.
    """
    return peri_scribe.models.FireClassification(
        classification=kind,
        distance_to_boundary_in_meters=0.0,
        outside_area_fraction=0.0,
        inside_area_fraction=0.0,
    )


def utc(
    year: int,
    month: int,
    day: int,
    hour: int,
    minute: int = 0,
    *,
    second: int = 0,
) -> datetime.datetime:
    """Return an aware UTC datetime.

    Args:
        year: The year.
        month: The month.
        day: The day.
        hour: The hour.
        minute: The minute.
        second: The second.

    Returns:
        The datetime.
    """
    return datetime.datetime(
        year,
        month,
        day,
        hour,
        minute,
        second,
        tzinfo=datetime.UTC,
    )


def test_watermark_time_from_returns_snapshot_time() -> None:
    path = pathlib.Path("000000,lastEdit=1786955463975.gpkg")
    expected = datetime.datetime.fromtimestamp(1786955463975 / 1000.0, tz=datetime.UTC)
    assert peri_scribe.fire_history.watermark_time_from(path) == expected


def test_watermark_time_from_returns_none_for_malformed_name() -> None:
    assert peri_scribe.fire_history.watermark_time_from(
        pathlib.Path("000000,no-time.gpkg"),
    ) is None


def test_watermark_time_from_returns_none_for_non_numeric_watermark() -> None:
    assert peri_scribe.fire_history.watermark_time_from(
        pathlib.Path("000000,lastEdit=soon.gpkg"),
    ) is None


def test_watermark_time_from_returns_none_without_comma() -> None:
    assert peri_scribe.fire_history.watermark_time_from(
        pathlib.Path("snapshot.gpkg"),
    ) is None


def test_effective_time_prefers_observation_time() -> None:
    mapping_time = utc(2026, 8, 16, 0, 10)
    snapshot_time = utc(2026, 8, 17, 1, 42)
    observed = observation(
        observation_time=mapping_time,
        snapshot_time=snapshot_time,
        attributes={"poly_DateCurrent": utc(2026, 8, 15, 22, 0)},
    )
    assert peri_scribe.fire_history.effective_time(observed) == mapping_time


def test_effective_time_falls_back_to_current_date_before_snapshot_time() -> None:
    current_date = utc(2026, 8, 16, 0, 10)
    snapshot_time = utc(2026, 8, 17, 1, 42)
    observed = observation(
        snapshot_time=snapshot_time,
        attributes={"poly_DateCurrent": current_date},
    )
    assert peri_scribe.fire_history.effective_time(observed) == current_date


def test_effective_time_falls_back_to_snapshot_time() -> None:
    snapshot_time = utc(2026, 8, 17, 1, 42)
    observed = observation(snapshot_time=snapshot_time)
    assert peri_scribe.fire_history.effective_time(observed) == snapshot_time


def test_perimeter_sort_key_orders_by_effective_time() -> None:
    earlier = observation(
        observation_time=utc(2026, 8, 16, 0, 10),
        serial_number=9,
    )
    later = observation(
        observation_time=utc(2026, 8, 16, 0, 11),
        serial_number=1,
    )
    assert peri_scribe.fire_history.perimeter_sort_key(earlier) < (
        peri_scribe.fire_history.perimeter_sort_key(later)
    )


def test_geometries_are_equal_compares_shapes() -> None:
    first = polygon((0, 0), (1, 0), (1, 1), (0, 0))
    second = polygon((0, 0), (1, 0), (1, 1), (0, 0))
    different = polygon((0, 0), (2, 0), (2, 1), (0, 0))
    assert peri_scribe.fire_history.geometries_are_equal(first, second)
    assert not peri_scribe.fire_history.geometries_are_equal(first, different)


def test_geometries_are_equal_treats_missing_geometries() -> None:
    assert peri_scribe.fire_history.geometries_are_equal(None, None)
    assert not peri_scribe.fire_history.geometries_are_equal(None, point(0, 0))


def test_geometries_are_equal_treats_empty_geometries() -> None:
    empty = shapely.geometry.Polygon()
    assert peri_scribe.fire_history.geometries_are_equal(empty, empty)
    assert not peri_scribe.fire_history.geometries_are_equal(empty, point(0, 0))


def test_collapse_identical_consecutive_perimeters_collapses_runs() -> None:
    geometry = polygon((0, 0), (1, 0), (1, 1), (0, 0))
    older = observation(
        geometry=geometry,
        observation_time=utc(2026, 8, 16, 0, 10),
        serial_number=0,
        attributes={"area_acres": 10},
    )
    newer = observation(
        geometry=geometry,
        observation_time=utc(2026, 8, 16, 0, 10),
        serial_number=1,
        attributes={"area_acres": 11},
    )
    versions = peri_scribe.fire_history.collapse_identical_consecutive_perimeters(
        [older, newer],
    )
    assert versions == [newer]


def test_collapse_identical_consecutive_perimeters_keeps_distinct_geometries() -> None:
    first = polygon((0, 0), (1, 0), (1, 1), (0, 0))
    second = polygon((0, 0), (2, 0), (2, 1), (0, 0))
    first_observation = observation(
        geometry=first,
        observation_time=utc(2026, 8, 16, 0, 10),
    )
    second_observation = observation(
        geometry=second,
        observation_time=utc(2026, 8, 16, 1, 10),
    )
    versions = peri_scribe.fire_history.collapse_identical_consecutive_perimeters(
        [first_observation, second_observation],
    )
    assert versions == [first_observation, second_observation]


def test_observations_are_contemporaneous_within_tolerance() -> None:
    left = observation(observation_time=utc(2026, 8, 16, 0, 10))
    right = observation(observation_time=utc(2026, 8, 16, 4, 10))
    assert peri_scribe.fire_history.observations_are_contemporaneous(left, right)


def test_observations_are_contemporaneous_beyond_tolerance() -> None:
    left = observation(observation_time=utc(2026, 8, 16, 0, 10))
    right = observation(observation_time=utc(2026, 8, 16, 4, 11))
    assert not peri_scribe.fire_history.observations_are_contemporaneous(left, right)


def test_observations_are_contemporaneous_with_missing_times() -> None:
    assert peri_scribe.fire_history.observations_are_contemporaneous(
        observation(),
        observation(),
    )
    assert not peri_scribe.fire_history.observations_are_contemporaneous(
        observation(observation_time=utc(2026, 8, 16, 0, 10)),
        observation(),
    )


def test_preferred_perimeter_source_prefers_wfigs_outside_california() -> None:
    kinds = [
        peri_scribe.models.BorderClassification.CROSSES_CALIFORNIA_BORDER,
        peri_scribe.models.BorderClassification.OUTSIDE_CALIFORNIA_NEAR_BORDER,
        peri_scribe.models.BorderClassification.OUTSIDE_CALIFORNIA,
    ]
    for kind in kinds:
        assert (
            peri_scribe.fire_history.preferred_perimeter_source(classification(kind))
            is WFIGS_PERIMETER
        )


def test_preferred_perimeter_source_prefers_firis_inside_california() -> None:
    kinds = [
        peri_scribe.models.BorderClassification.INSIDE_CALIFORNIA,
        peri_scribe.models.BorderClassification.INSIDE_CALIFORNIA_NEAR_BORDER,
    ]
    for kind in kinds:
        assert (
            peri_scribe.fire_history.preferred_perimeter_source(classification(kind))
            is FIRIS_PERIMETER
        )


def test_preferred_perimeter_source_defaults_to_firis() -> None:
    assert peri_scribe.fire_history.preferred_perimeter_source(None) is FIRIS_PERIMETER


def test_preferred_pair_returns_preferred_first() -> None:
    firis = observation(source_kind=FIRIS_PERIMETER)
    wfigs = observation(source_kind=WFIGS_PERIMETER)
    assert peri_scribe.fire_history.preferred_pair(
        firis,
        wfigs,
        FIRIS_PERIMETER,
    ) == (firis, wfigs)
    assert peri_scribe.fire_history.preferred_pair(
        firis,
        wfigs,
        WFIGS_PERIMETER,
    ) == (wfigs, firis)


def test_merge_observations_merges_attributes_winner_first() -> None:
    winner = observation(
        source_kind=WFIGS_PERIMETER,
        geometry=polygon((0, 0), (1, 0), (1, 1), (0, 0)),
        attributes={"area_acres": 100, "source": "NIFC"},
    )
    loser = observation(
        source_kind=FIRIS_PERIMETER,
        geometry=polygon((0, 0), (1, 0), (1, 1), (0, 0)),
        attributes={"area_acres": 99, "cost": 500},
    )
    merged = peri_scribe.fire_history.merge_observations(winner, loser)
    assert merged.source_kind is WFIGS_PERIMETER
    assert merged.attributes == {"area_acres": 100, "source": "NIFC", "cost": 500}


def test_merge_identical_observations_merges_matching_geometry() -> None:
    geometry = polygon((0, 0), (1, 0), (1, 1), (0, 0))
    firis = observation(
        source_kind=FIRIS_PERIMETER,
        geometry=geometry,
        observation_time=utc(2026, 8, 16, 0, 10),
        attributes={"area_acres": 100},
    )
    wfigs = observation(
        source_kind=WFIGS_PERIMETER,
        geometry=geometry,
        observation_time=utc(2026, 8, 16, 0, 10),
        attributes={"poly_GISAcres": 100, "attr_EstimatedCostToDate": 500},
    )
    merged = peri_scribe.fire_history.merge_identical_observations(
        [firis, wfigs],
        WFIGS_PERIMETER,
    )
    assert [version.source_kind for version in merged] == [WFIGS_PERIMETER]
    assert merged[0].attributes["area_acres"] == firis.attributes["area_acres"]
    assert (
        merged[0].attributes["attr_EstimatedCostToDate"]
        == wfigs.attributes["attr_EstimatedCostToDate"]
    )


def test_keep_preferred_in_window_drops_loser_when_both_sources_present() -> None:
    firis = observation(source_kind=FIRIS_PERIMETER)
    wfigs = observation(source_kind=WFIGS_PERIMETER)
    kept = peri_scribe.fire_history.keep_preferred_in_window(
        [firis, wfigs],
        WFIGS_PERIMETER,
    )
    assert kept == [wfigs]


def test_keep_preferred_in_window_keeps_single_source_window() -> None:
    firis = observation(source_kind=FIRIS_PERIMETER)
    kept = peri_scribe.fire_history.keep_preferred_in_window(
        [firis],
        WFIGS_PERIMETER,
    )
    assert kept == [firis]


def test_drop_losing_source_versions_drops_loser_in_window() -> None:
    firis = observation(
        source_kind=FIRIS_PERIMETER,
        observation_time=utc(2026, 7, 11, 21, 15),
    )
    wfigs = observation(
        source_kind=WFIGS_PERIMETER,
        observation_time=utc(2026, 7, 12, 0, 23),
    )
    kept = peri_scribe.fire_history.drop_losing_source_versions(
        [firis, wfigs],
        FIRIS_PERIMETER,
    )
    assert kept == [firis]


def test_reconcile_perimeter_versions_merges_identical_and_prefers_wfigs() -> None:
    early = polygon((0, 0), (1, 0), (1, 1), (0, 0))
    mid = polygon((0, 0), (2, 0), (2, 1), (0, 0))
    late = polygon((0, 0), (3, 0), (3, 1), (0, 0))
    firis_observations = [
        observation(
            geometry=early,
            observation_time=utc(2026, 8, 9, 1, 0),
            attributes={"area_acres": 100},
        ),
        observation(
            geometry=mid,
            observation_time=utc(2026, 8, 16, 0, 10),
            attributes={"area_acres": 200},
        ),
        observation(
            geometry=late,
            observation_time=utc(2026, 8, 18, 2, 14),
            attributes={"area_acres": 300},
        ),
    ]
    wfigs_observations = [
        observation(
            source_kind=WFIGS_PERIMETER,
            geometry=mid,
            observation_time=utc(2026, 8, 16, 0, 10),
            attributes={"poly_GISAcres": 200},
        ),
        observation(
            source_kind=WFIGS_PERIMETER,
            geometry=late,
            observation_time=utc(2026, 8, 18, 2, 14),
            attributes={"poly_GISAcres": 300},
        ),
    ]
    versions = peri_scribe.fire_history.reconcile_perimeter_versions(
        firis_observations,
        wfigs_observations,
        classification(
            peri_scribe.models.BorderClassification.CROSSES_CALIFORNIA_BORDER,
        ),
    )
    assert [version.source_kind for version in versions] == [
        FIRIS_PERIMETER,
        WFIGS_PERIMETER,
        WFIGS_PERIMETER,
    ]


def test_reconcile_perimeter_versions_prefers_firis_for_inside_near() -> None:
    first = polygon((0, 0), (1, 0), (1, 1), (0, 0))
    second = polygon((0, 0), (2, 0), (2, 1), (0, 0))
    wfigs_geometry = polygon((0, 0), (3, 0), (3, 1), (0, 0))
    firis_observations = [
        observation(geometry=first, observation_time=utc(2026, 7, 11, 21, 15)),
        observation(geometry=second, observation_time=utc(2026, 7, 11, 21, 32)),
    ]
    wfigs_observations = [
        observation(
            source_kind=WFIGS_PERIMETER,
            geometry=wfigs_geometry,
            observation_time=utc(2026, 7, 12, 0, 23),
        ),
    ]
    versions = peri_scribe.fire_history.reconcile_perimeter_versions(
        firis_observations,
        wfigs_observations,
        classification(
            peri_scribe.models.BorderClassification.INSIDE_CALIFORNIA_NEAR_BORDER,
        ),
    )
    assert [version.source_kind for version in versions] == [
        FIRIS_PERIMETER,
        FIRIS_PERIMETER,
    ]


def test_geometry_area_in_acres_returns_area_for_polygon() -> None:
    geometry = polygon((0, 0), (1, 0), (1, 1), (0, 0))
    area = peri_scribe.fire_history.geometry_area_in_acres(geometry)
    assert area is not None
    assert area > 0


def test_geometry_area_in_acres_returns_none_without_geometry() -> None:
    assert peri_scribe.fire_history.geometry_area_in_acres(None) is None
    assert (
        peri_scribe.fire_history.geometry_area_in_acres(
            shapely.geometry.Polygon(),
        )
        is None
    )


def test_computed_area_in_acres_returns_first_positive_value() -> None:
    area = peri_scribe.fire_history.computed_area_in_acres(
        {"poly_Acres_AutoCalc": 123, "poly_GISAcres": 456, "area_acres": 789},
    )
    assert area == pytest.approx(123)


def test_computed_area_in_acres_skips_missing_and_nonpositive() -> None:
    area = peri_scribe.fire_history.computed_area_in_acres(
        {"poly_Acres_AutoCalc": 0, "poly_GISAcres": None, "area_acres": 456},
    )
    assert area == pytest.approx(456)


def test_computed_area_in_acres_returns_none_without_sizes() -> None:
    assert peri_scribe.fire_history.computed_area_in_acres({}) is None


def test_incident_size_in_acres_returns_first_positive_value() -> None:
    size = peri_scribe.fire_history.incident_size_in_acres(
        {"attr_IncidentSize": 100, "attr_FinalAcres": 200},
    )
    assert size == pytest.approx(100)


def test_incident_size_in_acres_skips_missing_and_nonpositive() -> None:
    size = peri_scribe.fire_history.incident_size_in_acres(
        {"attr_IncidentSize": np.nan, "attr_FinalAcres": 200},
    )
    assert size == pytest.approx(200)


def test_incident_size_in_acres_returns_none_without_sizes() -> None:
    assert peri_scribe.fire_history.incident_size_in_acres({}) is None


def test_perimeter_is_implausibly_small_flags_collapsed_geometry() -> None:
    tiny = polygon((0, 0), (0.0001, 0), (0.0001, 0.0001), (0, 0))
    version = observation(geometry=tiny, attributes={"area_acres": 1000})
    assert peri_scribe.fire_history.perimeter_is_implausibly_small(version)


def test_perimeter_is_implausibly_small_flags_small_incident_size() -> None:
    tiny = polygon((0, 0), (0.0001, 0), (0.0001, 0.0001), (0, 0))
    version = observation(geometry=tiny, attributes={"attr_IncidentSize": 100_000})
    assert peri_scribe.fire_history.perimeter_is_implausibly_small(version)


def test_perimeter_is_implausibly_small_keeps_matching_geometry() -> None:
    large = polygon((0, 0), (1, 0), (1, 1), (0, 0))
    version = observation(geometry=large, attributes={"area_acres": 3_000_000})
    assert not peri_scribe.fire_history.perimeter_is_implausibly_small(version)


def test_perimeter_is_implausibly_small_keeps_incident_running_ahead() -> None:
    medium = polygon((0, 0), (0.01, 0), (0.01, 0.01), (0, 0))
    version = observation(geometry=medium, attributes={"attr_IncidentSize": 4000})
    assert not peri_scribe.fire_history.perimeter_is_implausibly_small(version)


def test_perimeter_is_implausibly_small_keeps_without_reported_size() -> None:
    tiny = polygon((0, 0), (0.0001, 0), (0.0001, 0.0001), (0, 0))
    version = observation(geometry=tiny, attributes={})
    assert not peri_scribe.fire_history.perimeter_is_implausibly_small(version)


def test_perimeter_is_implausibly_small_keeps_without_geometry() -> None:
    version = observation(geometry=None, attributes={"area_acres": 1000})
    assert not peri_scribe.fire_history.perimeter_is_implausibly_small(version)


def test_drop_implausibly_small_perimeters_drops_collapsed() -> None:
    tiny = polygon((0, 0), (0.0001, 0), (0.0001, 0.0001), (0, 0))
    large = polygon((0, 0), (1, 0), (1, 1), (0, 0))
    observations = [
        observation(geometry=large, attributes={"area_acres": 3_000_000}),
        observation(geometry=tiny, attributes={"area_acres": 1000}),
    ]
    survivors = peri_scribe.fire_history.drop_implausibly_small_perimeters(
        observations,
    )
    assert survivors == [observations[0]]


def test_attributes_are_equal_compares_keys_and_values() -> None:
    assert peri_scribe.fire_history.attributes_are_equal(
        {"a": 1, "b": 2},
        {"a": 1, "b": 2},
    )
    assert not peri_scribe.fire_history.attributes_are_equal(
        {"a": 1},
        {"a": 1, "b": 2},
    )
    assert not peri_scribe.fire_history.attributes_are_equal(
        {"a": 1},
        {"a": 2},
    )


def test_point_versions_folds_geometry_move() -> None:
    first = observation(
        source_kind=WFIGS_LOCATION,
        geometry=point(0, 0),
        snapshot_time=utc(2026, 8, 17, 1, 0),
        serial_number=0,
        attributes={"IncidentSize": 100},
    )
    moved = observation(
        source_kind=WFIGS_LOCATION,
        geometry=point(1, 1),
        snapshot_time=utc(2026, 8, 17, 2, 0),
        serial_number=1,
        attributes={"IncidentSize": 100},
    )
    versions = peri_scribe.fire_history.point_versions([first, moved])
    assert [version.geometry for version in versions] == [point(1, 1)]
    assert versions[0].snapshot_time == moved.snapshot_time


def test_point_versions_creates_version_on_attribute_change() -> None:
    first = observation(
        source_kind=WFIGS_LOCATION,
        geometry=point(0, 0),
        serial_number=0,
        attributes={"IncidentSize": 100},
    )
    second = observation(
        source_kind=WFIGS_LOCATION,
        geometry=point(0, 0),
        serial_number=1,
        attributes={"IncidentSize": 200},
    )
    versions = peri_scribe.fire_history.point_versions([first, second])
    assert versions == [first, second]


def test_attribute_value_returns_first_present_value() -> None:
    first = 10
    second = 11
    assert peri_scribe.fire_history.attribute_value(
        {"area_acres": first, "poly_GISAcres": second},
        "area_acres",
        "poly_GISAcres",
    ) == first
    assert peri_scribe.fire_history.attribute_value(
        {"poly_GISAcres": second},
        "area_acres",
        "poly_GISAcres",
    ) == second
    assert peri_scribe.fire_history.attribute_value({}, "area_acres") is None


def test_text_attribute_returns_non_blank_text() -> None:
    assert peri_scribe.fire_history.text_attribute({"type": " Heat "}, "type") == "Heat"
    assert peri_scribe.fire_history.text_attribute({"type": "  "}, "type") is None
    assert peri_scribe.fire_history.text_attribute({}, "type") is None


def test_float_attribute_returns_number_or_none() -> None:
    expected = 10.5
    assert peri_scribe.fire_history.float_attribute(
        {"area_acres": "10.5"},
        "area_acres",
    ) == pytest.approx(expected)
    assert (
        peri_scribe.fire_history.float_attribute({"area_acres": "x"}, "area_acres")
        is None
    )
    assert peri_scribe.fire_history.float_attribute({}, "area_acres") is None
    assert (
        peri_scribe.fire_history.float_attribute({"area_acres": True}, "area_acres")
        is None
    )
    assert (
        peri_scribe.fire_history.float_attribute(
            {"area_acres": [1, 2]},
            "area_acres",
        )
        is None
    )


def test_datetime_attribute_returns_datetime_or_none() -> None:
    value = "2026-08-16T00:10:45"
    expected = datetime.datetime(2026, 8, 16, 0, 10, 45, tzinfo=datetime.UTC)
    assert peri_scribe.fire_history.datetime_attribute({"t": value}, "t") == expected
    assert peri_scribe.fire_history.datetime_attribute({}, "t") is None


def test_classification_text_returns_value_or_none() -> None:
    assert peri_scribe.fire_history.classification_text(None) is None
    assert (
        peri_scribe.fire_history.classification_text(
            classification(
                peri_scribe.models.BorderClassification.CROSSES_CALIFORNIA_BORDER,
            ),
        )
        == "crosses_california_border"
    )


def test_attributes_json_serializes_missing_and_dates() -> None:
    count = 3
    result = peri_scribe.fire_history.attributes_json(
        {
            "missing": float("nan"),
            "when": datetime.datetime(2026, 8, 16, 0, 10, 45, tzinfo=datetime.UTC),
            "count": count,
        },
    )
    parsed = json.loads(result)
    assert parsed["missing"] is None
    assert parsed["when"] == "2026-08-16T00:10:45+00:00"
    assert parsed["count"] == count


def test_json_safe_value_converts_nested_and_numpy_values() -> None:
    assert peri_scribe.fire_history.json_safe_value({"nested": [1, 2]}) == {
        "nested": [1, 2],
    }
    assert peri_scribe.fire_history.json_safe_value(
        np.int64(ITEM_VALUE),
    ) == ITEM_VALUE


def test_identity_fields_includes_complex_when_present() -> None:
    complex_fire = peri_scribe.models.Fire(
        name="Member",
        status=ACTIVE,
        identifier="member-id",
        aliases=frozenset({"member-id"}),
    )
    peri_scribe.models.FireComplex(
        name="ROWE CREEK COMPLEX",
        identifier="complex-id",
        fires=frozenset({complex_fire}),
    )
    fields = peri_scribe.fire_history.identity_fields(complex_fire, None)
    assert fields["complex_name"] == "ROWE CREEK COMPLEX"
    assert fields["complex_identifier"] == "complex-id"
    assert fields["fire_name"] == "Member"


def test_perimeter_row_builds_fields_and_geometry() -> None:
    geometry = polygon((0, 0), (1, 0), (1, 1), (0, 0))
    area_acres = 100
    version = observation(
        geometry=geometry,
        observation_time=utc(2026, 8, 16, 0, 10),
        attributes={"area_acres": area_acres, "GlobalID": "abc"},
    )
    row = peri_scribe.fire_history.perimeter_row(fire(), None, version)
    assert row["geometry"] == geometry
    assert row["area_acres"] == pytest.approx(area_acres)
    assert row["source_globalid"] == "abc"
    assert row["source"] == "firis_perimeter"


def test_perimeter_row_falls_back_to_current_date() -> None:
    geometry = polygon((0, 0), (1, 0), (1, 1), (0, 0))
    current_date = utc(2026, 8, 16, 0, 10)
    version = observation(
        geometry=geometry,
        snapshot_time=utc(2026, 8, 17, 1, 42),
        attributes={"poly_DateCurrent": current_date},
    )
    row = peri_scribe.fire_history.perimeter_row(fire(), None, version)
    assert row["observation_time"] == current_date


def test_point_row_builds_fields_and_geometry() -> None:
    geometry = point(0, 0)
    incident_size = 100
    version = observation(
        source_kind=WFIGS_LOCATION,
        geometry=geometry,
        snapshot_time=utc(2026, 8, 17, 1, 0),
        attributes={"IncidentSize": incident_size},
    )
    row = peri_scribe.fire_history.point_row(fire(), None, version)
    assert row["geometry"] == geometry
    assert row["incident_size"] == pytest.approx(incident_size)
    assert row["observation_time"] == version.snapshot_time
    assert row["source"] == "wfigs_location"


def test_build_dataframe_builds_geodataframe() -> None:
    geometry = point(0, 0)
    rows: list[dict[str, object]] = [{"fire_name": "Bug", "geometry": geometry}]
    dataframe = peri_scribe.fire_history.build_dataframe(
        rows,
        ["fire_name", "geometry"],
    )
    assert isinstance(dataframe, geopandas.GeoDataFrame)
    assert dataframe.crs.to_epsg() == OUTPUT_WKID
    assert list(dataframe.geometry) == [geometry]


def test_read_full_rows_reads_every_file(monkeypatch: pytest.MonkeyPatch) -> None:
    first_path = pathlib.Path("a.gpkg")
    second_path = pathlib.Path("b.gpkg")
    first_rows = [
        peri_scribe.geo_data.FireRowRecord(
            record=tests.factories.fire_record("A", ACTIVE),
            object_id=1,
            source_name=FIRIS_FEED_NAME,
            attributes={},
        ),
    ]
    second_rows = [
        peri_scribe.geo_data.FireRowRecord(
            record=tests.factories.fire_record("B", ACTIVE),
            object_id=2,
            source_name=FIRIS_FEED_NAME,
            attributes={},
        ),
    ]
    rows_by_path = {first_path: first_rows, second_path: second_rows}
    monkeypatch.setattr(
        peri_scribe.snapshots,
        "geo_package_files",
        lambda _directory: [first_path, second_path],
    )
    monkeypatch.setattr(
        peri_scribe.geo_data,
        "fire_row_records",
        lambda path: iter(rows_by_path[path]),
    )
    rows, paths = peri_scribe.fire_history.read_full_rows(pathlib.Path("sources"))
    assert rows == first_rows + second_rows
    assert paths == [first_path, second_path]


def test_history_rows_for_fire_builds_perimeter_and_point_rows() -> None:
    sources_directory = pathlib.Path("data/2026/sources")
    perimeter_path = (
        sources_directory / FIRIS_FEED_NAME / "000000,lastEdit=1786929991427.gpkg"
    )
    point_path = (
        sources_directory
        / WFIGS_LOCATION_FEED_NAME
        / "000000,lastEdit=1786955463975.gpkg"
    )
    perimeter_row_record = peri_scribe.geo_data.FireRowRecord(
        record=tests.factories.fire_record(
            "Bug",
            ACTIVE,
            identifiers=frozenset({"2026-nvccd-030683"}),
            geometry=polygon((0, 0), (1, 0), (1, 1), (0, 0)),
            observed_at=utc(2026, 8, 16, 0, 10),
        ),
        object_id=1,
        source_name=FIRIS_FEED_NAME,
        attributes={"area_acres": 100},
    )
    point_row_record = peri_scribe.geo_data.FireRowRecord(
        record=tests.factories.fire_record(
            "Bug",
            ACTIVE,
            identifiers=frozenset({"2026-nvccd-030683"}),
            geometry=point(0, 0),
        ),
        object_id=1,
        source_name=WFIGS_LOCATION_FEED_NAME,
        attributes={"IncidentSize": 100},
    )
    perimeter_rows, point_rows = peri_scribe.fire_history.history_rows_for_fire(
        fire(),
        (0, 1),
        [perimeter_row_record, point_row_record],
        [perimeter_path, point_path],
        sources_directory=sources_directory,
        classification=None,
    )
    assert len(perimeter_rows) == 1
    assert len(point_rows) == 1
    assert perimeter_rows[0]["area_acres"] == pytest.approx(100)
    assert point_rows[0]["incident_size"] == pytest.approx(100)


def test_history_rows_for_fire_drops_implausibly_small_perimeter() -> None:
    sources_directory = pathlib.Path("data/2026/sources")
    perimeter_path = (
        sources_directory / FIRIS_FEED_NAME / "000000,lastEdit=1786929991427.gpkg"
    )
    tiny = polygon((0, 0), (0.0001, 0), (0.0001, 0.0001), (0, 0))
    perimeter_row_record = peri_scribe.geo_data.FireRowRecord(
        record=tests.factories.fire_record(
            "Bug",
            ACTIVE,
            identifiers=frozenset({"2026-nvccd-030683"}),
            geometry=tiny,
            observed_at=utc(2026, 8, 16, 0, 10),
        ),
        object_id=1,
        source_name=FIRIS_FEED_NAME,
        attributes={"area_acres": 1000},
    )
    perimeter_rows, _point_rows = peri_scribe.fire_history.history_rows_for_fire(
        fire(),
        (0,),
        [perimeter_row_record],
        [perimeter_path],
        sources_directory=sources_directory,
        classification=None,
    )
    assert perimeter_rows == []


def test_history_layer_rows_skips_complex_parents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record_groups = peri_scribe.fire_sources.FireRecordGroups(
        records=(),
        record_paths=(),
        fires=(fire(),),
        groups=((),),
        complex_identifiers=frozenset(),
    )
    monkeypatch.setattr(
        peri_scribe.fire_sources,
        "fire_is_complex_parent",
        lambda *_arguments: True,
    )
    perimeter_rows, point_rows = peri_scribe.fire_history.history_layer_rows(
        record_groups,
        {},
        [],
        [],
        pathlib.Path("data/2026/sources"),
    )
    assert perimeter_rows == []
    assert point_rows == []


def test_history_geopackage_path_names_output() -> None:
    assert peri_scribe.fire_history.history_geopackage_path(
        pathlib.Path("data/2026"),
    ) == pathlib.Path("data/2026/derived/history_of_full_geography.gpkg")


def test_write_history_of_full_geography_writes_two_layers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record_groups = peri_scribe.fire_sources.FireRecordGroups(
        records=(),
        record_paths=(),
        fires=(fire(),),
        groups=((),),
        complex_identifiers=frozenset(),
    )
    monkeypatch.setattr(
        peri_scribe.fire_sources,
        "fire_record_groups",
        lambda _directory: record_groups,
    )
    monkeypatch.setattr(
        peri_scribe.classification,
        "classify_fire_sources",
        lambda *_arguments: {},
    )
    monkeypatch.setattr(
        peri_scribe.fire_history,
        "read_full_rows",
        lambda _directory: ([], []),
    )
    monkeypatch.setattr(
        pathlib.Path,
        "mkdir",
        lambda *_arguments, **_keywords: None,
    )
    written: list[tuple[pathlib.Path, list[peri_scribe.models.LayerData]]] = []
    monkeypatch.setattr(
        peri_scribe.output,
        "write_geopackage",
        lambda path, layers: written.append((path, layers)),
    )
    result = peri_scribe.fire_history.write_history_of_full_geography(
        pathlib.Path("data/2026"),
    )
    assert result == pathlib.Path("data/2026/derived/history_of_full_geography.gpkg")
    assert len(written) == 1
    _path, layers = written[0]
    assert [layer.name for layer in layers] == [
        peri_scribe.fire_history.PERIMETER_LAYER_NAME,
        peri_scribe.fire_history.POINT_LAYER_NAME,
    ]
