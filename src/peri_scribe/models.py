"""Dataclasses and constants for peri_scribe."""

from __future__ import annotations

import dataclasses
import urllib.parse
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    import geopandas as gpd
    import pyproj


OUTPUT_FILENAME = "current_fire_data.gpkg"
GEOMETRY_COLUMN_NAME = "geom"

# Minimum plausible magnitude for coordinates in a projected (metre) reference. Smaller
# magnitudes are indistinguishable from degrees.
MINIMUM_PROJECTED_MAGNITUDE = 1_000.0

# Fallback maximum magnitude for a projected reference with no known area of use;
# roughly the widest extent any Earth-based projection produces.
PROJECTED_MAXIMUM_MAGNITUDE_FALLBACK = 25_000_000.0


@dataclasses.dataclass(frozen=True, kw_only=True)
class ArcGISFeed:
    url: str

    @property
    def path_segments(self) -> list[str]:
        return [
            segment
            for segment in urllib.parse.urlsplit(self.url).path.split("/")
            if segment
        ]

    @property
    def service_name(self) -> str:
        return self.path_segments[-3]

    @property
    def layer_id(self) -> int:
        return int(self.path_segments[-1])

    @property
    def name(self) -> str:
        return f"{self.service_name}_{self.layer_id}"


FEEDS: list[ArcGISFeed] = [
    ArcGISFeed(
        url="https://services1.arcgis.com/jUJYIo9tSA7EHvfZ/ArcGIS/rest/services/CA_Perimeters_NIFC_FIRIS_public_view/FeatureServer/0",
    ),
    ArcGISFeed(
        url="https://services3.arcgis.com/T4QMspbfLg3qTGWY/ArcGIS/rest/services/WFIGS_Interagency_Perimeters_Current/FeatureServer/0",
    ),
    ArcGISFeed(
        url="https://services3.arcgis.com/T4QMspbfLg3qTGWY/ArcGIS/rest/services/WFIGS_Incident_Locations_Current/FeatureServer/0",
    ),
]


@dataclasses.dataclass(frozen=True, kw_only=True)
class LayerData:
    name: str
    dataframe: gpd.GeoDataFrame


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
