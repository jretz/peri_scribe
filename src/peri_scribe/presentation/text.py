"""Building the KML description text for each fire placemark."""

from __future__ import annotations

import dataclasses
import hashlib
import typing

import peri_scribe.areas
import peri_scribe.geo.measurements
import peri_scribe.incidents
import peri_scribe.models
import peri_scribe.presentation.descriptions
import peri_scribe.presentation.prepared_cache
import peri_scribe.presentation.row_values
import peri_scribe.presentation.selection
import spatial_data.frame_fingerprints
import spatial_data.product_cache
from measurement_units import units


if typing.TYPE_CHECKING:
    import geopandas
    import pint


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
    *,
    incident_rows: geopandas.GeoDataFrame | None = None,
    history: peri_scribe.areas.PreparedHistory | None = None,
) -> peri_scribe.presentation.descriptions.FireDescription:
    """Return *entry*'s latest state for its balloon description.

    Area follows the shared geometry/report policy. Incident measurements follow their
    own update times, so a stationary polygon cannot hold back new costs or personnel.
    Source attributes retain the other descriptive facts and their provenance.

    Args:
        entry: One fire index entry.
        perimeter_rows: The fire's perimeter history rows, already selected.
        point_rows: The fire's point history rows, already selected.
        of_note: The fire's score explanation, shown as the balloon's final row, or None
            when the fire has no saved score.
        incident_rows: The optional independent reporting history for this fire.
        history: Already prepared reporting and area evidence, or None to prepare it.

    Returns:
        The fire's latest state.
    """
    if not spatial_data.product_cache.active():
        return build_fire_description(
            entry,
            perimeter_rows,
            point_rows,
            of_note,
            incident_rows=incident_rows,
            history=history,
        )
    if history is None:
        history = peri_scribe.areas.prepare_history(
            perimeter_rows,
            point_rows,
            incident_rows,
        )
    try:
        frames = tuple(
            spatial_data.frame_fingerprints.frame_rows(frame.iloc[-1:])
            for frame in (perimeter_rows, point_rows)
        )
        key = spatial_data.frame_fingerprints.selected_key(
            frames,
            tuple(tuple(range(len(frame.rows))) for frame in frames),
            (
                entry.model_dump_json(),
                hashlib.sha256(
                    peri_scribe.presentation.prepared_cache.history_bytes(history),
                ).digest(),
            ),
        )
    except ValueError:
        return build_fire_description(
            entry,
            perimeter_rows,
            point_rows,
            of_note,
            incident_rows=incident_rows,
            history=history,
        )
    payload = spatial_data.product_cache.get("fire_descriptions", key)
    if payload is not None:
        try:
            description = peri_scribe.presentation.prepared_cache.read_description(
                payload,
            )
        except ValueError:
            pass
        else:
            return dataclasses.replace(description, of_note=of_note)
    description = build_fire_description(
        entry,
        perimeter_rows,
        point_rows,
        incident_rows=incident_rows,
        history=history,
    )
    try:
        payload = peri_scribe.presentation.prepared_cache.description_bytes(description)
    except ValueError:
        pass
    else:
        spatial_data.product_cache.put("fire_descriptions", key, payload)
    return dataclasses.replace(description, of_note=of_note)


def build_fire_description(
    entry: peri_scribe.models.FireIndexEntry,
    perimeter_rows: geopandas.GeoDataFrame,
    point_rows: geopandas.GeoDataFrame,
    of_note: str | None = None,
    *,
    incident_rows: geopandas.GeoDataFrame | None = None,
    history: peri_scribe.areas.PreparedHistory | None = None,
) -> peri_scribe.presentation.descriptions.FireDescription:
    """Derive stable facts from the latest rows and complete reporting evidence.

    Args:
        entry: Indexed fire identity and metadata.
        perimeter_rows: Selected perimeter history in chronological order.
        point_rows: Selected point history in chronological order.
        of_note: The current score explanation, when supplied.
        incident_rows: Independent reporting evidence, when available.
        history: Reconciled evidence and selected acreage, when already prepared.

    Returns:
        The fire's latest state with its exact original measurement units.
    """
    perimeter_row = perimeter_rows.iloc[-1] if not perimeter_rows.empty else None
    point_row = point_rows.iloc[-1] if not point_rows.empty else None

    exterior_perimeter: pint.Quantity[float] | None = None
    if perimeter_row is not None:
        exterior_perimeter = peri_scribe.geo.measurements.exterior_perimeter(
            perimeter_row.geometry,
            perimeter_row.get(peri_scribe.geo.measurements.EXTERIOR_COLUMN),
        )

    if history is None:
        history = peri_scribe.areas.prepare_history(
            perimeter_rows,
            point_rows,
            incident_rows,
        )
    area, area_basis = selected_area_description(
        perimeter_rows,
        point_rows,
        incident_rows,
        history=history,
    )
    updates = history.updates
    percent_contained = peri_scribe.incidents.latest_value(updates, "percent_contained")
    cost = peri_scribe.incidents.latest_value(updates, "estimated_cost_to_date")
    final_cost = peri_scribe.incidents.latest_value(updates, "estimated_final_cost")
    total_personnel = peri_scribe.incidents.latest_value(updates, "personnel")
    if total_personnel is None:
        total_personnel = peri_scribe.presentation.row_values.first_source_number(
            perimeter_row,
            point_row,
            "TotalIncidentPersonnel",
            "attr_TotalIncidentPersonnel",
        )

    discovery_time = peri_scribe.presentation.row_values.datetime_value(
        perimeter_row,
        "discovery_time",
    )
    if discovery_time is None:
        discovery_time = peri_scribe.presentation.row_values.datetime_value(
            point_row,
            "discovery_time",
        )

    observation_time = max(
        (
            time
            for time in (
                peri_scribe.presentation.row_values.datetime_value(
                    perimeter_row,
                    "observation_time",
                ),
                peri_scribe.presentation.row_values.datetime_value(
                    point_row,
                    "observation_time",
                ),
                updates[-1].observation_time if updates else None,
            )
            if time is not None
        ),
        default=None,
    )

    initial_response_time = peri_scribe.presentation.row_values.as_datetime(
        peri_scribe.presentation.row_values.source_attribute_value(
            perimeter_row,
            "attr_InitialResponseDateTime",
        ),
    )
    if initial_response_time is None:
        initial_response_time = peri_scribe.presentation.row_values.as_datetime(
            peri_scribe.presentation.row_values.source_attribute_value(
                point_row,
                "InitialResponseDateTime",
            ),
        )

    protecting_unit = peri_scribe.presentation.row_values.source_text_value(
        point_row,
        "POOJurisdictionalUnit",
    )
    if protecting_unit is None:
        protecting_unit = peri_scribe.presentation.row_values.source_text_value(
            point_row,
            "POOProtectingUnit",
        )
    if protecting_unit is None:
        protecting_unit = peri_scribe.presentation.row_values.source_text_value(
            point_row,
            "POOJurisdictionalAgency",
        )

    return peri_scribe.presentation.descriptions.FireDescription(
        identifier=entry.identifier,
        source=peri_scribe.presentation.row_values.source_label(
            peri_scribe.presentation.row_values.column_value(perimeter_row, "source"),
        ),
        mission=peri_scribe.presentation.row_values.text_value(
            perimeter_row,
            "mission",
        ),
        area=area,
        area_basis=area_basis,
        exterior_perimeter=exterior_perimeter,
        percent_contained=percent_contained,
        estimated_cost_to_date=None if cost is None else cost * units.dollars,
        estimated_final_cost=None if final_cost is None else final_cost * units.dollars,
        total_personnel=total_personnel,
        protecting_unit=protecting_unit,
        discovery_time=discovery_time,
        observation_time=observation_time,
        initial_response_time=initial_response_time,
        incident_type=peri_scribe.presentation.row_values.first_source_text(
            perimeter_row,
            point_row,
            "IncidentTypeCategory",
            None,
        ),
        incident_complexity=peri_scribe.presentation.row_values.numbered_source_text(
            perimeter_row,
            point_row,
            INCIDENT_COMPLEXITY_ATTRIBUTE_KEYS,
        ),
        fuel_model=peri_scribe.presentation.row_values.numbered_source_text(
            perimeter_row,
            point_row,
            FUEL_MODEL_ATTRIBUTE_KEYS,
        ),
        fire_behavior=peri_scribe.presentation.row_values.numbered_source_text(
            perimeter_row,
            point_row,
            FIRE_BEHAVIOR_ATTRIBUTE_KEYS,
        ),
        landowner_category=peri_scribe.presentation.row_values.first_source_text(
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
        notes_by_name: Explanations for score entries without identifiers, keyed by
            name.
        fire_identifiers: The fire's canonical identifier and aliases.
        name: The fire's name.

    Returns:
        The explanation, or None when neither the identifiers nor the name match.
    """
    explanation = peri_scribe.presentation.selection.first_identifier_match(
        fire_identifiers,
        notes_by_identifier,
    )
    if explanation is not None:
        return explanation
    return notes_by_name.get(name)


def selected_area_description(
    perimeters: geopandas.GeoDataFrame,
    points: geopandas.GeoDataFrame,
    incident_rows: geopandas.GeoDataFrame | None,
    *,
    history: peri_scribe.areas.PreparedHistory | None = None,
) -> tuple[pint.Quantity[float] | None, str | None]:
    """Explain the evidence behind the area shared by charts, scores, and descriptions.

    The provenance date belongs to the underlying observation, which can precede the
    policy deadline that made a report eligible to replace stagnant mapping.

    Args:
        perimeters: The fire's selected perimeter history.
        points: Incident location rows used for fallback area reports.
        incident_rows: The optional independent incident history.
        history: Already prepared reporting and area evidence, or None to prepare it.

    Returns:
        The selected area and its source/date description. Undated fallbacks have no
        provenance text; missing measurements also have no area.
    """
    if history is None:
        history = peri_scribe.areas.prepare_history(perimeters, points, incident_rows)
    if not history.estimates:
        return history.latest_area, None
    estimate = history.estimates[-1]
    date = peri_scribe.presentation.descriptions.format_pacific_time(
        estimate.observation_time,
    )
    return estimate.area, f"{estimate.source.value}; {date}"
