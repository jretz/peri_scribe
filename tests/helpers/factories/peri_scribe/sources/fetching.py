"""Build inputs for fetching tests."""

from __future__ import annotations

import dataclasses
import datetime
import itertools

import geopandas
import shapely

import peri_scribe.sources.feed_types
import tests.helpers.factories.geography


FETCH_REFERENCE_TIME = datetime.datetime(2026, 8, 1, tzinfo=datetime.UTC)


@dataclasses.dataclass(frozen=True, kw_only=True)
class FetchFeature:
    """Keep independent source facts for the full and incremental fetch model.

    Args:
        name: The source's display name.
        active: Whether the incident is active.
        modified_minute: The modification time relative to the stored high-water mark.
        longitude: The point's longitude in source coordinate units.
    """

    name: str
    active: bool
    modified_minute: int | None
    longitude: int


def fetch_attributes(identifier: int, feature: FetchFeature) -> dict[str, object]:
    """Represent raw source facts in the same schema for storage and service results.

    Args:
        identifier: The feature's object ID.
        feature: Independent source facts for this feature.

    Returns:
        Attributes with UTC date text and the feed's raw status spellings.
    """
    return {
        "OBJECTID": identifier,
        "name": feature.name,
        "status": "Active" if feature.active else "Inactive",
        "ModifiedOnDateTime_dt": None
        if feature.modified_minute is None
        else (
            FETCH_REFERENCE_TIME + datetime.timedelta(minutes=feature.modified_minute)
        ).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def fetch_frame(features: dict[int, FetchFeature]) -> geopandas.GeoDataFrame:
    """Keep geometry and attributes aligned in a simulated stored snapshot.

    Args:
        features: Stored feature facts in their snapshot order.

    Returns:
        A WGS84 frame containing the raw source columns and point geometries.
    """
    return geopandas.GeoDataFrame(
        list(itertools.starmap(fetch_attributes, features.items())),
        geometry=[shapely.Point(feature.longitude, 0) for feature in features.values()],
        crs=tests.helpers.factories.geography.WGS84_WKID,
    )


def complete_fetch_feed(index: int) -> peri_scribe.sources.feed_types.ArcGISFeed:
    """Return a feed with a name unique to *index*.

    Args:
        index: The number that distinguishes the feed's name.

    Returns:
        The feed.
    """
    return peri_scribe.sources.feed_types.ArcGISFeed(
        url=(f"https://example.test/ArcGIS/rest/services/Fires{index}/FeatureServer/0"),
        fire_name_column="name",
        status_column="status",
    )
