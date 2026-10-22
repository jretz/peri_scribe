"""Shared command paths keep monitoring and pipeline arguments consistent."""

from __future__ import annotations

import dataclasses
import datetime
import math
import pathlib
import re
import typing

import click
import pint

import peri_scribe.paths
import peri_scribe.pipeline_stages
from measurement_units import units


@dataclasses.dataclass(frozen=True, kw_only=True)
class PublicationThreshold:
    """Keep parsed physical thresholds independent of the pipeline's heavy imports."""

    area: pint.Quantity[float]
    interval: datetime.timedelta


def default_year_directory() -> pathlib.Path:
    """Return the current year's data directory under the working directory.

    Returns:
        The path to ``data/<current year>`` under the current working directory.
    """
    return peri_scribe.paths.year_directory_path(
        pathlib.Path.cwd(),
        datetime.date.today().year,
    )


def command_year_directory(
    _context: click.Context,
    _parameter: click.Parameter,
    value: pathlib.Path | None,
) -> pathlib.Path:
    """Resolve the command's directory before its first log entry.

    Args:
        _context: The command's Click context.
        _parameter: The year-directory argument being parsed.
        value: The explicitly supplied directory, or None to use the current year.

    Returns:
        The directory shared by pipeline data and command logs.
    """
    return value if value is not None else default_year_directory()


def year_directory_default_help() -> str:
    """Return the help sentence naming the default year directory.

    The default moves forward each new year, so the sentence names the current year.

    Returns:
        The sentence naming the default year directory.
    """
    return (
        f"YEAR_DIRECTORY defaults to "
        f"{peri_scribe.paths.DATA_DIRECTORY}/"
        f"{datetime.date.today().year}."
    )


class Duration(click.ParamType):
    """A duration of whole minutes, hours or days.

    Values are a non-negative whole number followed by ``m``, ``h`` or ``d``, for
    example ``5m``, ``12h`` or ``1d``, and convert to a ``datetime.timedelta``.
    """

    name = "duration"

    def convert(
        self,
        value: object,
        param: click.Parameter | None,
        ctx: click.Context | None,
    ) -> datetime.timedelta:
        """Return *value* converted to a ``datetime.timedelta``.

        Strings use the duration syntax described above. An already-converted
        ``datetime.timedelta`` passes through unchanged, so the type also works with
        timedelta defaults.

        Args:
            value: The option value to convert.
            param: The parameter the value came from.
            ctx: The click context.

        Returns:
            The parsed duration.
        """
        if isinstance(value, datetime.timedelta):
            return value
        message = (
            f"{value!r} is not a duration of whole minutes, hours or days "
            "such as '5m', '12h' or '1d'"
        )
        if not isinstance(value, str):
            self.fail(message, param, ctx)
        duration_match = re.fullmatch(r"([0-9]+)([mhd])", value)
        if duration_match is None:
            self.fail(message, param, ctx)
        count = int(duration_match.group(1))
        try:
            if duration_match.group(2) == "m":
                return datetime.timedelta(minutes=count)
            if duration_match.group(2) == "h":
                return datetime.timedelta(hours=count)
            return datetime.timedelta(days=count)
        except OverflowError:
            self.fail(f"{value!r} is too large to be a duration", param, ctx)


class Area(click.ParamType):
    """Require a positive finite area with explicit physical units."""

    name = "area"

    def convert(
        self,
        value: object,
        param: click.Parameter | None,
        ctx: click.Context | None,
    ) -> pint.Quantity[float]:
        """Reject unitless and non-area values before the pipeline can write data.

        Args:
            value: The command-line area value, including its physical units.
            param: The Click parameter used to report validation errors, if available.
            ctx: The Click invocation context, if available.

        Returns:
            The positive area converted to square meters.
        """
        message = f"{value!r} is not a positive area such as '25 acre'"
        if not isinstance(value, (str, pint.Quantity)):
            self.fail(message, param, ctx)
        try:
            area = units.Quantity(value).to("meters ** 2")
        except pint.errors.PintError, TypeError, ValueError:
            self.fail(message, param, ctx)
        if not math.isfinite(area.magnitude) or area.magnitude <= 0:
            self.fail(message, param, ctx)
        return typing.cast("pint.Quantity[float]", area)


def publication_threshold(
    _context: click.Context,
    _parameter: click.Parameter,
    value: tuple[pint.Quantity[float], datetime.timedelta] | None,
) -> PublicationThreshold | None:
    """Validate the area and time settings as one publication policy.

    Args:
        _context: The invocation context supplied by Click; unused by this callback.
        _parameter: The option supplied by Click; unused by this callback.
        value: The parsed area and duration, or None when the option was omitted.

    Returns:
        The configured policy, or None when the option was omitted.

    Raises:
        click.BadParameter: If the publication interval is not positive.
    """
    if value is None:
        return None
    area, interval = value
    if interval <= datetime.timedelta(0):
        message = "The publication interval must be positive"
        raise click.BadParameter(message)
    return PublicationThreshold(area=area, interval=interval)


@dataclasses.dataclass(frozen=True, kw_only=True)
class PipelineStage:
    """A named pipeline stage and its description."""

    name: peri_scribe.pipeline_stages.Stage
    description: str


PIPELINE_STAGES: tuple[PipelineStage, ...] = (
    PipelineStage(
        name=peri_scribe.pipeline_stages.Stage.FETCH,
        description=(
            "Fetch fire feeds, external sources (buildings, evacuations, and "
            "Natural Earth places), and the administrative-boundary GeoPackage."
        ),
    ),
    PipelineStage(
        name=peri_scribe.pipeline_stages.Stage.GEOGRAPHY,
        description="Derive fire geography histories from the fetched sources.",
    ),
    PipelineStage(
        name=peri_scribe.pipeline_stages.Stage.SCORE,
        description="Score fires from the derived geography.",
    ),
    PipelineStage(
        name=peri_scribe.pipeline_stages.Stage.KMZ,
        description="Build the symbolized KMZ for Google Earth.",
    ),
    PipelineStage(
        name=peri_scribe.pipeline_stages.Stage.REPORTS,
        description="Write fire reports from the derived outputs.",
    ),
)


STAGE_NAMES = tuple(stage.name.value for stage in PIPELINE_STAGES)


STAGE_INDEX = {stage.name: index for index, stage in enumerate(PIPELINE_STAGES)}


def print_stages() -> None:
    """Print the pipeline stages and their descriptions."""
    width = max(len(stage.name) for stage in PIPELINE_STAGES)
    for stage in PIPELINE_STAGES:
        click.echo(f"{stage.name:<{width}}  {stage.description}")


def selected_stage_range(
    only_stage: str | None,
    from_stage: str | None,
    to_stage: str | None,
) -> tuple[int, int]:
    """Return the inclusive indexes of the pipeline stages to run.

    Args:
        only_stage: The single stage to run, or None to use ``from_stage``/``to_stage``.
        from_stage: The first stage to run, or None for the first pipeline stage.
        to_stage: The last stage to run, or None for the last pipeline stage.

    Returns:
        A ``(start, end)`` pair of inclusive indexes into ``PIPELINE_STAGES``.

    Raises:
        click.UsageError: When ``from_stage`` comes after ``to_stage``.
    """
    if only_stage is not None:
        index = STAGE_INDEX[peri_scribe.pipeline_stages.Stage(only_stage)]
        return index, index
    start = (
        STAGE_INDEX[peri_scribe.pipeline_stages.Stage(from_stage)]
        if from_stage is not None
        else 0
    )
    end = (
        STAGE_INDEX[peri_scribe.pipeline_stages.Stage(to_stage)]
        if to_stage is not None
        else len(PIPELINE_STAGES) - 1
    )
    if start > end:
        message = (
            f"--from {from_stage or PIPELINE_STAGES[0].name} cannot follow "
            f"--to {to_stage or PIPELINE_STAGES[-1].name}"
        )
        raise click.UsageError(message)
    return start, end
