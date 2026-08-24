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
    change_columns=("EditDate",),
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
    # The polygon record is edited in place as a fire grows, so its capture date
    # (poly_PolygonDateTime) stays at the original mapping and misdates every later
    # version. poly_DateCurrent is the perimeter's as-of date (the date the version
    # is current for; the date the source polygon record was last edited in WFIGS),
    # which advances with each version and is the accurate per-version date.
    observation_time_column="poly_DateCurrent",
    # The polygon table updates (geometry, poly_DateCurrent, poly_CreateDate) without
    # moving attr_ModifiedOnDateTime_dt, so all three columns must count as a change
    # signal or the incremental fetch misses perimeter updates.
    change_columns=(
        "attr_ModifiedOnDateTime_dt",
        "poly_DateCurrent",
        "poly_CreateDate",
    ),
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
    # NIFC determines a fire's information last update by the incident record's
    # modified time, so the point observation is dated by ModifiedOnDateTime_dt
    # rather than by when peri_scribe fetched the layer.
    observation_time_column="ModifiedOnDateTime_dt",
    change_columns=("ModifiedOnDateTime_dt",),
)


FEEDS: list[peri_scribe.feed_types.Feed] = [
    CA_PERIMETERS_FEED,
    WFIGS_PERIMETERS_FEED,
    WFIGS_INCIDENT_LOCATIONS_FEED,
]
