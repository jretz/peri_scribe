"""Orchestration logic for peri_scribe — feed fetching, fire listing, output writing.

This module contains the core business logic shared across all user interfaces.
"""

from __future__ import annotations

import collections
import pathlib

import arcgis.features
import arcgis.gis
import structlog

import peri_scribe.exceptions
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


def list_fires(
    geo_package_paths: tuple[pathlib.Path, ...],
) -> list[peri_scribe.models.Fire]:
    """Collect the fires in the given GeoPackage files into a list.

    Fire names are deduplicated by name, ignoring case; the most common spelling
    of each name is the one kept. A fire is active when any of its records is
    active.

    Args:
        geo_package_paths: Paths to GeoPackage files containing fire data.

    Returns:
        The fires, in the order first encountered.

    Raises:
        SystemExit: If a GeoPackage file cannot be read.
        UnknownLayerError: If a layer does not correspond to a configured feed.
    """
    fires_by_case_folded_name: dict[str, list[peri_scribe.models.Fire]] = {}
    for path in geo_package_paths:
        try:
            for fire in peri_scribe.geo_data.fire_names(path):
                fires_by_case_folded_name.setdefault(
                    fire.name.casefold(),
                    [],
                ).append(fire)
        except peri_scribe.exceptions.UnknownLayerError:
            raise
        except Exception as error:
            # Fail fast with a readable message if a GeoPackage is unreadable.
            message = f"Failed to read {path}: {error}"
            raise SystemExit(message) from error
    return [most_common_fire(fires) for fires in fires_by_case_folded_name.values()]


def is_mixed_case(name: str) -> bool:
    """Return whether *name* contains both uppercase and lowercase letters.

    Args:
        name: The name to check.

    Returns:
        True when the name contains both uppercase and lowercase letters.
    """
    return name.lower() != name and name.upper() != name


def most_common_fire(
    occurrences: list[peri_scribe.models.Fire],
) -> peri_scribe.models.Fire:
    """Reduce repeated records of the same fire to a single fire.

    The most common mixed case spelling of the name is kept, or the most common
    spelling when none is mixed case. Ties are broken by the first spelling
    encountered. The fire is active when any of its records is active.

    Args:
        occurrences: The records of a single fire, deduplicated by case-folded
            name.

    Returns:
        The fire with its preferred name spelling and aggregated status.
    """
    name_counts = collections.Counter(
        fire.name for fire in occurrences if is_mixed_case(fire.name)
    )
    if not name_counts:
        name_counts = collections.Counter(fire.name for fire in occurrences)
    most_common_name = name_counts.most_common(1)[0][0]
    status = (
        peri_scribe.models.FireStatus.ACTIVE
        if any(
            fire.status is peri_scribe.models.FireStatus.ACTIVE for fire in occurrences
        )
        else peri_scribe.models.FireStatus.INACTIVE
    )
    return peri_scribe.models.Fire(name=most_common_name, status=status)
