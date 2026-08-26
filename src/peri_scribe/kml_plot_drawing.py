"""Drawing one fire plot with matplotlib.

A plot renders its surviving series into PNG bytes in memory. The figure, canvas, and
output buffer are built once and reused across a worker's plots.
"""

from __future__ import annotations

import dataclasses
import datetime
import io
import math

import matplotlib as mpl
import matplotlib.backends.backend_agg
import matplotlib.dates
import matplotlib.figure
import matplotlib.ticker
import seaborn as sns

import peri_scribe.kml_plot_data


# Tick values at or above these magnitudes keep progressively fewer decimals.
TICK_WHOLE_NUMBER_THRESHOLD = 1000.0
TICK_ONE_DECIMAL_THRESHOLD = 10.0

# X-axis tick labels sit only at midnight and are thinned so at most this many fit along
# the figure without crowding.
MAX_X_AXIS_TICKS = 6

# The rendered image dimensions, in inches and dots per inch.
FIGURE_WIDTH_IN_INCHES = 4.8
FIGURE_HEIGHT_IN_INCHES = 3.0
IMAGE_DPI = 100

IMAGE_FORMAT = "png"

DATE_FORMAT = "%m/%d"


@dataclasses.dataclass(frozen=True, kw_only=True)
class PlotRenderer:
    """The rendering setup one worker reuses for every plot it draws.

    The figure's dimensions and dpi, the canvas, and the output buffer are the same for
    every plot a worker renders, so a pool worker creates them once and clears the
    figure between plots rather than rebuilding them each time.
    """

    figure: matplotlib.figure.Figure
    buffer: io.BytesIO


def format_tick(value: float, _position: int) -> str:
    """Format one y-axis tick with size-appropriate precision.

    Large values carry thousands separators and no decimals; smaller values keep one or
    two decimals so small measurements do not read as zero. Trailing zeros after the
    decimal point are dropped.

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
    series_list: tuple[peri_scribe.kml_plot_data.PlotSeries, ...],
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
    series_list: tuple[peri_scribe.kml_plot_data.PlotSeries, ...],
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

    The figure's size and dpi, the canvas, and the output buffer are the same for every
    plot a worker renders, so a pool worker creates them once here and clears the figure
    between plots instead of rebuilding them each time.

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
    series_list: tuple[peri_scribe.kml_plot_data.PlotSeries, ...],
    *,
    y_axis_label: str = "",
) -> bytes:
    """Draw *series_list* on *renderer*'s figure and return its PNG bytes.

    The figure is cleared first, so the same figure and canvas serve every plot the
    renderer draws; the per-plot work is drawing and encoding, never rebuilding the
    figure. The renderer's buffer is reused the same way.

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
                data=peri_scribe.kml_plot_data.plot_frame(series_list),
                x=peri_scribe.kml_plot_data.OBSERVATION_TIME_COLUMN,
                y=peri_scribe.kml_plot_data.VALUE_COLUMN,
                hue=peri_scribe.kml_plot_data.LABEL_COLUMN,
                hue_order=labels,
                legend=False,
                ax=axes,
            )
    handles = list(axes.get_lines())
    if handles:
        axes.legend(handles, labels, title="")
    axes.set_ylabel(y_axis_label)
    # seaborn labels the x-axis with the observation-time column's name, but the dates
    # themselves are the only x-axis text wanted.
    axes.set_xlabel("")
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
    # Every plot shares a zero baseline: the x-axis line at the bottom of the axes sits
    # on the y=0 mark, so the axes cross at zero no matter how far the measurements are
    # from zero.
    axes.set_ylim(bottom=0)
    figure.tight_layout()
    buffer = renderer.buffer
    buffer.seek(0)
    buffer.truncate()
    figure.savefig(buffer, format=IMAGE_FORMAT)
    return buffer.getvalue()
