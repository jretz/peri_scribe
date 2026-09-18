"""CLI entry point for peri_scribe — fetch and symbolize fire geography."""

from __future__ import annotations

import importlib
import importlib.metadata
import pathlib
import typing

import click

import peri_scribe.cli_options
import peri_scribe.logging
import peri_scribe.monitor.app
import peri_scribe.paths
import peri_scribe.sources.catalog


PIPELINE_COMMANDS = {
    "run": "run",
    "show-colormap": "show_colormap",
    "validate-sources": "validate_sources",
}


class Commands(click.Group):
    """Observers can start without importing source retrieval and output generation."""

    @typing.override
    def list_commands(self, ctx: click.Context) -> list[str]:
        """Keep every command discoverable in help and shell completion.

        Args:
            ctx: The current command-line invocation.

        Returns:
            Registered and deferred command names in alphabetical order.
        """
        return sorted({*super().list_commands(ctx), *PIPELINE_COMMANDS})

    @typing.override
    def get_command(self, ctx: click.Context, cmd_name: str) -> click.Command | None:
        """Load pipeline implementations when Click resolves their command.

        Args:
            ctx: The current command-line invocation.
            cmd_name: The command being selected or described.

        Returns:
            Its command definition, or None for an unknown name.
        """
        if cmd_name in PIPELINE_COMMANDS:
            module = importlib.import_module("peri_scribe.pipeline")
            return typing.cast(
                "click.Command",
                getattr(module, PIPELINE_COMMANDS[cmd_name]),
            )
        return super().get_command(ctx, cmd_name)


@click.group(cls=Commands)
@click.option(
    "--stderr-log-level",
    type=click.Choice(
        ["debug", "info", "warning", "error", "critical"],
        case_sensitive=False,
    ),
    default="debug",
    show_default=True,
    help="Minimum logging level for formatted stderr output.",
)
@click.option(
    "--file-log-level",
    type=click.Choice(
        ["debug", "info", "warning", "error", "critical"],
        case_sensitive=False,
    ),
    default="debug",
    show_default=True,
    help="Minimum logging level for monthly JSON files in YEAR_DIRECTORY/logs.",
)
def cli(stderr_log_level: str, file_log_level: str) -> None:
    """Support systematic gathering and symbolization of fire geography.

    Use the collected geography for fire behavior analysis and presentation.

    Args:
        stderr_log_level: Minimum severity for console logging.
        file_log_level: Minimum severity for persistent command logs.
    """
    peri_scribe.logging.configure_logging(stderr_log_level, file_log_level)


@cli.command(
    help="Observe live logs, pipeline phases, run history, and the current report. "
    + peri_scribe.cli_options.year_directory_default_help(),
)
@click.argument(
    "year_directory",
    type=click.Path(path_type=pathlib.Path, file_okay=False),
    required=False,
    callback=peri_scribe.cli_options.command_year_directory,
)
def monitor(year_directory: pathlib.Path) -> None:
    """Observe a year directory without writing logs or acquiring the pipeline lock.

    Args:
        year_directory: The resolved directory whose logs and report should be watched.
    """
    peri_scribe.monitor.app.MonitorApp(
        year_directory,
        peri_scribe.paths.markdown_report_path(year_directory),
        peri_scribe.sources.catalog.configured_phase_branches(),
    ).run()


def distribution_version() -> str:
    """Return the installed peri_scribe distribution's version.

    ``__package__`` names the package this module belongs to, and the distribution is
    installed under that same name, so it supplies the metadata lookup name without
    repeating it in source here. The version comes from the installed distribution's
    metadata rather than from source, so it cannot drift from the released version.

    Returns:
        The installed distribution's version string.

    Raises:
        RuntimeError: If the module was not imported as part of its package, so the
            distribution name is unknown.
    """
    if __package__ is None:
        message = (
            "the installed distribution name is unknown because this module was "
            "not imported as part of its package"
        )
        raise RuntimeError(message)
    version = importlib.metadata.version(__package__)
    return f"{__package__} v{version}"


@cli.command()
def version() -> None:
    """Print the installed peri_scribe version."""
    click.echo(distribution_version())
