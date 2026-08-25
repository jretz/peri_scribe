"""Building the line plots embedded in each fire's KML balloon.

A fire's balloon shows its latest state as a table of facts. Behind that table the
balloon also shows a small chart of how the fire has changed over time, so the
reader can see the growth story rather than a single snapshot. Each chart is a line
plot with observation time on the x-axis and one or more measurements on the y-axis;
the plots are rendered to PNG bytes in memory so they can be written straight into
the KMZ archive without touching the filesystem.

The measurements are read from the fire's history: the perimeter history supplies
the mapped area, perimeter lengths, and cost, while the point history supplies the
incident-reported area and cost. A line is only drawn when its measurement exists
on at least two distinct observation times, because a single point cannot show
growth; a plot whose lines are all dropped is skipped entirely.

Rendering is parallelized across fires with one process pool: every worker
creates its figure, canvas, and output buffer once and clears the figure between
plots, so the expensive setup is shared across all of that worker's plots rather
than rebuilt per plot.
"""

from __future__ import annotations

import contextlib
import dataclasses
import datetime
import io
import math
import multiprocessing
import os
import re
import typing

import matplotlib as mpl
import matplotlib.backends.backend_agg
import matplotlib.dates
import matplotlib.figure
import matplotlib.ticker
import pandas as pd
import seaborn as sns

import peri_scribe.geo_package
import peri_scribe.units


if typing.TYPE_CHECKING:
    import geopandas


# A line is skipped unless its measurement exists on at least this many distinct
# observation times; one point cannot show how a fire grew.
MINIMUM_OBSERVATION_TIMES = 2

# Tick values at or above these magnitudes keep progressively fewer decimals.
TICK_WHOLE_NUMBER_THRESHOLD = 1000.0
TICK_ONE_DECIMAL_THRESHOLD = 10.0

# X-axis tick labels sit only at midnight and are thinned so at most this many fit
# along the figure without crowding.
MAX_X_AXIS_TICKS = 6

# Area and cost are scaled to these units before plotting so their values stay in a
# readable range.
ACRES_PER_THOUSAND = 1_000.0
DOLLARS_PER_MILLION = 1_000_000.0

# Containment percentages are reported in whole percent (0-100), so the contained
# perimeter is that fraction of the exterior perimeter length.
CONTAINMENT_IN_PERCENT = 100.0

# The rendered image dimensions, in inches and dots per inch.
FIGURE_WIDTH_IN_INCHES = 4.8
FIGURE_HEIGHT_IN_INCHES = 3.0
IMAGE_DPI = 100

IMAGE_FORMAT = "png"

DATE_FORMAT = "%m/%d"
X_AXIS_LABEL = "Date"

# Column names in the tidy frame handed to seaborn.
LABEL_COLUMN = "label"
OBSERVATION_TIME_COLUMN = "observation_time"
VALUE_COLUMN = "value"

# The filename suffix for each plot, used to build its image filename.
AREA_PLOT_SUFFIX = "area"
PERIMETER_PLOT_SUFFIX = "perimeter"
COST_PLOT_SUFFIX = "cost"

# The legend label for each line. Units are not part of the label; each plot's unit
# is shown once at its y-axis instead.
AREA_SERIES_LABEL = "Area"
EXTERIOR_PERIMETER_SERIES_LABEL = "Exterior perimeter"
CONTAINED_PERIMETER_SERIES_LABEL = "Contained perimeter"
COST_TO_DATE_SERIES_LABEL = "Cost to date"
ESTIMATED_FINAL_COST_SERIES_LABEL = "Estimated final cost"

# The unit shown at each plot's y-axis.
AREA_AXIS_LABEL = "Thousands of acres"
PERIMETER_AXIS_LABEL = "Miles"
COST_AXIS_LABEL = "Millions of $"

# Pool workers lower their scheduling priority by this niceness increment, as the
# ``nice`` command does, so the batch rendering yields the machine to other work
# while it runs.
WORKER_NICENESS_INCREMENT = 10


@dataclasses.dataclass(frozen=True, kw_only=True)
class SeriesPoint:
    """One measurement at one observation time."""

    observation_time: datetime.datetime
    value: float


@dataclasses.dataclass(frozen=True, kw_only=True)
class PlotSeries:
    """One line to draw: a label and its measurements over time."""

    label: str
    points: tuple[SeriesPoint, ...]


@dataclasses.dataclass(frozen=True, kw_only=True)
class FirePlot:
    """One plot for a fire: its lines, axis label, and the filename suffix."""

    filename_suffix: str
    series: tuple[PlotSeries, ...]
    y_axis_label: str


@dataclasses.dataclass(frozen=True, kw_only=True)
class PlotImage:
    """One rendered plot: its filename and PNG bytes."""

    filename: str
    content: bytes


@dataclasses.dataclass(frozen=True, kw_only=True)
class PlotRenderer:
    """The rendering setup one worker reuses for every plot it draws.

    The figure's dimensions and dpi, the canvas, and the output buffer are the
    same for every plot a worker renders, so a pool worker creates them once
    and clears the figure between plots rather than rebuilding them each time.
    """

    figure: matplotlib.figure.Figure
    buffer: io.BytesIO


@dataclasses.dataclass(frozen=True, kw_only=True)
class PlotRequest:
    """One plot ready to render: which fire it belongs to and its lines.

    A plot is only requested after its lines survived the minimum-observation
    filter, so every request produces exactly one image. The y-axis label is
    per-plot data; the shared setup a worker reuses holds no per-type state.
    """

    fire_index: int
    filename_prefix: str
    filename_suffix: str
    y_axis_label: str
    series: tuple[PlotSeries, ...]


def matching_rows(
    frame: geopandas.GeoDataFrame,
    fire_identifiers: frozenset[str],
    entry_name: str,
) -> geopandas.GeoDataFrame:
    """Return the rows of *frame* that belong to one fire.

    A fire with identifiers is matched by those identifiers; a fire without any is
    matched by name. The layer's rows are already in chronological order, so the
    result preserves that order.

    Args:
        frame: The history layer to search.
        fire_identifiers: The fire's identifiers.
        entry_name: The fire's name, used when it has no identifiers.

    Returns:
        The matching rows.
    """
    if fire_identifiers:
        return frame[frame["fire_identifier"].isin(sorted(fire_identifiers))]
    return frame[frame["fire_name"] == entry_name]


def series_points(
    frame: geopandas.GeoDataFrame,
    observation_column: str,
    value_column: str,
) -> tuple[SeriesPoint, ...]:
    """Return the (time, value) points of *frame*'s two named columns.

    Rows with a missing observation time or value are left out, since neither can be
    plotted. When either column is absent the layer carries no measurement to plot.

    Args:
        frame: The history layer to read.
        observation_column: The column holding observation times.
        value_column: The column holding the measurement.

    Returns:
        The plotted points, in the layer's row order.
    """
    if observation_column not in frame.columns or value_column not in frame.columns:
        return ()
    points: list[SeriesPoint] = []
    for observation_time, value in zip(
        frame[observation_column],
        frame[value_column],
        strict=True,
    ):
        time = peri_scribe.geo_package.observation_time_from(observation_time)
        number = peri_scribe.geo_package.numeric_value(value)
        if time is not None and number is not None:
            points.append(SeriesPoint(observation_time=time, value=number))
    return tuple(points)


def exterior_perimeter_points(
    frame: geopandas.GeoDataFrame,
) -> tuple[SeriesPoint, ...]:
    """Return each perimeter's exterior length in miles over time.

    Args:
        frame: The perimeter history layer.

    Returns:
        The exterior perimeter points, in the layer's row order.
    """
    if "observation_time" not in frame.columns:
        return ()
    points: list[SeriesPoint] = []
    for observation_time, geometry in zip(
        frame["observation_time"],
        frame.geometry,
        strict=True,
    ):
        time = peri_scribe.geo_package.observation_time_from(observation_time)
        length = peri_scribe.units.exterior_perimeter_in_miles(geometry)
        if time is not None and length is not None:
            points.append(SeriesPoint(observation_time=time, value=length))
    return tuple(points)


def contained_perimeter_points(
    frame: geopandas.GeoDataFrame,
) -> tuple[SeriesPoint, ...]:
    """Return each perimeter's contained length in miles over time.

    The contained length is the exterior perimeter length multiplied by the
    containment percentage, so a perimeter without a percentage has no contained
    length.

    Args:
        frame: The perimeter history layer.

    Returns:
        The contained perimeter points, in the layer's row order.
    """
    if "observation_time" not in frame.columns:
        return ()
    if "percent_contained" not in frame.columns:
        return ()
    points: list[SeriesPoint] = []
    for observation_time, geometry, percent_contained in zip(
        frame["observation_time"],
        frame.geometry,
        frame["percent_contained"],
        strict=True,
    ):
        time = peri_scribe.geo_package.observation_time_from(observation_time)
        length = peri_scribe.units.exterior_perimeter_in_miles(geometry)
        in_percent = peri_scribe.geo_package.numeric_value(percent_contained)
        if time is not None and length is not None and in_percent is not None:
            points.append(
                SeriesPoint(
                    observation_time=time,
                    value=length * in_percent / CONTAINMENT_IN_PERCENT,
                ),
            )
    return tuple(points)


def merge_series_points(
    *sequences: typing.Iterable[SeriesPoint],
) -> tuple[SeriesPoint, ...]:
    """Return every point from *sequences* in chronological order.

    Args:
        sequences: Each sequence of points to combine.

    Returns:
        The combined points, oldest first.
    """
    points = [point for sequence in sequences for point in sequence]
    return tuple(sorted(points, key=lambda point: point.observation_time))


def scaled_points(
    points: tuple[SeriesPoint, ...],
    divisor: float,
) -> tuple[SeriesPoint, ...]:
    """Return *points* with each value divided by *divisor*.

    Args:
        points: The measurements to scale.
        divisor: The value each measurement is divided by.

    Returns:
        The scaled points, in the same order.
    """
    return tuple(
        SeriesPoint(
            observation_time=point.observation_time,
            value=point.value / divisor,
        )
        for point in points
    )


def fire_plots(
    fire_identifiers: frozenset[str],
    entry_name: str,
    perimeters: geopandas.GeoDataFrame,
    points: geopandas.GeoDataFrame,
) -> tuple[FirePlot, ...]:
    """Return the three plots describing one fire's history.

    The area plot has one line, the perimeter plot has exterior and contained
    perimeter lines, and the cost plot has cost-to-date and estimated-final-cost
    lines. Area and cost are read from both the perimeter and point histories, while
    the two perimeter lengths come only from the perimeter history, whose geometry is
    the only source of a length.

    Args:
        fire_identifiers: The fire's identifiers.
        entry_name: The fire's name, used when it has no identifiers.
        perimeters: The perimeter history layer.
        points: The point history layer.

    Returns:
        The fire's plots, in area, perimeter, then cost order.
    """
    perimeter_rows = matching_rows(perimeters, fire_identifiers, entry_name)
    point_rows = matching_rows(points, fire_identifiers, entry_name)

    area_points = scaled_points(
        merge_series_points(
            series_points(perimeter_rows, "observation_time", "area_acres"),
            series_points(point_rows, "observation_time", "incident_size"),
        ),
        ACRES_PER_THOUSAND,
    )
    cost_to_date_points = scaled_points(
        merge_series_points(
            series_points(
                perimeter_rows,
                "observation_time",
                "estimated_cost_to_date",
            ),
            series_points(point_rows, "observation_time", "estimated_cost_to_date"),
        ),
        DOLLARS_PER_MILLION,
    )
    estimated_final_cost_points = scaled_points(
        merge_series_points(
            series_points(
                perimeter_rows,
                "observation_time",
                "estimated_final_cost",
            ),
            series_points(point_rows, "observation_time", "estimated_final_cost"),
        ),
        DOLLARS_PER_MILLION,
    )

    return (
        FirePlot(
            filename_suffix=AREA_PLOT_SUFFIX,
            series=(
                PlotSeries(
                    label=AREA_SERIES_LABEL,
                    points=area_points,
                ),
            ),
            y_axis_label=AREA_AXIS_LABEL,
        ),
        FirePlot(
            filename_suffix=PERIMETER_PLOT_SUFFIX,
            series=(
                PlotSeries(
                    label=EXTERIOR_PERIMETER_SERIES_LABEL,
                    points=exterior_perimeter_points(perimeter_rows),
                ),
                PlotSeries(
                    label=CONTAINED_PERIMETER_SERIES_LABEL,
                    points=contained_perimeter_points(perimeter_rows),
                ),
            ),
            y_axis_label=PERIMETER_AXIS_LABEL,
        ),
        FirePlot(
            filename_suffix=COST_PLOT_SUFFIX,
            series=(
                PlotSeries(
                    label=COST_TO_DATE_SERIES_LABEL,
                    points=cost_to_date_points,
                ),
                PlotSeries(
                    label=ESTIMATED_FINAL_COST_SERIES_LABEL,
                    points=estimated_final_cost_points,
                ),
            ),
            y_axis_label=COST_AXIS_LABEL,
        ),
    )


def has_multiple_observation_times(points: tuple[SeriesPoint, ...]) -> bool:
    """Return whether *points* span at least two distinct observation times.

    Args:
        points: One line's measurements.

    Returns:
        True when the line has enough times to show growth.
    """
    return len({point.observation_time for point in points}) >= (
        MINIMUM_OBSERVATION_TIMES
    )


def retained_series(
    series_list: typing.Iterable[PlotSeries],
) -> tuple[PlotSeries, ...]:
    """Return the series in *series_list* that span enough observation times.

    Args:
        series_list: The lines in a plot.

    Returns:
        The lines to draw, in order.
    """
    return tuple(
        series
        for series in series_list
        if has_multiple_observation_times(series.points)
    )


def plot_frame(series_list: tuple[PlotSeries, ...]) -> pd.DataFrame:
    """Return *series_list* as the tidy frame seaborn plots.

    Args:
        series_list: The lines to draw.

    Returns:
        The lines melted into one row per measurement.
    """
    rows = [
        (series.label, point.observation_time, point.value)
        for series in series_list
        for point in series.points
    ]
    return pd.DataFrame(
        rows,
        columns=[LABEL_COLUMN, OBSERVATION_TIME_COLUMN, VALUE_COLUMN],
    )


def format_tick(value: float, _position: int) -> str:
    """Format one y-axis tick with size-appropriate precision.

    Large values carry thousands separators and no decimals; smaller values keep one
    or two decimals so small measurements do not read as zero. Trailing zeros after
    the decimal point are dropped.

    Args:
        value: The tick value.
        _position: The tick position, unused.

    Returns:
        The formatted tick label.
    """
    magnitude = abs(value)
    if magnitude >= TICK_WHOLE_NUMBER_THRESHOLD:
        text = f"{value:,.0f}"
    elif magnitude >= TICK_ONE_DECIMAL_THRESHOLD:
        text = f"{value:,.1f}"
    else:
        text = f"{value:,.2f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def observation_day_span(
    series_list: tuple[PlotSeries, ...],
) -> tuple[datetime.date, datetime.date]:
    """Return the earliest and latest observation days across *series_list*.

    Args:
        series_list: The lines drawn in the plot.

    Returns:
        The first and last observation days.
    """
    times = [
        point.observation_time for series in series_list for point in series.points
    ]
    return min(times).date(), max(times).date()


def x_axis_ticks(
    series_list: tuple[PlotSeries, ...],
) -> tuple[datetime.datetime, ...]:
    """Return the midnight times at which to place x-axis ticks.

    Ticks sit on a uniform grid of midnights across the observations: each tick is one
    interval after the last, where the interval thins the grid to at most
    ``MAX_X_AXIS_TICKS`` ticks. No tick is forced onto the first or last observation
    day; the axis itself extends to cover them, so the line is never cut off and the
    reader can read any endpoint off the nearest tick.

    Args:
        series_list: The lines drawn in the plot.

    Returns:
        The midnight tick times, oldest first.
    """
    times = [
        point.observation_time for series in series_list for point in series.points
    ]
    if not times:
        return ()
    first_day, last_day = observation_day_span(series_list)
    in_days_spanned = (last_day - first_day).days + 1
    interval = max(1, math.ceil(in_days_spanned / MAX_X_AXIS_TICKS))
    ticks: list[datetime.datetime] = []
    day = first_day
    while day <= last_day:
        ticks.append(
            datetime.datetime.combine(day, datetime.time.min, tzinfo=datetime.UTC),
        )
        day += datetime.timedelta(days=interval)
    return tuple(ticks)


def create_plot_renderer() -> PlotRenderer:
    """Return the rendering setup one worker reuses for every plot it draws.

    The figure's size and dpi, the canvas, and the output buffer are the same
    for every plot a worker renders, so a pool worker creates them once here
    and clears the figure between plots instead of rebuilding them each time.

    Returns:
        The shared rendering setup.
    """
    figure = matplotlib.figure.Figure(
        figsize=(FIGURE_WIDTH_IN_INCHES, FIGURE_HEIGHT_IN_INCHES),
        dpi=IMAGE_DPI,
    )
    matplotlib.backends.backend_agg.FigureCanvasAgg(figure)
    return PlotRenderer(
        figure=figure,
        buffer=io.BytesIO(),
    )


def draw_plot(
    renderer: PlotRenderer,
    series_list: tuple[PlotSeries, ...],
    *,
    y_axis_label: str = "",
) -> bytes:
    """Draw *series_list* on *renderer*'s figure and return its PNG bytes.

    The figure is cleared first, so the same figure and canvas serve every plot
    the renderer draws; the per-plot work is drawing and encoding, never
    rebuilding the figure. The renderer's buffer is reused the same way.

    Args:
        renderer: The shared figure, canvas, and output buffer.
        series_list: The lines to draw, each already known to span enough
            observation times.
        y_axis_label: The unit shown at the plot's y-axis.

    Returns:
        The plot as PNG bytes.
    """
    figure = renderer.figure
    figure.clear()
    axes = figure.add_subplot(1, 1, 1)
    labels = [series.label for series in series_list]
    with mpl.rc_context(sns.axes_style("whitegrid")):
        if series_list:
            sns.lineplot(
                data=plot_frame(series_list),
                x=OBSERVATION_TIME_COLUMN,
                y=VALUE_COLUMN,
                hue=LABEL_COLUMN,
                hue_order=labels,
                legend=False,
                ax=axes,
            )
    handles = list(axes.get_lines())
    if handles:
        axes.legend(handles, labels, title="")
    axes.set_xlabel(X_AXIS_LABEL)
    axes.set_ylabel(y_axis_label)
    tick_times = x_axis_ticks(series_list)
    axes.xaxis.set_major_locator(
        matplotlib.ticker.FixedLocator(
            [matplotlib.dates.date2num(time) for time in tick_times],
        ),
    )
    axes.xaxis.set_major_formatter(matplotlib.dates.DateFormatter(DATE_FORMAT))
    if tick_times:
        # The axis spans the whole observation range, not just the ticks, so the line
        # reaches the first and last observation even when neither is on a tick.
        first_day, last_day = observation_day_span(series_list)
        axes.set_xlim(
            matplotlib.dates.date2num(
                datetime.datetime.combine(
                    first_day,
                    datetime.time.min,
                    tzinfo=datetime.UTC,
                ),
            ),
            matplotlib.dates.date2num(
                datetime.datetime.combine(
                    last_day,
                    datetime.time.min,
                    tzinfo=datetime.UTC,
                )
                + datetime.timedelta(days=1),
            ),
        )
    axes.yaxis.set_major_formatter(
        matplotlib.ticker.FuncFormatter(format_tick),
    )
    # Every plot shares a zero baseline: the x-axis line at the bottom of the
    # axes sits on the y=0 mark, so the axes cross at zero no matter how far
    # the measurements are from zero.
    axes.set_ylim(bottom=0)
    figure.tight_layout()
    buffer = renderer.buffer
    buffer.seek(0)
    buffer.truncate()
    figure.savefig(buffer, format=IMAGE_FORMAT)
    return buffer.getvalue()


# The rendering setup each pool worker reuses for every plot it draws. The pool
# initializer appends one renderer per worker; the workers share it across the
# pool's plots by clearing the figure between them. The parent process never
# renders, so its list stays empty.
worker_renderers: list[PlotRenderer] = []


def initialize_worker() -> None:
    """Create the renderer a plot pool worker reuses for every plot it draws.

    This runs once per worker process when the pool starts. The renderer holds
    the figure, canvas, and buffer the worker clears between plots; the y-axis
    label is per-plot data and travels with each request instead.
    """
    # Set niceness when possible to keep the machine responsive while the pool works.
    # Some platforms (e.g., Windows) do not have os.nice at all (AttributeError) and
    # sometimes sandboxes (e.g., used with coding agents) prevent changing niceness
    # (OSError), so ignore those errors as they don't change functionality.
    with contextlib.suppress(AttributeError, OSError):
        os.nice(WORKER_NICENESS_INCREMENT)
    worker_renderers.append(create_plot_renderer())


def render_plot_request(request: PlotRequest) -> PlotImage:
    """Render *request* on this worker's shared renderer.

    A pool worker calls this once per plot; the worker's renderer was created
    by the pool initializer.

    Args:
        request: The plot to render.

    Returns:
        The rendered image.

    Raises:
        RuntimeError: When the worker's renderer has not been created.
    """
    renderer = worker_renderers[0] if worker_renderers else None
    if renderer is None:
        message = "a plot pool worker must create its renderer before rendering"
        raise RuntimeError(message)
    return PlotImage(
        filename=plot_filename(
            request.filename_prefix,
            request.filename_suffix,
        ),
        content=draw_plot(
            renderer,
            request.series,
            y_axis_label=request.y_axis_label,
        ),
    )


def worker_count_for(task_count: int) -> int:
    """Return the number of workers the plot pool should use.

    A pool never needs more workers than it has plots to render, and never more
    than the machine has cores.

    Args:
        task_count: The number of plots the pool will render.

    Returns:
        The number of workers, at least one.
    """
    return max(1, min(task_count, os.cpu_count() or 1))


def plot_image_bundles(
    fire_bundles: tuple[tuple[str, tuple[FirePlot, ...]], ...],
) -> tuple[tuple[PlotImage, ...], ...]:
    """Render every fire's plots in parallel with one shared pool.

    Every worker in the pool creates its figure, canvas, and output buffer once
    and clears the figure between plots, so the per-plot work is only drawing
    and encoding. A fire's plot is skipped when none of its lines span enough
    observation times.

    Args:
        fire_bundles: Each fire's filename prefix and its plots, in fire order.

    Returns:
        Each fire's rendered images, in the input fire order and in each fire's
        plot order.
    """
    requests: list[PlotRequest] = []
    for fire_index, (filename_prefix, plots) in enumerate(fire_bundles):
        for plot in plots:
            series = retained_series(plot.series)
            if not series:
                continue
            requests.append(
                PlotRequest(
                    fire_index=fire_index,
                    filename_prefix=filename_prefix,
                    filename_suffix=plot.filename_suffix,
                    y_axis_label=plot.y_axis_label,
                    series=series,
                ),
            )
    images_by_fire: list[list[PlotImage]] = [[] for _fire in fire_bundles]
    if not requests:
        return tuple(tuple(images) for images in images_by_fire)
    with multiprocessing.Pool(
        worker_count_for(len(requests)),
        initializer=initialize_worker,
    ) as pool:
        results = pool.map(render_plot_request, requests)
    for request, image in zip(requests, results, strict=True):
        images_by_fire[request.fire_index].append(image)
    return tuple(tuple(images) for images in images_by_fire)


def plot_filename(filename_prefix: str, filename_suffix: str) -> str:
    """Return the image filename for *filename_suffix* under *filename_prefix*.

    Args:
        filename_prefix: The fire's unique filename prefix.
        filename_suffix: The plot's suffix, like ``area``.

    Returns:
        The filename, like ``2026-cabug-000001-area.png``.
    """
    return f"{filename_prefix}-{filename_suffix}.{IMAGE_FORMAT}"


def filename_prefix(identifier: str | None, name: str) -> str:
    """Return a filesystem-safe filename prefix for a fire.

    The canonical identifier is preferred and is already a unique token; a fire
    without one uses its name. Either way, every non-alphanumeric run collapses to a
    hyphen so the prefix is safe to use in a filename and an HTML image source.

    Args:
        identifier: The fire's canonical identifier, or None.
        name: The fire's name.

    Returns:
        The filename prefix.
    """
    value = identifier if identifier is not None else name
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return slug or "fire"
