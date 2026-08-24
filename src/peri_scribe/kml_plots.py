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
"""

from __future__ import annotations

import dataclasses
import datetime
import io
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

# Containment percentages are reported in whole percent (0-100), so the contained
# perimeter is that fraction of the exterior perimeter length.
CONTAINMENT_PERCENT = 100.0

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

# The legend label for each line; the label also carries the unit, since every line
# in a plot shares one unit.
AREA_SERIES_LABEL = "Area (acres)"
EXTERIOR_PERIMETER_SERIES_LABEL = "Exterior perimeter (miles)"
CONTAINED_PERIMETER_SERIES_LABEL = "Contained perimeter (miles)"
COST_TO_DATE_SERIES_LABEL = "Cost to date ($)"
ESTIMATED_FINAL_COST_SERIES_LABEL = "Estimated final cost ($)"


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
    """One plot for a fire: its lines and the filename suffix for its image."""

    filename_suffix: str
    series: tuple[PlotSeries, ...]


@dataclasses.dataclass(frozen=True, kw_only=True)
class PlotImage:
    """One rendered plot: its filename and PNG bytes."""

    filename: str
    content: bytes


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
        percent = peri_scribe.geo_package.numeric_value(percent_contained)
        if time is not None and length is not None and percent is not None:
            points.append(
                SeriesPoint(
                    observation_time=time,
                    value=length * percent / CONTAINMENT_PERCENT,
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

    area_points = merge_series_points(
        series_points(perimeter_rows, "observation_time", "area_acres"),
        series_points(point_rows, "observation_time", "incident_size"),
    )
    cost_to_date_points = merge_series_points(
        series_points(
            perimeter_rows,
            "observation_time",
            "estimated_cost_to_date",
        ),
        series_points(point_rows, "observation_time", "estimated_cost_to_date"),
    )
    estimated_final_cost_points = merge_series_points(
        series_points(
            perimeter_rows,
            "observation_time",
            "estimated_final_cost",
        ),
        series_points(point_rows, "observation_time", "estimated_final_cost"),
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
    or two decimals so small measurements do not read as zero.

    Args:
        value: The tick value.
        _position: The tick position, unused.

    Returns:
        The formatted tick label.
    """
    magnitude = abs(value)
    if magnitude >= TICK_WHOLE_NUMBER_THRESHOLD:
        return f"{value:,.0f}"
    if magnitude >= TICK_ONE_DECIMAL_THRESHOLD:
        return f"{value:,.1f}"
    return f"{value:,.2f}"


def render_plot(series_list: tuple[PlotSeries, ...]) -> bytes:
    """Render *series_list* as one line plot and return its PNG bytes.

    Args:
        series_list: The lines to draw, each already known to span enough
            observation times.

    Returns:
        The plot as PNG bytes.
    """
    figure = matplotlib.figure.Figure(
        figsize=(FIGURE_WIDTH_IN_INCHES, FIGURE_HEIGHT_IN_INCHES),
        dpi=IMAGE_DPI,
    )
    matplotlib.backends.backend_agg.FigureCanvasAgg(figure)
    axes = figure.add_subplot(1, 1, 1)
    frame = plot_frame(series_list)
    with mpl.rc_context(sns.axes_style("whitegrid")):
        sns.lineplot(
            data=frame,
            x=OBSERVATION_TIME_COLUMN,
            y=VALUE_COLUMN,
            hue=LABEL_COLUMN,
            ax=axes,
        )
    legend = axes.get_legend()
    if legend is not None:
        legend.set_title("")
    axes.set_xlabel(X_AXIS_LABEL)
    axes.set_ylabel("")
    axes.xaxis.set_major_locator(matplotlib.dates.AutoDateLocator())
    axes.xaxis.set_major_formatter(matplotlib.dates.DateFormatter(DATE_FORMAT))
    axes.yaxis.set_major_formatter(
        matplotlib.ticker.FuncFormatter(format_tick),
    )
    figure.tight_layout()
    buffer = io.BytesIO()
    figure.savefig(buffer, format=IMAGE_FORMAT)
    return buffer.getvalue()


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


def plot_images(
    plots: typing.Iterable[FirePlot],
    filename_prefix: str,
) -> tuple[PlotImage, ...]:
    """Render each of *plots* that still has a line to draw.

    A line is dropped when it does not span enough observation times; a plot whose
    lines are all dropped produces no image. Each rendered image's filename combines
    *filename_prefix* with the plot's suffix.

    Args:
        plots: The fire's plots, in display order.
        filename_prefix: The fire's unique filename prefix.

    Returns:
        The rendered images, in the order of the plots that survived.
    """
    images: list[PlotImage] = []
    for plot in plots:
        series = retained_series(plot.series)
        if not series:
            continue
        images.append(
            PlotImage(
                filename=plot_filename(filename_prefix, plot.filename_suffix),
                content=render_plot(series),
            ),
        )
    return tuple(images)
