"""Build inputs for administrative boundaries tests."""

from __future__ import annotations

import pathlib

import arcgis.features
import geopandas
import pyproj
import shapely.geometry

import peri_scribe.sources.administrative_boundaries
import peri_scribe.sources.borders


CALIFORNIA = shapely.geometry.Polygon([(0, 0), (0, 10), (10, 10), (10, 0)])


ARIZONA = shapely.geometry.Polygon([(10, 0), (10, 10), (20, 10), (20, 0)])


NEVADA = shapely.geometry.Polygon([(0, 10), (0, 20), (10, 20), (10, 10)])


OREGON = shapely.geometry.Polygon([(-10, 0), (-10, 10), (0, 10), (0, 0)])


BASE_DIRECTORY = pathlib.Path("/boundaries")


OUTPUT_LAYER_NAME = peri_scribe.sources.administrative_boundaries.OUTPUT_LAYER_NAME


def polygon_feature_set(
    polygons: list[shapely.Polygon],
    names: list[str],
    abbreviations: list[str],
) -> arcgis.features.FeatureSet:
    """Build an ArcGIS FeatureSet from polygon geometries in WGS84.

    Args:
        polygons: Boundary polygons expressed in WGS84.
        names: Administrative names aligned with the polygon sequence.
        abbreviations: Optional state abbreviations aligned with the polygons.

    Returns:
        A FeatureSet whose features carry the named polygons in WGS84.
    """
    features = []
    for polygon, name, abbreviation in zip(polygons, names, abbreviations, strict=True):
        rings = [[list(coordinate) for coordinate in polygon.exterior.coords]]
        features.append(
            arcgis.features.Feature(
                geometry={"rings": rings, "spatialReference": {"wkid": 4326}},
                attributes={"STATE_NAME": name, "STATE_ABBR": abbreviation},
            ),
        )
    return arcgis.features.FeatureSet(features)


def good_border_dataframe() -> geopandas.GeoDataFrame:
    """Return the border GeoDataFrame for the sample neighboring states.

    Returns:
        The three shared borders in WGS84 with the expected columns.
    """
    neighbors = geopandas.GeoDataFrame(
        {
            "STATE_NAME": ["Arizona", "Nevada", "Oregon"],
            "STATE_ABBR": ["AZ", "NV", "OR"],
        },
        geometry=[ARIZONA, NEVADA, OREGON],
        crs=pyproj.CRS.from_epsg(4326),
    )
    return peri_scribe.sources.borders.border_dataframe(CALIFORNIA, neighbors)


def is_usable_dataframe(
    *,
    geometry: list[shapely.Geometry | None],
    crs: object | None = pyproj.CRS.from_epsg(4326),
) -> geopandas.GeoDataFrame:
    """Build a candidate border dataframe for the is_usable checks.

    Args:
        geometry: The border line geometries.
        crs: The dataframe's CRS, or None to omit it.

    Returns:
        The GeoDataFrame with the expected border columns.
    """
    return geopandas.GeoDataFrame(
        {
            "NEIGHBOR": ["Arizona", "Nevada", "Oregon"],
            "NEIGHBOR_ABBR": ["AZ", "NV", "OR"],
            "LENGTH_KM": [1.0, 2.0, 3.0],
        },
        geometry=geometry,
        crs=crs,
    )


def california_like_border() -> shapely.geometry.MultiLineString:
    """Return a synthetic border shaped like California's interstate border.

    Returns:
        An Oregon segment across the top and a Nevada/Arizona segment down the east.
    """
    return shapely.geometry.MultiLineString([
        shapely.geometry.LineString([(-124.0, 42.0), (-120.0, 42.0)]),
        shapely.geometry.LineString([(-120.0, 42.0), (-114.0, 32.7)]),
    ])
