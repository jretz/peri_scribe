"""CLI entry point for peri_scribe — fetch and symbolize fire geography."""

from __future__ import annotations

import pathlib

import click
import structlog

import peri_scribe.models
import peri_scribe.operations
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
    """
    A tool for systematic gathering and symbolization of fire geography, for use in fire
    behavior analysis and presentation.
    """
    peri_scribe.output.configure_logging(log_level)


@cli.command()
def fetch() -> None:
    """Fetch each configured feed into a GeoPackage."""
    peri_scribe.operations.fetch_all_feeds()


@cli.command()
def feed_config() -> None:
    """Print the configured feeds."""
    for i, feed in enumerate(peri_scribe.models.FEEDS):
        logger.info(
            "Feed %d",
            i + 1,
            feed_type=type(feed).__name__,
            name=feed.name,
            url=feed.url,
        )


@cli.command()
def current_watermarks() -> None:
    """Log the current watermark for each configured feed."""
    for index, feed in enumerate(peri_scribe.models.FEEDS, start=1):
        logger.info(
            "Feed %d",
            index,
            name=feed.name,
            url=feed.url,
            watermark=feed.current_watermark,
        )


@cli.command()
@click.argument(
    "directory",
    type=click.Path(
        path_type=pathlib.Path,
        exists=True,
        file_okay=False,
        dir_okay=True,
    ),
)
def list_fires(directory: pathlib.Path) -> None:
    """Log the name, status, and identifier of each fire.

    Reads every GeoPackage file anywhere below DIRECTORY.
    """
    for index, fire in enumerate(
        peri_scribe.operations.list_fires(directory),
        start=1,
    ):
        logger.info(
            "Fire %d",
            index,
            name=fire.name,
            status=fire.status.value,
            identifier=fire.identifier,
        )


if __name__ == "__main__":
    cli()
