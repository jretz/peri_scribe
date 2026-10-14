"""Tests for peri_scribe.sources.feeds configuration."""

from __future__ import annotations

import peri_scribe.sources.feeds


def test_ca_perimeters_feed_dates_by_current_date() -> None:
    # poly_DateCurrent is the date the perimeter version is current for; the CAL FIRE
    # public view of NIFC FIRIS carries no capture-date column at all.
    assert (
        peri_scribe.sources.feeds.CA_PERIMETERS_FEED.observation_time_column
        == "poly_DateCurrent"
    )


def test_ca_perimeters_feed_identifies_by_incident_number_and_record_guid() -> None:
    # incident_number is the primary identifier, but rows mapped before an incident
    # number is assigned still carry their record GUID, which keeps such rows identified
    # rather than name-only.
    assert peri_scribe.sources.feeds.CA_PERIMETERS_FEED.fire_identifier_columns == (
        "incident_number",
        "GlobalID",
    )


def test_wfigs_perimeters_feed_dates_by_current_date_not_capture_date() -> None:
    # poly_PolygonDateTime dates the field collection and can remain unchanged when the
    # record is edited; poly_DateCurrent supplies the perimeter's as-of observation
    # date.
    assert (
        peri_scribe.sources.feeds.WFIGS_PERIMETERS_FEED.observation_time_column
        == "poly_DateCurrent"
    )


def test_wfigs_locations_feed_dates_by_incident_modified_time() -> None:
    # NIFC dates fire information by the incident record's modified time, so the
    # location observation uses ModifiedOnDateTime_dt.
    assert (
        peri_scribe.sources.feeds.WFIGS_INCIDENT_LOCATIONS_FEED.observation_time_column
        == "ModifiedOnDateTime_dt"
    )
