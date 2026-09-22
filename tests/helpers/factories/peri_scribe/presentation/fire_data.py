"""Build inputs for fire data tests."""

from __future__ import annotations

import datetime
import json
import typing

import shapely.geometry

import peri_scribe.perimeters.progression
import spatial_data.measurements
import tests.helpers.factories.geography
import tests.helpers.factories.geometry


if typing.TYPE_CHECKING:
    import geopandas


def area_frame(
    column: str,
    rows: list[tuple[str | None, str]],
    values: list[float | None],
) -> geopandas.GeoDataFrame:
    """Build a history frame with one area column populated.

    Args:
        column: The area column to add.
        rows: The identifier and name of each row.
        values: The area value of each row.

    Returns:
        The rows as a GeoDataFrame with *column* populated.
    """
    return tests.helpers.factories.geography.geo_frame(
        {
            "fire_identifier": [identifier for identifier, _name in rows],
            "fire_name": [name for _identifier, name in rows],
            column: values,
        },
        [shapely.geometry.Point(0.0, 0.0) for _row in rows],
    )


def type_one_point_frame(complexity_level: str | None) -> geopandas.GeoDataFrame:
    """Return a point history frame marking one fire with a complexity level.

    Args:
        complexity_level: The incident complexity level to preserve, or None to leave
            the attribute absent.

    Returns:
        The frame holding one point row for the fire.
    """
    attributes = (
        {}
        if complexity_level is None
        else {"IncidentComplexityLevel": complexity_level}
    )
    return tests.helpers.factories.geography.geo_frame(
        {
            "fire_identifier": ["id-bug"],
            "fire_name": ["Bug"],
            "source_attributes": [json.dumps(attributes)],
        },
        [shapely.geometry.Point(1.0, 1.0)],
    )


def dated_ring(
    side: float,
    observation_time: datetime.datetime,
) -> peri_scribe.perimeters.progression.Ring:
    """Return a dated growth ring over a square of *side*.

    Args:
        side: The square's side length in degrees.
        observation_time: The ring's observation time.

    Returns:
        The growth ring.
    """
    return peri_scribe.perimeters.progression.Ring(
        geometry=tests.helpers.factories.geometry.square(side),
        observation_time=observation_time,
    )


def description_perimeter_frame() -> geopandas.GeoDataFrame:
    """Return a perimeter history frame with attribute columns populated.

    Returns:
        The frame.
    """
    first_area = spatial_data.measurements.area(
        tests.helpers.factories.geometry.square(1.0),
    )
    second_area = spatial_data.measurements.area(
        tests.helpers.factories.geometry.square(2.0),
    )
    return tests.helpers.factories.geography.geo_frame(
        {
            "fire_identifier": ["id-bug", "id-bug"],
            "fire_name": ["Bug", "Bug"],
            "source": ["firis_perimeter", "firis_perimeter"],
            "mission": ["CA-BUG-1", "CA-BUG-2"],
            "area_acres": [first_area.m_as("acres"), second_area.m_as("acres")],
            "percent_contained": [10.0, 20.0],
            "estimated_cost_to_date": [1_000.0, 2_000.0],
            "estimated_final_cost": [1_500.0, 2_500.0],
            "discovery_time": [
                datetime.datetime(2026, 6, 29, 12, 4, 46, tzinfo=datetime.UTC),
                datetime.datetime(2026, 6, 29, 12, 4, 46, tzinfo=datetime.UTC),
            ],
            "observation_time": [
                datetime.datetime(2026, 8, 5, 20, 0, tzinfo=datetime.UTC),
                datetime.datetime(2026, 8, 6, 20, 0, tzinfo=datetime.UTC),
            ],
            "source_attributes": [
                json.dumps({
                    "attr_InitialResponseDateTime": "2026-07-27T19:24:00",
                    "attr_IncidentComplexityLevel": "Type 4 Incident",
                    "attr_PrimaryFuelModel": "Timber (Litter and Understory)",
                    "attr_PredominantFuelModel": "GS1",
                    "attr_PredominantFuelGroup": "Grass",
                    "attr_FireBehaviorGeneral": "Active",
                    "attr_FireBehaviorGeneral2": "Running",
                    "attr_POOLandownerCategory": "Federal",
                    "attr_TotalIncidentPersonnel": 300,
                }),
                json.dumps({
                    "attr_InitialResponseDateTime": "2026-07-27T19:24:00",
                    "attr_IncidentComplexityLevel": "Type 4 Incident",
                    "attr_PrimaryFuelModel": "Timber (Litter and Understory)",
                    "attr_PredominantFuelModel": "GS1",
                    "attr_PredominantFuelGroup": "Grass",
                    "attr_FireBehaviorGeneral": "Active",
                    "attr_FireBehaviorGeneral2": "Running",
                    "attr_POOLandownerCategory": "Federal",
                    "attr_TotalIncidentPersonnel": 400,
                }),
            ],
        },
        [
            tests.helpers.factories.geometry.square(1.0),
            tests.helpers.factories.geometry.square(2.0),
        ],
    )


def description_point_frame() -> geopandas.GeoDataFrame:
    """Return a point history frame with attribute columns populated.

    Returns:
        The frame.
    """
    return tests.helpers.factories.geography.geo_frame(
        {
            "fire_identifier": ["id-bug"],
            "fire_name": ["Bug"],
            "incident_size": [30.0],
            "percent_contained": [30.0],
            "estimated_cost_to_date": [3_000.0],
            "estimated_final_cost": [3_500.0],
            "discovery_time": [
                datetime.datetime(2026, 6, 29, 12, 4, 46, tzinfo=datetime.UTC),
            ],
            "observation_time": [
                datetime.datetime(2026, 8, 6, 20, 0, tzinfo=datetime.UTC),
            ],
            "source_attributes": [
                json.dumps({
                    "POOJurisdictionalUnit": "CANOD",
                    "InitialResponseDateTime": "2026-07-27T19:24:00",
                    "IncidentTypeCategory": "WF",
                    "IncidentComplexityLevel": "Type 4 Incident",
                    "FireMgmtComplexity": "Type 5 Incident",
                    "OrganizationalAssessment": "Type 3 IC",
                    "SecondaryFuelModel": "Brush (2 feet)",
                    "PredominantFuelModel": "GS1",
                    "PredominantFuelGroup": "Grass",
                    "FireBehaviorGeneral": "Active",
                    "FireBehaviorGeneral1": "Creeping",
                    "FireBehaviorGeneral2": "Smoldering",
                    "FireBehaviorGeneral3": "Smoldering",
                    "TotalIncidentPersonnel": 500,
                }),
            ],
        },
        [shapely.geometry.Point(1.0, 1.0)],
    )
