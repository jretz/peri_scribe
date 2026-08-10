"""Fetch current wildfire data feeds into a single GeoPackage.

Fidelity to the sources:

- No reprojection: coordinates are written in each layer's native spatial
  reference, and the CRS is recorded per layer. The CRS is chosen from the
  spatial reference wkids the layer and its query report, keeping the
  candidates whose plausible coordinate range (from pyproj's CRS database)
  fits the returned coordinates; if none or several fit, the fetch fails
  before anything is written.
- Column names are written verbatim, as reported by the service.
- Attribute values are written as returned by the service; date fields
  (esriFieldTypeDate) are converted to pandas datetimes (datetime64[us]).

If a feed returns no features, NoFeaturesError is raised before any output is
written, so an existing output file is left untouched.
"""

from __future__ import annotations

import dataclasses
import math
import pathlib
import typing
import urllib.parse

import arcgis.features
import arcgis.gis
import click
import geopandas as gpd
import pyproj
import pyproj.exceptions
import shapely
import structlog


if typing.TYPE_CHECKING:
    import pandas as pd


logger = structlog.get_logger()


OUTPUT_FILENAME = "current_fire_data.gpkg"
GEOMETRY_COLUMN_NAME = "geom"

# Minimum plausible magnitude for coordinates in a projected (metre)
# reference. Smaller magnitudes are indistinguishable from degrees.
MINIMUM_PROJECTED_MAGNITUDE = 1_000.0

# Fallback maximum magnitude for a projected reference with no known area
# of use; roughly the widest extent any Earth-based projection produces.
PROJECTED_MAXIMUM_MAGNITUDE_FALLBACK = 25_000_000.0


class NoFeaturesError(ValueError):
    """Raised when a feed returns no features."""


class NoSpatialReferenceError(ValueError):
    """Raised when a layer's spatial reference cannot be determined."""

    def __init__(self, message: str = "no usable spatial reference wkid") -> None:
        super().__init__(message)


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


def spatial_reference_wkids(spatial_reference: object) -> set[int]:
    """Collect the integer wkid values an ArcGIS spatial reference reports."""
    if not isinstance(spatial_reference, dict):
        return set()
    wkids: set[int] = set()
    for key in ("wkid", "latestWkid"):
        value = spatial_reference.get(key)
        if isinstance(value, str) and value.isdigit():
            value = int(value)
        if isinstance(value, int):
            wkids.add(value)
    return wkids


def layer_wkids(layer: arcgis.features.FeatureLayer) -> set[int]:
    """Collect every wkid the layer's metadata reports, including extents."""
    wkids: set[int] = set()
    properties = layer.properties
    for key in ("extent", "fullExtent", "initialExtent"):
        container = properties.get(key)
        if isinstance(container, dict):
            wkids |= spatial_reference_wkids(container.get("spatialReference"))
    wkids |= spatial_reference_wkids(properties.get("spatialReference"))
    return wkids


def bounds_of(
    geometries: list[shapely.Geometry | None],
) -> tuple[float, float, float, float] | None:
    """Return (x_minimum, x_maximum, y_minimum, y_maximum) of the geometries.

    Returns None if every geometry is null.
    """
    valid = [geometry for geometry in geometries if geometry is not None]
    if not valid:
        return None
    x_minimum, y_minimum, x_maximum, y_maximum = shapely.total_bounds(valid)
    return x_minimum, x_maximum, y_minimum, y_maximum


def projected_maximum_magnitude(crs: pyproj.CRS) -> float:
    """Return the largest coordinate magnitude a projected CRS plausibly produces.

    Derived from the CRS's area of use: its corners are transformed into
    the CRS, giving the coordinate extent in the CRS's own units.
    """
    area = crs.area_of_use
    if area is None:
        return PROJECTED_MAXIMUM_MAGNITUDE_FALLBACK
    transformer = pyproj.Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    maximum_magnitude = 0.0
    for longitude, latitude in (
        (area.west, area.south),
        (area.east, area.south),
        (area.west, area.north),
        (area.east, area.north),
    ):
        try:
            x_coordinate, y_coordinate = transformer.transform(longitude, latitude)
        except pyproj.exceptions.ProjError, ValueError:
            continue
        if math.isfinite(x_coordinate) and math.isfinite(y_coordinate):
            maximum_magnitude = max(
                maximum_magnitude,
                abs(x_coordinate),
                abs(y_coordinate),
            )
    if not maximum_magnitude:
        return PROJECTED_MAXIMUM_MAGNITUDE_FALLBACK
    return maximum_magnitude


@dataclasses.dataclass(frozen=True)
class SpatialReferenceDomain:
    """Plausible coordinate magnitude bands for a spatial reference."""

    crs: pyproj.CRS
    bands: tuple[float, float, float, float]  # x and y (minimum, maximum) magnitudes
    description: str


def spatial_reference_domain(wkid: int) -> SpatialReferenceDomain | None:
    """Describe the plausible coordinate domain of a wkid, or None if unknown."""
    try:
        crs = pyproj.CRS.from_epsg(wkid)
    except pyproj.exceptions.CRSError:
        return None
    if crs.is_geographic:
        return SpatialReferenceDomain(
            crs,
            (0.0, 180.0, 0.0, 90.0),
            "geographic (degrees)",
        )
    if not crs.is_projected:
        return None
    unit = crs.axis_info[0].unit_name if crs.axis_info else "unknown"
    maximum_magnitude = projected_maximum_magnitude(crs)
    return SpatialReferenceDomain(
        crs,
        (
            MINIMUM_PROJECTED_MAGNITUDE,
            maximum_magnitude,
            MINIMUM_PROJECTED_MAGNITUDE,
            maximum_magnitude,
        ),
        f"projected ({unit})",
    )


def axis_fits(
    low: float,
    high: float,
    minimum_magnitude: float,
    maximum_magnitude: float,
) -> bool:
    """Return True if every value in [low, high] has magnitude in the band."""
    if max(abs(low), abs(high)) > maximum_magnitude:
        return False
    if minimum_magnitude > 0 and low <= 0 <= high:
        return False
    return min(abs(low), abs(high)) >= minimum_magnitude


def coordinates_match_domain(
    domain: tuple[float, float, float, float],
    bounds: tuple[float, float, float, float],
) -> bool:
    """Return True if every coordinate magnitude in bounds fits the bands."""
    x_minimum_band, x_maximum_band, y_minimum_band, y_maximum_band = domain
    x_minimum, x_maximum, y_minimum, y_maximum = bounds
    return axis_fits(
        x_minimum,
        x_maximum,
        x_minimum_band,
        x_maximum_band,
    ) and axis_fits(y_minimum, y_maximum, y_minimum_band, y_maximum_band)


def longitudes_in_area(
    west: float,
    east: float,
    x_minimum: float,
    x_maximum: float,
) -> bool:
    """Return True if the longitude extent lies within the area's bounds.

    The area may wrap across the antimeridian, in which case west > east.
    """
    if west <= east:
        return west <= x_minimum and x_maximum <= east
    return x_maximum <= east or x_minimum >= west


def coordinates_in_area(
    crs: pyproj.CRS,
    bounds: tuple[float, float, float, float],
) -> bool:
    """Return True if the bounds fall inside the CRS's area of use.

    An unknown area of use is treated as matching.
    """
    area = crs.area_of_use
    if area is None:
        return True
    x_minimum, x_maximum, y_minimum, y_maximum = bounds
    return (
        longitudes_in_area(area.west, area.east, x_minimum, x_maximum)
        and area.south <= y_minimum
        and y_maximum <= area.north
    )


def area_of_use_text(crs: pyproj.CRS) -> str:
    """Describe a CRS's area of use for warnings."""
    area = crs.area_of_use
    if area is None:
        return "unknown"
    return f"longitude {area.west}..{area.east}, latitude {area.south}..{area.north}"


@dataclasses.dataclass(frozen=True, kw_only=True)
class SpatialReferenceSelection:
    """Result of selecting a spatial reference wkid from candidates.

    When a wkid is chosen, `warning` holds the text to log about
    excluded candidates, if any. When no wkid can be chosen,
    `failure_message` explains why.
    """

    wkid: int | None
    warning: str | None = None
    failure_message: str = ""


def select_spatial_reference_wkid(
    candidates: set[int],
    bounds: tuple[float, float, float, float] | None,
) -> SpatialReferenceSelection:
    """Choose a wkid from the candidates for coordinates with these bounds.

    Keeps only the candidates whose plausible coordinate domain — derived
    from pyproj's CRS database — fits the returned features' coordinate
    bounds. The single surviving candidate wins; when others were excluded
    the selection carries a warning that lists them and the reason. When
    no wkid can be chosen, the selection carries a failure message that
    explains why.
    """
    if not candidates:
        return SpatialReferenceSelection(
            wkid=None,
            failure_message=(
                "no spatial reference wkid reported by the layer or its query"
            ),
        )
    if bounds is None:
        if len(candidates) == 1:
            return SpatialReferenceSelection(wkid=next(iter(candidates)))
        return SpatialReferenceSelection(
            wkid=None,
            failure_message=(
                "cannot determine spatial reference: wkids "
                f"{sorted(candidates)} are reported, but no feature geometry "
                "is available to check them"
            ),
        )
    x_minimum, x_maximum, y_minimum, y_maximum = bounds
    matches: list[int] = []
    excluded: list[str] = []
    for wkid in sorted(candidates):
        domain = spatial_reference_domain(wkid)
        if domain is None:
            excluded.append(f"{wkid} (no expected coordinate range known)")
        elif not coordinates_match_domain(domain.bands, bounds):
            (
                x_minimum_band,
                x_maximum_band,
                y_minimum_band,
                y_maximum_band,
            ) = domain.bands
            excluded.append(
                f"{wkid} ({domain.description}, expected coordinate "
                f"magnitudes x {x_minimum_band}..{x_maximum_band}, "
                f"y {y_minimum_band}..{y_maximum_band}, "
                f"got x {x_minimum}..{x_maximum}, "
                f"y {y_minimum}..{y_maximum})",
            )
        elif domain.crs.is_geographic and not coordinates_in_area(domain.crs, bounds):
            excluded.append(
                f"{wkid} (coordinates outside its area of use "
                f"{area_of_use_text(domain.crs)})",
            )
        else:
            matches.append(wkid)
    if len(matches) == 1:
        warning = None
        if excluded:
            warning = (
                f"  warning: picked spatial reference EPSG:{matches[0]}; "
                f"excluded {', '.join(excluded)}"
            )
        return SpatialReferenceSelection(wkid=matches[0], warning=warning)
    if not matches:
        return SpatialReferenceSelection(
            wkid=None,
            failure_message=(
                "no reported spatial reference wkid matches the returned "
                f"coordinates (x {x_minimum}..{x_maximum}, "
                f"y {y_minimum}..{y_maximum}); "
                f"excluded {', '.join(excluded)}"
            ),
        )
    return SpatialReferenceSelection(
        wkid=None,
        failure_message=(
            f"ambiguous spatial reference: wkids {sorted(matches)} all match "
            f"the returned coordinates (x {x_minimum}..{x_maximum}, "
            f"y {y_minimum}..{y_maximum})"
        ),
    )


def choose_spatial_reference_id(
    layer: arcgis.features.FeatureLayer,
    feature_set: arcgis.features.FeatureSet,
    bounds: tuple[float, float, float, float] | None,
) -> int:
    """Pick the spatial reference id for the coordinates a query returned.

    Collects every wkid the layer reports (layer metadata, layer extents,
    and the query response) and selects the candidate whose plausible
    coordinate domain fits the returned features' coordinate bounds. If
    the selection carries a warning, it is logged; if no wkid can be
    chosen, NoSpatialReferenceError is raised so no output is written.
    """
    candidates = layer_wkids(layer) | spatial_reference_wkids(
        feature_set.spatial_reference,
    )
    selection = select_spatial_reference_wkid(candidates, bounds)
    if selection.wkid is not None:
        if selection.warning is not None:
            logger.warning(selection.warning)
        return selection.wkid
    raise NoSpatialReferenceError(selection.failure_message)


def extract_geometries(
    dataframe: pd.DataFrame,
) -> tuple[pd.DataFrame, list[shapely.Geometry | None], str | None]:
    """Separate a feature dataframe's SHAPE column from its attributes.

    Returns the dataframe with the SHAPE column removed, the shapely
    geometries of its features (None where a feature has no geometry),
    and a warning to report when the dataframe has no geometry column.
    """
    if "SHAPE" not in dataframe.columns:
        return (
            dataframe,
            [None] * len(dataframe),
            (
                "  warning: all features lack geometry; "
                "writing the layer with NULL geometry"
            ),
        )
    return (
        dataframe.drop(columns=["SHAPE"]),
        list(dataframe["SHAPE"].geom.as_shapely),
        None,
    )


def geo_data_frame_from(
    dataframe: pd.DataFrame,
    shapely_geometries: list[shapely.Geometry | None],
    spatial_reference_id: int,
) -> gpd.GeoDataFrame:
    """Build the output GeoDataFrame with its geometry column renamed."""
    geo_data_frame = gpd.GeoDataFrame(
        dataframe,
        geometry=shapely_geometries,
        crs=pyproj.CRS.from_epsg(spatial_reference_id),
    )
    return geo_data_frame.rename_geometry(GEOMETRY_COLUMN_NAME, inplace=False)


def dataframe_for_layer(
    feed: ArcGISFeed,
    layer: arcgis.features.FeatureLayer,
    feature_set: arcgis.features.FeatureSet,
) -> gpd.GeoDataFrame:
    """Convert a query result to a GeoDataFrame in the layer's native CRS.

    Raises NoFeaturesError if the feed returns no features.
    """
    features = feature_set.features
    if not features:
        message = (
            f"Feed {feed.name} returned no features; {OUTPUT_FILENAME} was not modified"
        )
        raise NoFeaturesError(message)
    dataframe = feature_set.sdf
    dataframe, shapely_geometries, geometry_warning = extract_geometries(dataframe)
    if geometry_warning is not None:
        logger.warning(geometry_warning)
    bounds = bounds_of(shapely_geometries)
    spatial_reference_id = choose_spatial_reference_id(layer, feature_set, bounds)
    return geo_data_frame_from(dataframe, shapely_geometries, spatial_reference_id)


def write_geopackage(path: pathlib.Path, layers: list[LayerData]) -> None:
    if path.exists():
        path.unlink()
        logger.info("Replaced existing", path=path.name)
    mode = "w"
    for layer_data in layers:
        layer_data.dataframe.to_file(
            path,
            driver="GPKG",
            layer=layer_data.name,
            mode=mode,
        )
        logger.info(
            "Wrote layer",
            layer=layer_data.name,
            features=len(layer_data.dataframe),
        )
        mode = "a"


def configure_logging(log_level: str) -> None:
    """Configure structlog with the minimum log level."""
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="%Y-%m-%dT%H:%M:%S%z", utc=False),
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
    )


@click.group()
@click.option(
    "--log-level",
    type=click.Choice(
        ["debug", "info", "warning", "error", "critical"],
        case_sensitive=False,
    ),
    default="info",
    show_default=True,
    help="Logging level.",
)
def cli(log_level: str) -> None:
    """Fetch current wildfire data feeds into a single GeoPackage."""
    configure_logging(log_level)


@cli.command()
def fetch() -> None:
    """Fetch all configured feeds into a single GeoPackage."""
    output_path = pathlib.Path.cwd() / OUTPUT_FILENAME
    logger.info("Output file", path=output_path)
    gis = arcgis.gis.GIS()
    layers: list[LayerData] = []
    for feed in FEEDS:
        logger.info("Fetching", feed=feed.name, url=feed.url)
        try:
            layer = arcgis.features.FeatureLayer(feed.url, gis)
            feature_set = layer.query()
            geodataframe = dataframe_for_layer(feed, layer, feature_set)
        except Exception as error:
            # Fail fast with a readable message if a feed is unreachable.
            message = f"Failed to fetch {feed.name}: {error}"
            raise SystemExit(message) from error
        logger.info("Received features", count=len(feature_set.features))
        logger.info(
            "Prepared feed",
            feed=feed.name,
            rows=len(geodataframe),
            crs=geodataframe.crs,
        )
        layers.append(LayerData(name=feed.name, dataframe=geodataframe))
    logger.info("Writing layers", count=len(layers), path=output_path)
    write_geopackage(output_path, layers)
    logger.info("Done")


@cli.command()
def feed_config() -> None:
    """Print the configured feeds."""
    for i, feed in enumerate(FEEDS):
        logger.info("Feed %d", i + 1, name=feed.name, url=feed.url)


if __name__ == "__main__":
    cli()
