"""Render historical pipeline performance in compatible image-capable terminals."""

import base64
import compression.zstd
import datetime
import pathlib
import re
import sqlite3
import sys
import typing

import click

import peri_scribe.cli_options
import peri_scribe.show_latencies.perimeters
import peri_scribe.show_latencies.runs
import peri_scribe.terminal_images
import svg_charts.cumulative


SECONDS_PER_UNIT = {"ms": 0.001, "s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


class RelativeTime(click.ParamType):
    """One nonpositive relative duration avoids ambiguous compound expressions."""

    name = "offset"

    @typing.override
    def convert(
        self,
        value: object,
        param: click.Parameter | None,
        ctx: click.Context | None,
    ) -> datetime.timedelta:
        """Accept one negative number and a fixed-length unit suffix.

        Args:
            value: A user-supplied relative duration.
            param: The option being converted.
            ctx: The current command invocation.

        Returns:
            Its signed offset from the invocation's clock reading.
        """
        match = re.fullmatch(r"-(\d+(?:\.\d+)?)(ms|s|m|h|d|w)", str(value))
        if match:
            try:
                return -datetime.timedelta(
                    seconds=float(match[1]) * SECONDS_PER_UNIT[match[2]],
                )
            except OverflowError:
                pass
        return self.fail(
            "use one nonpositive offset, such as -3h or -7d (units: ms, s, m, h, d, w)",
            param,
            ctx,
        )


def inline_image(png: bytes, dimensions: tuple[str, str] | None = None) -> str:
    """Encode a PNG using the OSC 1337 inline-image protocol.

    Args:
        png: The complete rendered image.
        dimensions: Terminal width and height controls, or the PNG dimensions.

    Returns:
        One terminal escape sequence, without diagnostic text.
    """
    name = base64.b64encode(b"performance.png").decode("ascii")
    if dimensions is None:
        dimensions = (
            f"{int(svg_charts.cumulative.CDF_CHART_WIDTH.m_as('pixels'))}px",
            f"{int(svg_charts.cumulative.CDF_CHART_HEIGHT.m_as('pixels'))}px",
        )
    width, height = dimensions
    return (
        f"\033]1337;File=name={name};size={len(png)};inline=1;"
        f"width={width};height={height};preserveAspectRatio=1:"
        f"{base64.b64encode(png).decode('ascii')}\a"
    )


def render(
    year_directory: pathlib.Path,
    window: peri_scribe.show_latencies.runs.Window,
) -> bytes:
    """Build the chart independently of terminal transport and the current clock.

    Args:
        year_directory: Retained logs and source data.
        window: Explicit inclusive bounds for reproducible analysis.

    Returns:
        A combined CDF chart encoded as PNG.

    Raises:
        ValueError: No finished runs fall inside the measurement window.
    """
    evidence = peri_scribe.show_latencies.runs.read(year_directory / "logs", window)
    if not evidence.runs:
        message = "No completed runs in the requested time window."
        raise ValueError(message)
    latencies = peri_scribe.show_latencies.perimeters.latencies(
        year_directory,
        evidence,
        window,
    )
    return svg_charts.cumulative.png(
        (
            svg_charts.cumulative.Series(
                label="All pipeline runs",
                durations=tuple(
                    run.duration for run in evidence.runs if run.started >= window.start
                ),
                color="#60a5fa",
            ),
            svg_charts.cumulative.Series(
                label="Source publication → end of KMZ-producing run",
                durations=latencies,
                color="#2dd4bf",
            ),
        ),
        f"{window.start:%Y-%m-%d %H:%M:%S %Z}  —  {window.end:%Y-%m-%d %H:%M:%S %Z}",
    )


@click.command(
    "show-latencies",
    help=(
        "Display run-time and source-to-KMZ CDFs inline in compatible terminals. "
        + peri_scribe.cli_options.year_directory_default_help()
    ),
)
@click.argument(
    "year_directory",
    type=click.Path(path_type=pathlib.Path, file_okay=False),
    required=False,
    callback=peri_scribe.cli_options.command_year_directory,
)
@click.option(
    "--start",
    type=RelativeTime(),
    default="-7d",
    show_default=True,
    help="Inclusive start relative to now; one number and ms/s/m/h/d/w.",
)
@click.option(
    "--end",
    type=RelativeTime(),
    default="-0d",
    show_default=True,
    help="Inclusive end relative to the same clock reading.",
)
def show_latencies(
    year_directory: pathlib.Path,
    start: datetime.timedelta,
    end: datetime.timedelta,
) -> None:
    """Keep logs and source data read-only while sending only the image to stdout.

    Args:
        year_directory: Retained production logs, sources, and full geography.
        start: Nonpositive offset to the beginning of the window.
        end: Nonpositive offset to the end of the window.

    Raises:
        click.ClickException: No completed runs or insufficient readable evidence.
        click.UsageError: The start is not earlier than the end.
    """
    if start >= end:
        message = "--start must be earlier than --end"
        raise click.UsageError(message)
    now = datetime.datetime.now(datetime.UTC)
    try:
        window = peri_scribe.show_latencies.runs.Window(
            start=(now + start).astimezone(),
            end=(now + end).astimezone(),
        )
        image = render(year_directory, window)
    except (
        OSError,
        EOFError,
        ValueError,
        KeyError,
        sqlite3.Error,
        compression.zstd.ZstdError,
        OverflowError,
    ) as error:
        message = f"Cannot build performance chart: {error}"
        raise click.ClickException(message) from error
    # Click's ANSI stripping can remove OSC sequences when stdout is redirected.
    dimensions = peri_scribe.terminal_images.display_dimensions(
        sys.stdout,
        svg_charts.cumulative.CDF_CHART_WIDTH,
        (
            svg_charts.cumulative.CDF_CHART_WIDTH
            / svg_charts.cumulative.CDF_CHART_HEIGHT
        ).magnitude,
    )
    click.echo("\r" + inline_image(image, dimensions), color=True)
