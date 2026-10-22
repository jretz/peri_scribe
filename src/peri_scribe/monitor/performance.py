"""Draw completed command durations from the monitor's recent structural evidence.

The fixed 48-hour time axis and adaptive duration bins use the same valid samples.
Terminal cells quantize observations, so several durations can share one line segment.

Algorithm reasoning and contracts:
[Charts](../../../docs/algorithms/monitor-presentation.md#performance-charts)
"""

import bisect
import dataclasses
import datetime
import itertools
import math
import operator
import textwrap
import zoneinfo

import pint

import peri_scribe.monitor.history
import peri_scribe.monitor.model
import peri_scribe.monitor.performance_types
from measurement_units import units


CHART_HEIGHT = 8
MINIMUM_HISTOGRAM_BINS = 8
MAXIMUM_HISTOGRAM_BINS = 40
TIMING_RESOLUTION = 0.01 * units.seconds
MINIMUM_WIDTH = 24
DATED_TICKS_WIDTH = 31
PACIFIC_TIME_ZONE = zoneinfo.ZoneInfo("America/Los_Angeles")
LINE_CHARACTERS = " ╵╶└╷│┌├╴┘─┴┐┤┬┼"


@dataclasses.dataclass(frozen=True, kw_only=True)
class Sample:
    """One successful command completion supplies its recorded elapsed duration."""

    finished: datetime.datetime
    duration: pint.Quantity


@dataclasses.dataclass(frozen=True, kw_only=True)
class Series:
    """Each execution mode has a chronological collection of valid completions."""

    command: str
    samples: tuple[Sample, ...]


@dataclasses.dataclass(frozen=True, kw_only=True)
class Bin:
    """Duration intervals include their lower edge and the final bin's upper edge."""

    lower: pint.Quantity
    upper: pint.Quantity
    count: int


def duration(fields: object) -> pint.Quantity | None:
    """Omit damaged timings instead of showing invented zero-duration runs.

    Args:
        fields: The completion record's optional duration metadata.

    Returns:
        A finite nonnegative scalar quantity in seconds, or None for unusable metadata.
    """
    if not isinstance(fields, dict):
        return None
    value = fields.get("value")
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        return None
    try:
        elapsed = units.Quantity(value, fields["units"]).to("seconds")
        return (
            elapsed
            if math.isfinite(float(elapsed.magnitude)) and elapsed.magnitude >= 0
            else None
        )
    except KeyError, TypeError, ValueError, OverflowError, pint.errors.PintError:
        return None


def prepare(
    state: peri_scribe.monitor.model.State,
    now: datetime.datetime,
) -> tuple[Series, ...]:
    """Group successful completions in the inclusive rolling observation window.

    Args:
        state: Compact health history, which retains every recent command completion.
        now: The aware observation time shared by both ends of the 48-hour window.

    Returns:
        Fetch-only modes first, then remaining modes alphabetically, each containing
        chronological valid samples. Failed, unfinished, undated, and future completions
        do not contribute samples.
    """
    commands: dict[str, list[Sample]] = {}
    since = now - peri_scribe.monitor.history.WINDOW
    for run in state.runs:
        command = peri_scribe.monitor.performance_types.run_type(run)
        for event in peri_scribe.monitor.model.evidence(run):
            if (
                event.message != "Finished command"
                or event.fields.get("status") != "completed"
                or event.timestamp is None
                or not since <= event.timestamp <= now
            ):
                continue
            elapsed = duration(event.fields.get("duration"))
            if elapsed is not None:
                commands.setdefault(command, []).append(
                    Sample(finished=event.timestamp, duration=elapsed),
                )
    return tuple(
        Series(
            command=command,
            samples=tuple(sorted(samples, key=operator.attrgetter("finished"))),
        )
        for command, samples in sorted(
            commands.items(),
            key=lambda item: (not item[0].startswith("Fetch only"), item[0]),
        )
    )


def upper_bound(samples: tuple[Sample, ...]) -> pint.Quantity:
    """Keep the duration axis useful when every measured duration is zero.

    Args:
        samples: At least one valid duration observation.

    Returns:
        The greatest duration, or one second when all observations are zero.
    """
    maximum = max(sample.duration for sample in samples)
    return maximum if maximum > 0 * units.seconds else 1 * units.seconds


def histogram_bounds(
    samples: tuple[Sample, ...],
) -> tuple[pint.Quantity, pint.Quantity]:
    """Use the observed range while giving identical durations a containing interval.

    Args:
        samples: At least one finite nonnegative duration observation.

    Returns:
        Minimum and maximum durations. Uniform data uses the preceding hundredth of a
        second, bounded by zero; zero-only data spans zero to one hundredth of a second.
        At large magnitudes the preceding representable value supplies a positive span.
    """
    minimum = min(sample.duration for sample in samples).to("seconds")
    maximum = max(sample.duration for sample in samples).to("seconds")
    if minimum < maximum:
        return minimum, maximum
    if maximum == 0 * units.seconds:
        return maximum, TIMING_RESOLUTION
    minimum = max(0 * units.seconds, maximum - TIMING_RESOLUTION)
    if minimum == maximum:
        minimum = math.nextafter(float(maximum.magnitude), 0) * units.seconds
    return minimum, maximum


def histogram_bin_count(samples: tuple[Sample, ...], spread: pint.Quantity) -> int:
    """Add detail when both the sample population and measured spread support it.

    Args:
        samples: At least one finite nonnegative duration observation.
        spread: Positive width of the histogram's duration range.

    Returns:
        One to forty bins, bounded by distinct durations and hundredth-second intervals.
        Varied data starts with up to eight bins; square-root population growth can add
        more. A narrow range or sparse population reduces the requested detail.
    """
    distinct = len({float(sample.duration.m_as("seconds")) for sample in samples})
    population = max(MINIMUM_HISTOGRAM_BINS, math.ceil(math.sqrt(len(samples))))
    intervals = (
        MAXIMUM_HISTOGRAM_BINS
        if spread >= TIMING_RESOLUTION * MAXIMUM_HISTOGRAM_BINS
        else max(
            1,
            math.floor(
                math.nextafter(float((spread / TIMING_RESOLUTION).magnitude), math.inf),
            ),
        )
    )
    return min(MAXIMUM_HISTOGRAM_BINS, distinct, population, intervals)


def histogram(samples: tuple[Sample, ...]) -> tuple[Bin, ...]:
    """Count every sample once in adaptive equal-width duration intervals.

    Args:
        samples: At least one finite nonnegative duration observation.

    Returns:
        Adjacent bins span the measured range, with positive width for uniform data.
        Internal boundaries belong to the following bin, and the maximum belongs to the
        final bin. Counts use the published edges so rounding cannot assign a boundary
        observation to the interval on its left. Fewer bins are used if floating-point
        spacing would otherwise create coincident boundaries.
    """
    minimum, maximum = histogram_bounds(samples)
    spread = maximum - minimum
    count = histogram_bin_count(samples, spread)
    while True:
        edges = (
            minimum,
            *(minimum + spread * (index / count) for index in range(1, count)),
            maximum,
        )
        if all(first < last for first, last in itertools.pairwise(edges)):
            break
        count -= 1
    counts = [0] * count
    for sample in samples:
        index = min(count - 1, bisect.bisect_right(edges, sample.duration) - 1)
        counts[index] += 1
    return tuple(
        Bin(
            lower=edges[index],
            upper=edges[index + 1],
            count=count,
        )
        for index, count in enumerate(counts)
    )


def duration_text(elapsed: pint.Quantity) -> str:
    """Keep axis values short while stating their unit explicitly.

    Args:
        elapsed: A duration expressed in any time unit.

    Returns:
        A compact duration label in seconds.
    """
    return f"{elapsed.m_as('seconds'):.3g} s"


def vertical_line(canvas: list[list[int]], column: int, first: int, last: int) -> None:
    """Connect neighboring rows so quantized slopes use continuous box-drawing lines.

    Args:
        canvas: Mutable cell connections local to one chart rendering.
        column: The shared horizontal cell index.
        first: One endpoint's row.
        last: The other endpoint's row.
    """
    for row in range(min(first, last), max(first, last)):
        canvas[row][column] |= 4
        canvas[row + 1][column] |= 1


def connect(
    canvas: list[list[int]],
    first: tuple[int, int],
    last: tuple[int, int],
) -> None:
    """Rasterize a straight segment with rounded rows and connected terminal cells.

    Args:
        canvas: Mutable cell connections local to one chart rendering.
        first: The earlier observation's column and row.
        last: The later observation's column and row.
    """
    first_column, first_row = first
    last_column, last_row = last
    if first_column == last_column:
        vertical_line(canvas, first_column, first_row, last_row)
        return
    for column in range(first_column, last_column):
        fraction = (column - first_column) / (last_column - first_column)
        next_fraction = (column + 1 - first_column) / (last_column - first_column)
        row = round(first_row + fraction * (last_row - first_row))
        next_row = round(first_row + next_fraction * (last_row - first_row))
        canvas[row][column] |= 2
        canvas[row][column + 1] |= 8
        vertical_line(canvas, column + 1, row, next_row)


def time_series(series: Series, now: datetime.datetime, width: int) -> tuple[str, ...]:
    """Draw duration against the same fixed 48-hour interval for every execution mode.

    Args:
        series: One execution mode with chronologically ordered valid samples.
        now: The aware observation time used to select the series.
        width: Total available columns, with a minimum of 24.

    Returns:
        Pacific-time labels and continuous line characters without sample markers.
    """
    maximum = upper_bound(series.samples)
    labels = tuple(
        duration_text(maximum * ((CHART_HEIGHT - 1 - row) / (CHART_HEIGHT - 1)))
        for row in range(CHART_HEIGHT)
    )
    margin = max(len(label) for label in labels)
    columns = max(MINIMUM_WIDTH, width) - margin - 2
    since = now - peri_scribe.monitor.history.WINDOW
    points = tuple(
        (
            round(
                ((sample.finished - since) / peri_scribe.monitor.history.WINDOW)
                * (columns - 1),
            ),
            round(
                (1 - float((sample.duration / maximum).magnitude)) * (CHART_HEIGHT - 1),
            ),
        )
        for sample in series.samples
    )
    canvas = [[0] * columns for _ in range(CHART_HEIGHT)]
    for first, last in itertools.pairwise(points):
        connect(canvas, first, last)
    for column, row in points:
        if not canvas[row][column]:
            canvas[row][column] = 10
    result = ["Duration"]
    result.extend(
        f"{labels[row]:>{margin}} │"
        + "".join(LINE_CHARACTERS[connections] for connections in cells)
        for row, cells in enumerate(canvas)
    )
    result.append(" " * (margin + 1) + "└" + "─" * columns)
    tick_format = "%m-%d %H:%M %Z" if columns >= DATED_TICKS_WIDTH else "%H:%M"
    left = since.astimezone(PACIFIC_TIME_ZONE).strftime(tick_format)
    right = now.astimezone(PACIFIC_TIME_ZONE).strftime(tick_format)
    result.extend(
        (
            " " * (margin + 2) + left + right.rjust(columns - len(left)),
            " " * (margin + 2) + "Completion time (Pacific) · last 48 hours",
        ),
    )
    return tuple(result)


def histogram_lines(samples: tuple[Sample, ...], width: int) -> tuple[str, ...]:
    """Show exact counts beside bars so sparse bins remain readable.

    Args:
        samples: At least one valid completion duration.
        width: Total available columns, with a minimum of 24.

    Returns:
        Equal-width duration ranges with proportional horizontal bars and counts.
    """
    bins = histogram(samples)
    interval = float((bins[0].upper - bins[0].lower).m_as("seconds"))
    maximum = float(bins[-1].upper.m_as("seconds"))
    precision = min(
        17,
        max(3, math.floor(math.log10(maximum)) - math.floor(math.log10(interval)) + 2),
    )
    labels = tuple(
        f"{item.lower.m_as('seconds'):.{precision}g} s, "
        f"{item.upper.m_as('seconds'):.{precision}g} s"
        f"{']' if index == len(bins) - 1 else ')'}"
        for index, item in enumerate(bins)
    )
    margin = max(len(label) for label in labels)
    largest_count = max(item.count for item in bins)
    columns = max(1, max(MINIMUM_WIDTH, width) - margin - len(str(largest_count)) - 3)
    return (
        "Histogram",
        *(
            f"{'[' + label:>{margin + 1}} "
            + "━" * round(item.count / largest_count * columns)
            + f" {item.count}"
            for label, item in zip(labels, bins, strict=True)
        ),
    )


def render(series: tuple[Series, ...], now: datetime.datetime, width: int) -> str:
    """Prepare all performance charts without consulting or mutating terminal widgets.

    Args:
        series: Execution modes in display order containing valid timings.
        now: The aware observation time used to prepare the samples.
        width: Available terminal columns, with a minimum of 24 for readable axes.

    Returns:
        Plain multiline text for the complete performance view, or an empty-state
        message.
    """
    columns = max(MINIMUM_WIDTH, width)
    if not series:
        return textwrap.fill(
            "No timing data in the last 48 hours.",
            width=columns,
        )
    content = "\n\n".join(
        "\n".join(
            (
                item.command,
                *time_series(item, now, width),
                "",
                *histogram_lines(item.samples, width),
            ),
        )
        for item in series
    )

    return "\n".join(
        textwrap.fill(line, width=columns) if len(line) > columns else line
        for line in content.splitlines()
    )
