"""CLI entry point for peri_scribe — fetch and symbolize fire geography."""

from __future__ import annotations

import pathlib

import arcgis.features
import arcgis.gis
import click
import structlog

import peri_scribe.geo_data
import peri_scribe.models
import peri_scribe.output


logger = structlog.get_logger()


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
    peri_scribe.output.configure_logging(log_level)


@cli.command()
def fetch() -> None:
    """Fetch all configured feeds into a single GeoPackage.

    Raises:
        SystemExit: If a feed is unreachable.
    """
    output_path = pathlib.Path.cwd() / peri_scribe.models.OUTPUT_FILENAME
    logger.info("Output file", path=output_path)
    gis = arcgis.gis.GIS()
    layers: list[peri_scribe.models.LayerData] = []
    for feed in peri_scribe.models.FEEDS:
        logger.info("Fetching", feed=feed.name, url=feed.url)
        try:
            layer = arcgis.features.FeatureLayer(feed.url, gis)
            feature_set = layer.query()
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


@cli.command()
def feed_config() -> None:
    """Print the configured feeds."""
    for i, feed in enumerate(peri_scribe.models.FEEDS):
        logger.info("Feed %d", i + 1, name=feed.name, url=feed.url)


if __name__ == "__main__":
    cli()
