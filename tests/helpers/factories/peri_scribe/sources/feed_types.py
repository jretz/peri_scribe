"""Build inputs for feed types tests."""

from __future__ import annotations

import peri_scribe.sources.feed_types


SAMPLE_FEED_URL = (
    "https://example.test/ArcGIS/rest/services/Fire_Layers/FeatureServer/3"
)


SAMPLE_PATH_SEGMENTS = [
    "ArcGIS",
    "rest",
    "services",
    "Fire_Layers",
    "FeatureServer",
    "3",
]


SAMPLE_SERVICE_NAME = "Fire_Layers"


SAMPLE_LAYER_ID = 3


SAMPLE_FEED_NAME = "Fire_Layers_3"


SAMPLE_FIRE_NAME_COLUMN = "name"


SAMPLE_STATUS_COLUMN = "status"


def sample_feed() -> peri_scribe.sources.feed_types.ArcGISFeed:
    """Return the sample ArcGIS feed.

    Returns:
        The sample ArcGIS feed.
    """
    return peri_scribe.sources.feed_types.ArcGISFeed(
        url=SAMPLE_FEED_URL,
        fire_name_column=SAMPLE_FIRE_NAME_COLUMN,
        status_column=SAMPLE_STATUS_COLUMN,
    )


FIRES_ONE_URL = "https://example.test/ArcGIS/rest/services/Fires_One/FeatureServer/0"


FIRES_TWO_URL = "https://example.test/ArcGIS/rest/services/Fires_Two/FeatureServer/0"


def arc_gis_feed(
    url: str,
    fire_name_column: str,
    status_column: str,
    *,
    fire_identifier_columns: tuple[str, ...] = (),
    mission_column: str | None = None,
    observation_time_column: str | None = None,
    point_of_origin_state_column: str | None = None,
    point_of_origin_fips_column: str | None = None,
    complex_identifier_column: str | None = None,
    complex_name_column: str | None = None,
    is_complex_child_column: str | None = None,
    change_columns: tuple[str, ...] = (),
) -> peri_scribe.sources.feed_types.ArcGISFeed:
    """Build an ArcGIS feed with the given name and status columns.

    Args:
        url: The feed's REST URL.
        fire_name_column: The column holding each fire's name.
        status_column: The column holding each fire's status.
        fire_identifier_columns: The columns holding fire identifiers.
        mission_column: The column holding each fire's mission.
        observation_time_column: The column holding each fire's observation time.
        point_of_origin_state_column: The column holding the point of origin state.
        point_of_origin_fips_column: The column holding the point of origin FIPS.
        complex_identifier_column: The column holding each complex's identifier.
        complex_name_column: The column holding each complex's name.
        is_complex_child_column: The column marking complex child rows.
        change_columns: The timestamp columns that change when a feature is edited.

    Returns:
        The ArcGIS feed.
    """
    return peri_scribe.sources.feed_types.ArcGISFeed(
        url=url,
        fire_name_column=fire_name_column,
        status_column=status_column,
        fire_identifier_columns=fire_identifier_columns,
        mission_column=mission_column,
        observation_time_column=observation_time_column,
        point_of_origin_state_column=point_of_origin_state_column,
        point_of_origin_fips_column=point_of_origin_fips_column,
        complex_identifier_column=complex_identifier_column,
        complex_name_column=complex_name_column,
        is_complex_child_column=is_complex_child_column,
        change_columns=change_columns,
    )


def change_feed(
    change_columns: tuple[str, ...] = ("ModifiedOnDateTime_dt",),
) -> peri_scribe.sources.feed_types.Feed:
    """Return a feed with known change columns.

    Args:
        change_columns: The timestamp columns that change when a feature is edited.

    Returns:
        The feed.
    """
    return peri_scribe.sources.feed_types.ArcGISFeed(
        url="https://example.test/ArcGIS/rest/services/Fires/FeatureServer/0",
        fire_name_column="name",
        status_column="status",
        change_columns=change_columns,
    )


def feed_document(**kwargs: object) -> dict[str, object]:
    """Return the sample feed's configuration document with *kwargs*.

    Args:
        kwargs: Configuration keys to add or replace.

    Returns:
        The feed configuration document.
    """
    return {
        "feed_type": "ArcGISFeed",
        "url": SAMPLE_FEED_URL,
        "fire_name_column": SAMPLE_FIRE_NAME_COLUMN,
        "status_column": SAMPLE_STATUS_COLUMN,
        **kwargs,
    }


SAMPLE_LAST_EDIT_DATE = 123
