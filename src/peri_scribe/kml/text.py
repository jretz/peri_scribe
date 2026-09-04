"""Building the KML description text for each fire placemark."""

from __future__ import annotations

import typing

import peri_scribe.areas
import peri_scribe.kml.descriptions
import peri_scribe.kml.plot_data
import peri_scribe.kml.row_values
import peri_scribe.models
import peri_scribe.units


if typing.TYPE_CHECKING:
    import geopandas


# The smallest computed or reported area that keeps a fire in the KMZ output. Fires
# whose every area indication is missing or below this are the season's long tail of
# tiny incidents, which clutter Google Earth without adding information.


FIRE_BEHAVIOR_ATTRIBUTE_KEYS: dict[int, tuple[str, str]] = {
    0: ("FireBehaviorGeneral", "attr_FireBehaviorGeneral"),
    1: ("FireBehaviorGeneral1", "attr_FireBehaviorGeneral1"),
    2: ("FireBehaviorGeneral2", "attr_FireBehaviorGeneral2"),
    3: ("FireBehaviorGeneral3", "attr_FireBehaviorGeneral3"),
}


INCIDENT_COMPLEXITY_ATTRIBUTE_KEYS: dict[int, tuple[str, str]] = {
    1: ("IncidentComplexityLevel", "attr_IncidentComplexityLevel"),
    2: ("FireMgmtComplexity", "attr_FireMgmtComplexity"),
    3: ("OrganizationalAssessment", "attr_OrganizationalAssessment"),
}


FUEL_MODEL_ATTRIBUTE_KEYS: dict[int, tuple[str, str]] = {
    1: ("PrimaryFuelModel", "attr_PrimaryFuelModel"),
    2: ("SecondaryFuelModel", "attr_SecondaryFuelModel"),
    3: ("PredominantFuelModel", "attr_PredominantFuelModel"),
    4: ("PredominantFuelGroup", "attr_PredominantFuelGroup"),
}


def fire_description(
    entry: peri_scribe.models.FireIndexEntry,
    perimeter_rows: geopandas.GeoDataFrame,
    point_rows: geopandas.GeoDataFrame,
    of_note: str | None = None,
) -> peri_scribe.kml.descriptions.FireDescription:
    """Return *entry*'s latest state for its balloon description.

    The latest perimeter supplies the fire's area, containment, cost, and timing; where
    a perimeter has no value for a fact the latest point location is used instead. The
    area shown is the reported acreage unless the perimeter's measured area is
    significantly larger, in which case the measured area is shown because the reported
    figure trails the polygon the source published. The protecting unit, initial
    response time, incident type, complexity, fuels, fire behavior, landowner category,
    and personnel count come only from the sources' original attributes, which the
    history preserves verbatim.

    Args:
        entry: One fire index entry.
        perimeter_rows: The fire's perimeter history rows, already selected.
        point_rows: The fire's point history rows, already selected.
        of_note: The fire's score explanation, shown as the balloon's final row, or
            None when the fire has no saved score.

    Returns:
        The fire's latest state.
    """
    perimeter_row = perimeter_rows.iloc[-1] if not perimeter_rows.empty else None
    point_row = point_rows.iloc[-1] if not point_rows.empty else None

    exterior_perimeter_in_miles = None
    if perimeter_row is not None:
        exterior_perimeter_in_miles = peri_scribe.units.exterior_perimeter_in_miles(
            perimeter_row.geometry,
        )

    area_in_acres = peri_scribe.kml.row_values.float_value(perimeter_row, "area_acres")
    if area_in_acres is None:
        area_in_acres = peri_scribe.kml.row_values.float_value(
            point_row,
            "incident_size",
        )
    if (
        area_in_acres is not None
        and perimeter_row is not None
        and perimeter_row.geometry is not None
        and not perimeter_row.geometry.is_empty
    ):
        # The reported acreage can trail the polygon the source published; when the
        # geometry is significantly larger the measured area is what users should see.
        area_in_acres = peri_scribe.areas.presented_area_in_acres(
            area_in_acres,
            peri_scribe.units.area_in_acres(perimeter_row.geometry),
        )

    percent_contained = peri_scribe.kml.row_values.float_value(
        perimeter_row,
        "percent_contained",
    )
    if percent_contained is None:
        percent_contained = peri_scribe.kml.row_values.float_value(
            point_row,
            "percent_contained",
        )

    estimated_cost_to_date = peri_scribe.kml.row_values.float_value(
        perimeter_row,
        "estimated_cost_to_date",
    )
    if estimated_cost_to_date is None:
        estimated_cost_to_date = peri_scribe.kml.row_values.float_value(
            point_row,
            "estimated_cost_to_date",
        )

    estimated_final_cost = peri_scribe.kml.row_values.float_value(
        perimeter_row,
        "estimated_final_cost",
    )
    if estimated_final_cost is None:
        estimated_final_cost = peri_scribe.kml.row_values.float_value(
            point_row,
            "estimated_final_cost",
        )

    total_personnel = peri_scribe.kml.row_values.first_source_number(
        perimeter_row,
        point_row,
        peri_scribe.kml.plot_data.POINT_PERSONNEL_ATTRIBUTE_KEY,
        peri_scribe.kml.plot_data.PERIMETER_PERSONNEL_ATTRIBUTE_KEY,
    )

    discovery_time = peri_scribe.kml.row_values.datetime_value(
        perimeter_row,
        "discovery_time",
    )
    if discovery_time is None:
        discovery_time = peri_scribe.kml.row_values.datetime_value(
            point_row,
            "discovery_time",
        )

    observation_time = peri_scribe.kml.row_values.datetime_value(
        perimeter_row,
        "observation_time",
    )
    if observation_time is None:
        observation_time = peri_scribe.kml.row_values.datetime_value(
            point_row,
            "observation_time",
        )

    initial_response_time = peri_scribe.kml.row_values.as_datetime(
        peri_scribe.kml.row_values.source_attribute_value(
            perimeter_row,
            "attr_InitialResponseDateTime",
        ),
    )
    if initial_response_time is None:
        initial_response_time = peri_scribe.kml.row_values.as_datetime(
            peri_scribe.kml.row_values.source_attribute_value(
                point_row,
                "InitialResponseDateTime",
            ),
        )

    protecting_unit = peri_scribe.kml.row_values.source_text_value(
        point_row,
        "POOJurisdictionalUnit",
    )
    if protecting_unit is None:
        protecting_unit = peri_scribe.kml.row_values.source_text_value(
            point_row,
            "POOProtectingUnit",
        )
    if protecting_unit is None:
        protecting_unit = peri_scribe.kml.row_values.source_text_value(
            point_row,
            "POOJurisdictionalAgency",
        )

    return peri_scribe.kml.descriptions.FireDescription(
        identifier=entry.identifier,
        source=peri_scribe.kml.row_values.source_label(
            peri_scribe.kml.row_values.column_value(perimeter_row, "source"),
        ),
        mission=peri_scribe.kml.row_values.text_value(perimeter_row, "mission"),
        area_in_acres=area_in_acres,
        exterior_perimeter_in_miles=exterior_perimeter_in_miles,
        percent_contained=percent_contained,
        estimated_cost_to_date_in_dollars=estimated_cost_to_date,
        estimated_final_cost_in_dollars=estimated_final_cost,
        total_personnel=total_personnel,
        protecting_unit=protecting_unit,
        discovery_time=discovery_time,
        observation_time=observation_time,
        initial_response_time=initial_response_time,
        incident_type=peri_scribe.kml.row_values.first_source_text(
            perimeter_row,
            point_row,
            "IncidentTypeCategory",
            None,
        ),
        incident_complexity=peri_scribe.kml.row_values.numbered_source_text(
            perimeter_row,
            point_row,
            INCIDENT_COMPLEXITY_ATTRIBUTE_KEYS,
        ),
        fuel_model=peri_scribe.kml.row_values.numbered_source_text(
            perimeter_row,
            point_row,
            FUEL_MODEL_ATTRIBUTE_KEYS,
        ),
        fire_behavior=peri_scribe.kml.row_values.numbered_source_text(
            perimeter_row,
            point_row,
            FIRE_BEHAVIOR_ATTRIBUTE_KEYS,
        ),
        landowner_category=peri_scribe.kml.row_values.first_source_text(
            perimeter_row,
            point_row,
            None,
            "attr_POOLandownerCategory",
        ),
        of_note=of_note,
    )


def score_explanation_for(
    notes_by_identifier: typing.Mapping[str, str],
    notes_by_name: typing.Mapping[str, str],
    fire_identifiers: frozenset[str],
    name: str,
) -> str | None:
    """Return the score explanation matching *fire_identifiers* or *name*.

    A fire's explanation is found by its identifiers first, so fires that share a name
    but not an identity each show their own explanation; a fire no identifier matches
    falls back to its name.

    Args:
        notes_by_identifier: Explanations keyed by score entry identifier.
        notes_by_name: Explanations for score entries without identifiers, keyed
            by name.
        fire_identifiers: The fire's canonical identifier and aliases.
        name: The fire's name.

    Returns:
        The explanation, or None when neither the identifiers nor the name match.
    """
    return next(
        (
            notes_by_identifier[identifier]
            for identifier in fire_identifiers
            if identifier in notes_by_identifier
        ),
        notes_by_name.get(name),
    )
