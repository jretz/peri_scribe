"""Area provenance identifies the supporting observation instead of the policy clock."""

from __future__ import annotations

import datetime
import json

import pytest
import shapely.geometry

import peri_scribe.presentation.text
import spatial_data.measurements
import tests.helpers.factories.geography
import tests.helpers.factories.geometry
import tests.helpers.factories.peri_scribe.kml.parsing
import tests.helpers.factories.peri_scribe.presentation.fire_data
import tests.helpers.factories.time
from measurement_units import units


@pytest.mark.parametrize(
    ("report", "expected_area", "expected_basis"),
    [(False, 100, "Mapped; 08/31 17:00 PDT"), (True, 200, "Reported; 09/02 17:00 PDT")],
)
def test_selected_area_description_dates_the_supporting_evidence(
    *,
    report: bool,
    expected_area: float,
    expected_basis: str,
) -> None:
    days = (1, 5) if report else (1,)
    shape = tests.helpers.factories.geometry.square(0.01)
    perimeters = tests.helpers.factories.geography.geo_frame(
        {
            "observation_time": [
                tests.helpers.factories.time.utc(2026, 9, day, 0) for day in days
            ],
            "geometry_area_square_meters": [(100 * units.acres).m_as("meters**2")]
            * len(days),
        },
        [shape] * len(days),
    )
    incidents = (
        tests.helpers.factories.geography.geo_frame(
            {
                "observation_time": [tests.helpers.factories.time.utc(2026, 9, 3, 0)],
                "report_confirmed": [False],
                "incident_size": [200],
            },
            [None],
        )
        if report
        else None
    )
    area, basis = peri_scribe.presentation.text.selected_area_description(
        perimeters,
        perimeters.iloc[0:0],
        incidents,
    )
    assert area == expected_area * units.acres
    assert basis == expected_basis


def test_score_explanation_for_prefers_identifier() -> None:
    assert (
        peri_scribe.presentation.text.score_explanation_for(
            {"id-big": "Over 250 structures within a mile."},
            {"Timber": "Over 5 structures within a mile."},
            frozenset({"id-big"}),
            "Timber",
        )
        == "Over 250 structures within a mile."
    )


def test_score_explanation_for_matches_any_identifier() -> None:
    assert (
        peri_scribe.presentation.text.score_explanation_for(
            {"id-big": "Over 250 structures within a mile."},
            {},
            frozenset({"alias", "id-big"}),
            "Timber",
        )
        == "Over 250 structures within a mile."
    )


def test_score_explanation_for_falls_back_to_name() -> None:
    assert (
        peri_scribe.presentation.text.score_explanation_for(
            {},
            {"Timber": "Over 5 structures within a mile."},
            frozenset(),
            "Timber",
        )
        == "Over 5 structures within a mile."
    )


def test_score_explanation_for_returns_none_without_match() -> None:
    assert (
        peri_scribe.presentation.text.score_explanation_for(
            {},
            {},
            frozenset({"id-other"}),
            "Timber",
        )
        is None
    )


def test_fire_description_uses_latest_incident_values() -> None:
    entry = tests.helpers.factories.peri_scribe.kml.parsing.fire_index_entry(
        "Bug",
        "active",
        identifier="id-bug",
    )
    description = peri_scribe.presentation.text.fire_description(
        entry,
        tests.helpers.factories.peri_scribe.presentation.fire_data.description_perimeter_frame(),
        tests.helpers.factories.peri_scribe.presentation.fire_data.description_point_frame(),
        of_note="Over 100,000 acres, and a Type 1 Incident.",
    )
    assert description.area is not None
    assert description.area.m_as("acres") == pytest.approx(
        spatial_data.measurements.area(
            tests.helpers.factories.geometry.square(2.0),
        ).m_as(
            "acres",
        ),
    )
    assert description.percent_contained == pytest.approx(30.0)
    assert description.estimated_cost_to_date is not None
    assert description.estimated_cost_to_date.m_as("dollars") == pytest.approx(3_000.0)
    assert description.estimated_final_cost is not None
    assert description.estimated_final_cost.m_as("dollars") == pytest.approx(3_500.0)
    # Personnel comes from the sources' attributes, where the point feed's value wins
    # when both feeds carry it.
    assert description.total_personnel == pytest.approx(500.0)
    assert description.mission == "CA-BUG-2"
    assert description.source == "FIRIS / NIFC"
    assert description.identifier == "id-bug"
    assert description.observation_time == datetime.datetime(
        2026,
        8,
        6,
        20,
        0,
        tzinfo=datetime.UTC,
    )
    assert description.initial_response_time == datetime.datetime(
        2026,
        7,
        27,
        19,
        24,
        tzinfo=datetime.UTC,
    )
    assert description.protecting_unit == "CANOD"
    assert description.exterior_perimeter is not None
    assert description.exterior_perimeter.m_as("miles") == pytest.approx(
        551.47,
        rel=0.01,
    )
    assert description.incident_type == "WF"
    assert (
        description.incident_complexity == "Type 4 Incident; Type 5 Incident; Type 3 IC"
    )
    assert (
        description.fuel_model
        == "Timber (Litter and Understory); Brush (2 feet); GS1; Grass"
    )
    assert description.fire_behavior == "Active; Creeping; Smoldering; Running"
    assert description.landowner_category == "Federal"
    assert description.of_note == "Over 100,000 acres, and a Type 1 Incident."


def test_fire_description_presents_geometry_when_reported_understates() -> None:
    entry = tests.helpers.factories.peri_scribe.kml.parsing.fire_index_entry(
        "Bug",
        "active",
        identifier="id-bug",
    )
    reported_in_acres = 100.0
    geometry = tests.helpers.factories.geometry.square(0.02)
    perimeters = tests.helpers.factories.peri_scribe.kml.parsing.geometry_frame(
        [("id-bug", "Bug", geometry)],
        area_acres=[reported_in_acres],
    )
    description = peri_scribe.presentation.text.fire_description(
        entry,
        perimeters,
        tests.helpers.factories.peri_scribe.kml.parsing.geometry_frame([]),
    )
    assert description.area is not None
    assert description.area.m_as("acres") == pytest.approx(
        spatial_data.measurements.area(geometry).m_as("acres"),
    )
    assert description.area is not None
    assert description.area.m_as("acres") != pytest.approx(reported_in_acres)


def test_fire_description_uses_geometry_within_agreement() -> None:
    entry = tests.helpers.factories.peri_scribe.kml.parsing.fire_index_entry(
        "Bug",
        "active",
        identifier="id-bug",
    )
    reported_in_acres = 1_000.0
    geometry = tests.helpers.factories.geometry.square(0.02)
    perimeters = tests.helpers.factories.peri_scribe.kml.parsing.geometry_frame(
        [("id-bug", "Bug", geometry)],
        area_acres=[reported_in_acres],
    )
    description = peri_scribe.presentation.text.fire_description(
        entry,
        perimeters,
        tests.helpers.factories.peri_scribe.kml.parsing.geometry_frame([]),
    )
    assert description.area is not None
    assert description.area.m_as("acres") == pytest.approx(
        spatial_data.measurements.area(geometry).m_as("acres"),
    )


def test_fire_description_falls_back_to_point_when_perimeter_missing() -> None:
    entry = tests.helpers.factories.peri_scribe.kml.parsing.fire_index_entry(
        "Bug",
        "active",
        identifier="id-bug",
    )
    # The perimeter row carries no values of its own, so the point row supplies the
    # facts; its geometry is drawn at the point-reported 30-acre scale so the fallback
    # size is not treated as an understatement against a larger map.
    empty_perimeters = tests.helpers.factories.geography.geo_frame(
        {
            "fire_identifier": ["id-bug"],
            "fire_name": ["Bug"],
            "source": [None],
            "mission": [None],
            "area_acres": [None],
            "percent_contained": [None],
            "estimated_cost_to_date": [None],
            "estimated_final_cost": [None],
            "discovery_time": [None],
            "observation_time": [None],
            "source_attributes": [json.dumps({})],
        },
        [tests.helpers.factories.geometry.square(0.0032)],
    )
    description = peri_scribe.presentation.text.fire_description(
        entry,
        empty_perimeters,
        tests.helpers.factories.peri_scribe.presentation.fire_data.description_point_frame(),
    )
    assert description.area is not None
    assert description.area.m_as("acres") == pytest.approx(30.0)
    assert description.percent_contained == pytest.approx(30.0)
    assert description.estimated_cost_to_date is not None
    assert description.estimated_cost_to_date.m_as("dollars") == pytest.approx(3_000.0)
    assert description.estimated_final_cost is not None
    assert description.estimated_final_cost.m_as("dollars") == pytest.approx(3_500.0)
    assert description.total_personnel == pytest.approx(500.0)
    assert description.observation_time == datetime.datetime(
        2026,
        8,
        6,
        20,
        0,
        tzinfo=datetime.UTC,
    )
    assert description.initial_response_time == datetime.datetime(
        2026,
        7,
        27,
        19,
        24,
        tzinfo=datetime.UTC,
    )
    # The exterior perimeter follows the small agreement-scale geometry.
    measured_perimeter = spatial_data.measurements.exterior_perimeter(
        tests.helpers.factories.geometry.square(0.0032),
    )
    assert description.exterior_perimeter is not None
    assert measured_perimeter is not None
    assert description.exterior_perimeter.m_as("meters") == pytest.approx(
        measured_perimeter.m_as("meters"),
        rel=0.01,
    )
    assert description.incident_type == "WF"
    assert (
        description.incident_complexity == "Type 4 Incident; Type 5 Incident; Type 3 IC"
    )
    assert description.fuel_model == "Brush (2 feet); GS1; Grass"
    assert description.fire_behavior == "Active; Creeping; Smoldering"
    assert description.landowner_category is None


def test_fire_description_falls_back_to_protecting_agency() -> None:
    entry = tests.helpers.factories.peri_scribe.kml.parsing.fire_index_entry(
        "Bug",
        "active",
        identifier="id-bug",
    )
    point_frame = tests.helpers.factories.geography.geo_frame(
        {
            "fire_identifier": ["id-bug"],
            "fire_name": ["Bug"],
            "source_attributes": [json.dumps({"POOJurisdictionalAgency": "BLM"})],
        },
        [shapely.geometry.Point(1.0, 1.0)],
    )
    description = peri_scribe.presentation.text.fire_description(
        entry,
        tests.helpers.factories.peri_scribe.kml.parsing.geometry_frame([]),
        point_frame,
    )
    assert description.protecting_unit == "BLM"
    assert description.exterior_perimeter is None


def test_fire_description_falls_back_to_perimeter_personnel() -> None:
    entry = tests.helpers.factories.peri_scribe.kml.parsing.fire_index_entry(
        "Bug",
        "active",
        identifier="id-bug",
    )
    perimeter_frame = tests.helpers.factories.geography.geo_frame(
        {
            "fire_identifier": ["id-bug"],
            "fire_name": ["Bug"],
            "source_attributes": [json.dumps({"attr_TotalIncidentPersonnel": 400})],
        },
        [tests.helpers.factories.geometry.square(1.0)],
    )
    point_frame = tests.helpers.factories.geography.geo_frame(
        {
            "fire_identifier": ["id-bug"],
            "fire_name": ["Bug"],
            "source_attributes": [json.dumps({})],
        },
        [shapely.geometry.Point(1.0, 1.0)],
    )
    description = peri_scribe.presentation.text.fire_description(
        entry,
        perimeter_frame,
        point_frame,
    )
    assert description.total_personnel == pytest.approx(400.0)


def test_fire_description_keeps_reported_area_without_mappable_geometry() -> None:
    entry = tests.helpers.factories.peri_scribe.kml.parsing.fire_index_entry(
        "Bug",
        "active",
        identifier="id-bug",
    )
    empty_perimeter_frame = tests.helpers.factories.geography.geo_frame(
        {"fire_identifier": ["id-bug"], "fire_name": ["Bug"], "area_acres": [30.0]},
        [shapely.geometry.Polygon()],
    )
    description = peri_scribe.presentation.text.fire_description(
        entry,
        empty_perimeter_frame,
        tests.helpers.factories.peri_scribe.kml.parsing.geometry_frame([]),
    )
    assert description is not None
    assert description.area is not None
    assert description.area.m_as("acres") == pytest.approx(30.0)
