"""Orchestration logic for peri_scribe — feed fetching and output writing.

This module contains the core business logic shared across all user interfaces.
"""

from __future__ import annotations

import pathlib

import arcgis.features
import arcgis.gis
import structlog

import peri_scribe.geo_data
import peri_scribe.models
import peri_scribe.output


logger = structlog.get_logger()


def fetch_all_feeds(
    output_dir: pathlib.Path | None = None,
) -> pathlib.Path:
    """Fetch all configured feeds and write them to a single GeoPackage.

    Args:
        output_dir: Directory in which to create the output file. Defaults to the
            current working directory.

    Returns:
        The path to the output GeoPackage file.

    Raises:
        SystemExit: If a feed is unreachable.
    """
    if output_dir is None:
        output_dir = pathlib.Path.cwd()
    output_path = output_dir / peri_scribe.models.OUTPUT_FILENAME
    logger.info("Output file", path=output_path)
    gis = arcgis.gis.GIS()
    layers: list[peri_scribe.models.LayerData] = []
    for feed in peri_scribe.models.FEEDS:
        logger.info("Fetching", feed=feed.name, url=feed.url)
        try:
            layer = arcgis.features.FeatureLayer(feed.url, gis)
            feature_set = peri_scribe.geo_data.query_with_retry(
                feed.name,
                layer,
            )
            geodataframe = peri_scribe.geo_data.dataframe_for_layer(
                feed,
                layer,
                feature_set,
            )
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
        layers.append(
            peri_scribe.models.LayerData(name=feed.name, dataframe=geodataframe),
        )
    logger.info("Writing layers", count=len(layers), path=output_path)
    peri_scribe.output.write_geopackage(output_path, layers)
    logger.info("Done")
    return output_path
