"""Dataclasses and constants for peri_scribe."""

from __future__ import annotations

import dataclasses
import json
import pathlib
import typing
from typing import TYPE_CHECKING

import peri_scribe.feed_types


if TYPE_CHECKING:
    import geopandas
    import pyproj


OUTPUT_FILENAME = "current_fire_data.gpkg"
GEOMETRY_COLUMN_NAME = "geom"

# Minimum plausible magnitude for coordinates in a projected (metre) reference. Smaller
# magnitudes are indistinguishable from degrees.
MINIMUM_PROJECTED_MAGNITUDE = 1_000.0

# Fallback maximum magnitude for a projected reference with no known area of use;
# roughly the widest extent any Earth-based projection produces.
PROJECTED_MAXIMUM_MAGNITUDE_FALLBACK = 25_000_000.0


def load_feeds_config() -> list[dict[str, typing.Any]]:
    """Read the raw feed configuration from the JSON file on disk.

    Returns:
        The parsed feed configuration as a list of dictionaries.
    """
    config_path = pathlib.Path(__file__).parent / "feeds.json"
    return json.loads(config_path.read_text())


def build_feeds(
    configs: list[dict[str, typing.Any]],
) -> list[peri_scribe.feed_types.Feed]:
    """Build feed instances from a list of configuration dictionaries.

    Each dictionary must have a ``feed_type`` key whose value is the class name
    of a registered feed type. The remaining keys are forwarded as keyword
    arguments to the feed class constructor.

    Returns:
        A list of feed instances, one per configuration dictionary.
    """
    feeds: list[peri_scribe.feed_types.Feed] = []
    for config in configs:
        feed_type_name = config["feed_type"]
        feed_class = peri_scribe.feed_types.FeedTypes.get_feed_class(feed_type_name)
        feed_parameters = {
            key: value for key, value in config.items() if key != "feed_type"
        }
        feeds.append(feed_class(**feed_parameters))
    return feeds


FEEDS: list[peri_scribe.feed_types.Feed] = build_feeds(load_feeds_config())


@dataclasses.dataclass(frozen=True, kw_only=True)
class LayerData:
    name: str
    dataframe: geopandas.GeoDataFrame


@dataclasses.dataclass(frozen=True)
class SpatialReferenceDomain:
    """Plausible coordinate magnitude bands for a spatial reference."""

    crs: pyproj.CRS
    bands: tuple[float, float, float, float]  # x and y (minimum, maximum) magnitudes
    description: str


@dataclasses.dataclass(frozen=True, kw_only=True)
class SpatialReferenceSelection:
    """Result of selecting a spatial reference wkid from candidates.

    When a wkid is chosen, `warning` holds the text to log about excluded candidates, if
    any. When no wkid can be chosen, `failure_message` explains why.
    """

    wkid: int | None
    warning: str | None = None
    failure_message: str = ""
