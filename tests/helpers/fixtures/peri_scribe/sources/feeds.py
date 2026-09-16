"""Isolate feeds tests with explicit fixtures."""

from __future__ import annotations

import typing

import pytest

import tests.helpers.doubles.peri_scribe.sources.feeds
import tests.helpers.factories.peri_scribe.sources.feed_types


if typing.TYPE_CHECKING:
    import peri_scribe.sources.feed_types


@pytest.fixture
def feed() -> peri_scribe.sources.feed_types.ArcGISFeed:
    """Return the sample ArcGIS feed.

    Returns:
        The sample ArcGIS feed.
    """
    return tests.helpers.factories.peri_scribe.sources.feed_types.sample_feed()


@pytest.fixture
def configured_feeds(
    monkeypatch: pytest.MonkeyPatch,
) -> list[peri_scribe.sources.feed_types.Feed]:
    """Point feeds.FEEDS at two configured feeds for GeoPackage reading.

    Args:
        monkeypatch: Replace dependencies and restore them after the test.

    Returns:
        The two feeds, configured with fire name and status columns.
    """
    return tests.helpers.doubles.peri_scribe.sources.feeds.configure_feeds(
        monkeypatch,
        [
            tests.helpers.factories.peri_scribe.sources.feed_types.arc_gis_feed(
                tests.helpers.factories.peri_scribe.sources.feed_types.FIRES_ONE_URL,
                "incident_name",
                "displayStatus",
            ),
            tests.helpers.factories.peri_scribe.sources.feed_types.arc_gis_feed(
                tests.helpers.factories.peri_scribe.sources.feed_types.FIRES_TWO_URL,
                "IncidentName",
                "ActiveFireCandidate",
            ),
        ],
    )


@pytest.fixture
def configured_feeds_with_identifiers(
    monkeypatch: pytest.MonkeyPatch,
) -> list[peri_scribe.sources.feed_types.Feed]:
    """Point feeds.FEEDS at feeds with identifier and complex columns.

    The first feed is CA-layer-like, with an identifier column only. The second is
    WFIGS-like, with identifier and complex columns.

    Args:
        monkeypatch: Replace dependencies and restore them after the test.

    Returns:
        The two feeds, configured with fire name, status, identifier, and complex
        columns.
    """
    return tests.helpers.doubles.peri_scribe.sources.feeds.configure_feeds(
        monkeypatch,
        [
            tests.helpers.factories.peri_scribe.sources.feed_types.arc_gis_feed(
                tests.helpers.factories.peri_scribe.sources.feed_types.FIRES_ONE_URL,
                "incident_name",
                "displayStatus",
                fire_identifier_columns=("incident_number",),
            ),
            tests.helpers.factories.peri_scribe.sources.feed_types.arc_gis_feed(
                tests.helpers.factories.peri_scribe.sources.feed_types.FIRES_TWO_URL,
                "IncidentName",
                "ActiveFireCandidate",
                fire_identifier_columns=("IrwinID",),
                complex_identifier_column="CpxID",
                complex_name_column="CpxName",
                is_complex_child_column="IsCpxChild",
            ),
        ],
    )


@pytest.fixture
def configured_feeds_with_mission(
    monkeypatch: pytest.MonkeyPatch,
) -> list[peri_scribe.sources.feed_types.Feed]:
    """Point feeds.FEEDS at a CA-layer-like feed with mission and time columns.

    Args:
        monkeypatch: Replace dependencies and restore them after the test.

    Returns:
        The feed, configured with name, status, identifier, mission, and observation
        time columns.
    """
    return tests.helpers.doubles.peri_scribe.sources.feeds.configure_feeds(
        monkeypatch,
        [
            tests.helpers.factories.peri_scribe.sources.feed_types.arc_gis_feed(
                tests.helpers.factories.peri_scribe.sources.feed_types.FIRES_ONE_URL,
                "incident_name",
                "displayStatus",
                fire_identifier_columns=("incident_number",),
                mission_column="mission",
                observation_time_column="poly_DateCurrent",
            ),
        ],
    )


@pytest.fixture
def configured_feeds_with_point_of_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> list[peri_scribe.sources.feed_types.Feed]:
    """Point feeds.FEEDS at a WFIGS-like feed with point of origin columns.

    Args:
        monkeypatch: Replace dependencies and restore them after the test.

    Returns:
        The feed, configured with name, status, identifier, mission, and point of origin
        columns.
    """
    return tests.helpers.doubles.peri_scribe.sources.feeds.configure_feeds(
        monkeypatch,
        [
            tests.helpers.factories.peri_scribe.sources.feed_types.arc_gis_feed(
                tests.helpers.factories.peri_scribe.sources.feed_types.FIRES_TWO_URL,
                "IncidentName",
                "ActiveFireCandidate",
                fire_identifier_columns=("IrwinID",),
                mission_column="mission",
                point_of_origin_state_column="POOState",
                point_of_origin_fips_column="POOFips",
            ),
        ],
    )
