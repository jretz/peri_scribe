"""Load the interactive observer only when its command is selected."""

import pathlib

import click

import peri_scribe.cli_options
import peri_scribe.monitor.app
import peri_scribe.paths
import peri_scribe.sources.catalog


@click.command(
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
