"""CLI entry point for peri_scribe — fetch and symbolize fire geography."""

from __future__ import annotations

import importlib
import importlib.metadata
import typing

import click

import peri_scribe.logging


DEFERRED_COMMANDS = {
    "run": ("peri_scribe.pipeline", "run"),
    "show-colormap": ("peri_scribe.pipeline", "show_colormap"),
    "validate-sources": ("peri_scribe.pipeline", "validate_sources"),
    "show-latencies": ("peri_scribe.show_latencies.cli", "show_latencies"),
    "monitor": ("peri_scribe.monitor.cli", "monitor"),
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
        return sorted({*super().list_commands(ctx), *DEFERRED_COMMANDS})

    @typing.override
    def get_command(self, ctx: click.Context, cmd_name: str) -> click.Command | None:
        """Load pipeline implementations when Click resolves their command.

        Args:
            ctx: The current command-line invocation.
            cmd_name: The command being selected or described.

        Returns:
            Its command definition, or None for an unknown name.
        """
        if cmd_name in DEFERRED_COMMANDS:
            module_name, function = DEFERRED_COMMANDS[cmd_name]
            module = importlib.import_module(module_name)
            return typing.cast(
                "click.Command",
                getattr(module, function),
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
