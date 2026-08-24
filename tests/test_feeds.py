"""Tests for peri_scribe.feeds configuration."""

from __future__ import annotations

import peri_scribe.feeds


def test_ca_perimeters_feed_dates_by_current_date() -> None:
    # poly_DateCurrent is the date the perimeter version is current for; the CAL
    # FIRE public view of NIFC FIRIS carries no capture-date column at all.
    assert (
        peri_scribe.feeds.CA_PERIMETERS_FEED.observation_time_column
        == "poly_DateCurrent"
    )


def test_wfigs_perimeters_feed_dates_by_current_date_not_capture_date() -> None:
    # poly_PolygonDateTime is the record's original capture date and stays frozen as
    # the record is edited in place; poly_DateCurrent advances with each version.
    assert (
        peri_scribe.feeds.WFIGS_PERIMETERS_FEED.observation_time_column
        == "poly_DateCurrent"
    )


def test_wfigs_locations_feed_dates_by_incident_modified_time() -> None:
    # NIFC determines a fire's information last update by the incident record's
    # modified time, so the location observation is dated by ModifiedOnDateTime_dt.
    assert (
        peri_scribe.feeds.WFIGS_INCIDENT_LOCATIONS_FEED.observation_time_column
        == "ModifiedOnDateTime_dt"
    )
