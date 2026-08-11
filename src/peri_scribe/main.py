"""CLI entry point for peri_scribe — fetch and symbolize fire geography."""

from __future__ import annotations

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
    """Fetch all configured feeds into a single GeoPackage."""
    peri_scribe.operations.fetch_all_feeds()


@cli.command()
def feed_config() -> None:
    """Print the configured feeds."""
    for i, feed in enumerate(peri_scribe.models.FEEDS):
        logger.info("Feed %d", i + 1, name=feed.name, url=feed.url)


if __name__ == "__main__":
    cli()
