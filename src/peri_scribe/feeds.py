"""The configured ArcGIS feature-layer feeds that supply fire data."""

from __future__ import annotations

import peri_scribe.feed_types


# The CAL FIRE perimeter layer, which retains every update for the season, unlike the
# WFIGS layers that keep only the most recent perimeter for each active fire.
CA_PERIMETERS_FEED = peri_scribe.feed_types.ArcGISFeed(
    url=(
        "https://services1.arcgis.com/jUJYIo9tSA7EHvfZ/ArcGIS/rest/services/"
        "CA_Perimeters_NIFC_FIRIS_public_view/FeatureServer/0"
    ),
    fire_name_column="incident_name",
    status_column="displayStatus",
    fire_identifier_columns=("incident_number",),
    mission_column="mission",
    observation_time_column="poly_DateCurrent",
    modified_column="EditDate",
)

# The WFIGS perimeter layer, which keeps only the most recent perimeter for each
# active fire.
WFIGS_PERIMETERS_FEED = peri_scribe.feed_types.ArcGISFeed(
    url=(
        "https://services3.arcgis.com/T4QMspbfLg3qTGWY/ArcGIS/rest/services/"
        "WFIGS_Interagency_Perimeters_Current/FeatureServer/0"
    ),
    fire_name_column="attr_IncidentName",
    status_column="attr_ActiveFireCandidate",
    fire_identifier_columns=("poly_IRWINID", "attr_UniqueFireIdentifier"),
    complex_identifier_column="attr_CpxID",
    complex_name_column="attr_CpxName",
    is_complex_child_column="attr_IsCpxChild",
    point_of_origin_state_column="attr_POOState",
    point_of_origin_fips_column="attr_POOFips",
    observation_time_column="poly_PolygonDateTime",
    modified_column="attr_ModifiedOnDateTime_dt",
)

# The WFIGS incident location layer, which carries a point for each incident.
WFIGS_INCIDENT_LOCATIONS_FEED = peri_scribe.feed_types.ArcGISFeed(
    url=(
        "https://services3.arcgis.com/T4QMspbfLg3qTGWY/ArcGIS/rest/services/"
        "WFIGS_Incident_Locations_Current/FeatureServer/0"
    ),
    fire_name_column="IncidentName",
    status_column="ActiveFireCandidate",
    fire_identifier_columns=("IrwinID", "UniqueFireIdentifier"),
    complex_identifier_column="CpxID",
    complex_name_column="CpxName",
    is_complex_child_column="IsCpxChild",
    point_of_origin_state_column="POOState",
    point_of_origin_fips_column="POOFips",
    modified_column="ModifiedOnDateTime_dt",
)


FEEDS: list[peri_scribe.feed_types.Feed] = [
    CA_PERIMETERS_FEED,
    WFIGS_PERIMETERS_FEED,
    WFIGS_INCIDENT_LOCATIONS_FEED,
]
