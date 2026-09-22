"""SVG time-series charts with measured legends and complete UTC-day axes."""

from __future__ import annotations

import collections.abc
import dataclasses
import datetime
import itertools
import math

import svg_charts.models
import svg_charts.svg
from measurement_units import units


# Tick values at or above these magnitudes keep progressively fewer decimals.
TICK_WHOLE_NUMBER_THRESHOLD = 1_000.0
TICK_ONE_DECIMAL_THRESHOLD = 10.0

# X-axis tick labels sit only at midnight and are thinned so at most this many fit along
# the figure without crowding.
MAXIMUM_X_AXIS_TICKS = 6

# The rendered chart size.
CHART_WIDTH = 480 * units.pixels
CHART_HEIGHT = 300 * units.pixels

# The document format emitted by the renderer.
IMAGE_FORMAT = "svg"

DATE_FORMAT = "%m/%d"

# Font sizes in pixels. Ten-point text at 100 dpi lands at 13.9 px, so the tick labels
# round up to 14 px.
TICK_FONT_SIZE = 14.0
AXIS_LABEL_FONT_SIZE = 15.0
TEXT_COLOR = "#262626"

# Padding inside the canvas, and the gaps the axes need around the plot area. The bottom
# margin leaves room for the x tick labels below the plot area, the right margin adds to
# the half of the outermost x label the layout keeps inside the canvas, and the top
# margin is larger because the legend occupies a row above the plot area.
PAD_TOP = 30.0
PAD_RIGHT = 8.0
PAD_BOTTOM = 39.0
TICK_LENGTH = 5.0
TICK_LABEL_GAP = 7.0
GRID_COLOR = "#cccccc"
LINE_WIDTH = 1.6

# The legend is one centred row above the plot area: a colour swatch and a label per
# series, with this much space between consecutive entries.
LEGEND_BASELINE_Y = 16.0
LEGEND_SWATCH_WIDTH = 22.0
LEGEND_SWATCH_GAP = 6.0
LEGEND_SWATCH_RISE = 5.0
LEGEND_ENTRY_GAP = 25.0

# The rotated y-axis label sits with its baseline here, and the y tick labels keep a
# clear gap past the label's lower edge so the unit is not crowded against the numbers.
# Rotated text runs its ascent to one side of the baseline and its descent to the other,
# so the lower edge is the baseline plus the descent.
PAD_AXIS_LABEL = 15.0
AXIS_LABEL_LOWER_EDGE = 4.0
AXIS_LABEL_GAP = 8.0


def format_tick(value: float) -> str:
    """Format one y-axis tick with size-appropriate precision.

    Small values retain enough significant digits to distinguish the 1/2/2.5/5 tick
    intervals even when measurements are tiny fractions of the axis unit. Trailing zeros
    after the decimal point are dropped.

    Args:
        value: The tick value.

    Returns:
        The formatted tick label.

    Examples:
        >>> format_tick(0.0)
        '0'
        >>> format_tick(7.5)
        '7.5'
        >>> format_tick(2_500.0)
        '2,500'
    """
    magnitude = abs(value)
    if magnitude >= TICK_WHOLE_NUMBER_THRESHOLD:
        text = f"{value:,.0f}"
    elif magnitude >= TICK_ONE_DECIMAL_THRESHOLD:
        text = f"{value:,.1f}"
    else:
        precision = max(2, 2 - math.floor(math.log10(magnitude))) if magnitude else 2
        text = f"{value:,.{precision}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def observation_day_span(
    series_list: tuple[svg_charts.models.PlotSeries, ...],
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
    return (
        min(times).astimezone(datetime.UTC).date(),
        max(times).astimezone(datetime.UTC).date(),
    )


def x_axis_ticks(
    series_list: tuple[svg_charts.models.PlotSeries, ...],
) -> tuple[datetime.datetime, ...]:
    """Return the midnight times at which to place x-axis ticks.

    Ticks sit on a uniform grid of midnights across the observations: each tick is one
    interval after the last, where the interval thins the grid to at most
    ``MAXIMUM_X_AXIS_TICKS`` ticks. No tick is forced onto the first or last observation
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
    interval = max(1, math.ceil(in_days_spanned / MAXIMUM_X_AXIS_TICKS))
    ticks: list[datetime.datetime] = []
    day = first_day
    while day <= last_day:
        ticks.append(
            datetime.datetime.combine(day, datetime.time.min, tzinfo=datetime.UTC),
        )
        day += datetime.timedelta(days=interval)
    return tuple(ticks)


def y_axis_ticks(
    series_list: tuple[svg_charts.models.PlotSeries, ...],
) -> tuple[float, tuple[float, ...]]:
    """Return the y-axis top and its tick values, counted up from zero.

    Args:
        series_list: The lines drawn in the plot.

    Returns:
        The axis top and the tick values from zero to the top.

    Examples:
        >>> peak = svg_charts.models.PlotSeries(
        ...     label="Area",
        ...     points=(
        ...         svg_charts.models.SeriesPoint(
        ...             observation_time=datetime.datetime(
        ...                 2026, 7, 1, tzinfo=datetime.UTC
        ...             ),
        ...             value=0.0,
        ...         ),
        ...     ),
        ... )
        >>> y_axis_ticks((peak,))
        (1.0, (0.0, 1.0))
    """
    peak = max(point.value for series in series_list for point in series.points)
    if peak <= 0:
        return 1.0, (0.0, 1.0)
    step = svg_charts.svg.nice_step(peak, 4)
    top = math.ceil(peak / step) * step
    count = round(top / step)
    return top, tuple(index * step for index in range(count + 1))


def line_path(
    points: tuple[svg_charts.models.SeriesPoint, ...],
    x_of: collections.abc.Callable[[datetime.datetime], float],
    y_of: collections.abc.Callable[[float], float],
) -> str:
    """Return the SVG path data drawing *points* as one open polyline.

    Args:
        points: The measurements to draw.
        x_of: A callable mapping an observation time to an x coordinate.
        y_of: A callable mapping a value to a y coordinate.

    Returns:
        The ``d`` attribute text, like ``M 10.0 20.0 L 30.0 40.0``.

    Examples:
        >>> point = svg_charts.models.SeriesPoint(
        ...     observation_time=datetime.datetime(2026, 7, 1, tzinfo=datetime.UTC),
        ...     value=2.0,
        ... )
        >>> line_path((point,), lambda _time: 10.0, lambda _value: 20.0)
        'M 10.0 20.0'
    """
    commands = [
        f"{'M' if index == 0 else 'L'} {x_of(point.observation_time):.1f} "
        f"{y_of(point.value):.1f}"
        for index, point in enumerate(points)
    ]
    return " ".join(commands)


def legend_entry_width(label: str) -> float:
    """Return the width one legend entry occupies.

    Args:
        label: The entry's label.

    Returns:
        The width in pixels.
    """
    return (
        LEGEND_SWATCH_WIDTH
        + LEGEND_SWATCH_GAP
        + svg_charts.svg.text_width(label, TICK_FONT_SIZE)
    )


def legend_width(labels: tuple[str, ...]) -> float:
    """Return the width the one-row legend occupies.

    Args:
        labels: The legend's labels, in order.

    Returns:
        The width in pixels.

    Examples:
        >>> legend_width(())
        0.0
        >>> round(legend_width(("Area",)), 3)
        57.568
    """
    return sum(legend_entry_width(label) for label in labels) + LEGEND_ENTRY_GAP * max(
        0,
        len(labels) - 1,
    )


def line_element(x1: float, y1: float, x2: float, y2: float) -> str:
    """Return one SVG line element.

    Args:
        x1: The start x coordinate.
        y1: The start y coordinate.
        x2: The end x coordinate.
        y2: The end y coordinate.

    Returns:
        The line element.
    """
    return f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}"/>'


@dataclasses.dataclass(frozen=True, kw_only=True)
class PlotLayout:
    """Where every part of one plot is drawn.

    The layout is computed once from the data and then read by each element builder, so
    the coordinate mapping and the axis margins are decided in exactly one place.
    """

    width: int
    height: int
    plot_left: float
    plot_top: float
    plot_right: float
    plot_bottom: float
    first_day: datetime.date
    day_span: int
    axis_top: float
    ticks: tuple[float, ...]
    tick_text: tuple[str, ...]
    tick_times: tuple[datetime.datetime, ...]

    @property
    def plot_width(self) -> float:
        """The plot area's width in pixels.

        Returns:
            The width in pixels.
        """
        return self.plot_right - self.plot_left

    @property
    def plot_height(self) -> float:
        """The plot area's height in pixels.

        Returns:
            The height in pixels.
        """
        return self.plot_bottom - self.plot_top

    def x_of(self, time: datetime.datetime) -> float:
        """Return the x coordinate of *time*.

        Args:
            time: The observation time to place.

        Returns:
            The x coordinate.
        """
        first_midnight = datetime.datetime.combine(
            self.first_day,
            datetime.time.min,
            tzinfo=datetime.UTC,
        )
        elapsed = (time - first_midnight) / datetime.timedelta(days=self.day_span)
        return self.plot_left + elapsed * self.plot_width

    def y_of(self, value: float) -> float:
        """Return the y coordinate of *value*.

        Args:
            value: The measurement to place.

        Returns:
            The y coordinate.
        """
        return self.plot_bottom - value / self.axis_top * self.plot_height


def plot_layout(
    series_list: tuple[svg_charts.models.PlotSeries, ...],
) -> PlotLayout:
    """Return where every part of *series_list*'s plot is drawn.

    The y-axis is counted up from zero. The x-axis covers complete UTC days, including
    the last observation's day, so intraday measurements fit between midnight ticks. The
    left margin clears the rotated axis label, and the right margin keeps half of the
    outermost x label inside the canvas so it is never clipped.

    Args:
        series_list: The lines drawn in the plot.

    Returns:
        The layout.
    """
    width = int(CHART_WIDTH.magnitude)
    height = int(CHART_HEIGHT.magnitude)
    axis_top, ticks = y_axis_ticks(series_list)
    tick_text = tuple(format_tick(value) for value in ticks)
    first_day, last_day = observation_day_span(series_list)
    tick_times = x_axis_ticks(series_list)
    half_x_label = (
        max(
            svg_charts.svg.text_width(time.strftime(DATE_FORMAT), TICK_FONT_SIZE)
            for time in (tick_times[0], tick_times[-1])
        )
        / 2
    )
    widest_tick = max(
        svg_charts.svg.text_width(text, TICK_FONT_SIZE) for text in tick_text
    )
    plot_left = max(
        PAD_AXIS_LABEL
        + AXIS_LABEL_LOWER_EDGE
        + AXIS_LABEL_GAP
        + widest_tick
        + TICK_LABEL_GAP
        + TICK_LENGTH,
        half_x_label + 2,
    )
    return PlotLayout(
        width=width,
        height=height,
        plot_left=plot_left,
        plot_top=PAD_TOP,
        plot_right=width - PAD_RIGHT - half_x_label,
        plot_bottom=height - PAD_BOTTOM,
        first_day=first_day,
        day_span=(last_day - first_day).days + 1,
        axis_top=axis_top,
        ticks=ticks,
        tick_text=tick_text,
        tick_times=tick_times,
    )


def gridline_elements(layout: PlotLayout) -> list[str]:
    """Return the horizontal gridlines, which sit beneath everything else.

    The group is axis-aligned and one pixel wide, so it asks the renderer to skip
    antialiasing rather than blur each line across two half-intensity pixel rows.

    Args:
        layout: The plot's layout.

    Returns:
        The elements.
    """
    return [
        (f'<g stroke="{GRID_COLOR}" stroke-width="1" shape-rendering="crispEdges">'),
        *(
            line_element(
                layout.plot_left,
                layout.y_of(value),
                layout.plot_right,
                layout.y_of(value),
            )
            for value in layout.ticks
        ),
        "</g>",
    ]


def frame_elements(layout: PlotLayout) -> list[str]:
    """Return the box frame and its tick marks, which sit beneath the data.

    The frame is drawn on all four sides. It is drawn before the data so a series
    sitting on zero stays visible instead of disappearing under the x-axis rule.

    Args:
        layout: The plot's layout.

    Returns:
        The elements.
    """
    left, right = layout.plot_left, layout.plot_right
    top, bottom = layout.plot_top, layout.plot_bottom
    return [
        f'<g stroke="{TEXT_COLOR}" stroke-width="1" shape-rendering="crispEdges">',
        line_element(left, top, left, bottom),
        line_element(left, bottom, right, bottom),
        line_element(left, top, right, top),
        line_element(right, top, right, bottom),
        *(
            line_element(
                left - TICK_LENGTH,
                layout.y_of(value),
                left,
                layout.y_of(value),
            )
            for value in layout.ticks
        ),
        *(
            line_element(
                layout.x_of(time),
                bottom,
                layout.x_of(time),
                bottom + TICK_LENGTH,
            )
            for time in layout.tick_times
        ),
        "</g>",
    ]


def stroke_attributes(
    color: str,
    *,
    style: svg_charts.models.StrokeStyle,
) -> str:
    """Keep the legend swatches consistent with the lines they identify.

    Args:
        color: The series color shared by the plot and legend.
        style: The stroke pattern for the line and its legend swatch.

    Returns:
        SVG stroke attributes shared by the line and its legend swatch.
    """
    dash = (
        ' stroke-dasharray="5 3"'
        if style is svg_charts.models.StrokeStyle.DASHED
        else ""
    )
    return f'stroke="{svg_charts.svg.escape_text(color)}"{dash}'


def series_elements(
    series_list: tuple[svg_charts.models.PlotSeries, ...],
    layout: PlotLayout,
) -> list[str]:
    """Return the data lines, clipped to the plot area.

    Args:
        series_list: The lines to draw.
        layout: The plot's layout.

    Returns:
        The elements.
    """
    elements = [
        f'<g clip-path="url(#plot-area)" fill="none" stroke-width="{LINE_WIDTH}">',
    ]
    for series in series_list:
        for points, style in line_segments(series.points):
            elements.append(
                f'<path d="{line_path(points, layout.x_of, layout.y_of)}" '
                f"{stroke_attributes(series.color, style=style)} "
                'stroke-linejoin="round"/>',
            )
    return [*elements, "</g>"]


def line_segments(
    points: tuple[svg_charts.models.SeriesPoint, ...],
) -> list[
    tuple[tuple[svg_charts.models.SeriesPoint, ...], svg_charts.models.StrokeStyle]
]:
    """Keep stroke changes visible while connecting adjacent parts of a series.

    A transition shares its preceding endpoint and takes the destination point's
    style. Isolated points cannot form a line or justify a legend entry.

    Args:
        points: Chronological measurements with caller-selected stroke styles.

    Returns:
        Drawable point sequences paired with their stroke styles, or an empty
        list when there are too few points to form a line.
    """
    if len(points) <= 1:
        return []
    result: list[
        tuple[tuple[svg_charts.models.SeriesPoint, ...], svg_charts.models.StrokeStyle]
    ] = []
    segment = [points[0]]
    style = points[0].style
    for point in points[1:]:
        if point.style != style:
            if len(segment) > 1:
                result.append((tuple(segment), style))
            segment = [segment[-1]]
            style = point.style
        segment.append(point)
    result.append((tuple(segment), style))
    return result


def label_elements(layout: PlotLayout, y_axis_label: str) -> list[str]:
    """Return the tick labels and the rotated y-axis label.

    Y tick labels are right-aligned against the axis so they need no measurement; x tick
    labels are centred on their ticks.

    Args:
        layout: The plot's layout.
        y_axis_label: The unit shown at the plot's y-axis.

    Returns:
        The elements.
    """
    font = (
        f'font-family="{svg_charts.svg.FONT_STACK}" '
        f'font-size="{TICK_FONT_SIZE:.0f}" fill="{TEXT_COLOR}"'
    )
    axis_font = (
        f'font-family="{svg_charts.svg.FONT_STACK}" '
        f'font-size="{AXIS_LABEL_FONT_SIZE:.0f}" fill="{TEXT_COLOR}"'
    )
    centre_y = (layout.plot_top + layout.plot_bottom) / 2
    return [
        f'<g {font} text-anchor="end">',
        *(
            (
                f'<text x="{layout.plot_left - TICK_LENGTH - TICK_LABEL_GAP:.1f}" '
                f'y="{layout.y_of(value) + TICK_FONT_SIZE * 0.35:.1f}">{text}</text>'
            )
            for value, text in zip(layout.ticks, layout.tick_text, strict=True)
        ),
        "</g>",
        f'<g {font} text-anchor="middle">',
        *(
            (
                f'<text x="{layout.x_of(time):.1f}" '
                f'y="{layout.plot_bottom + TICK_LENGTH + TICK_FONT_SIZE + 2:.1f}">'
                f"{time.strftime(DATE_FORMAT)}</text>"
            )
            for time in layout.tick_times
        ),
        "</g>",
        (
            f'<text x="0" y="0" transform="translate({PAD_AXIS_LABEL},{centre_y:.1f}) '
            f'rotate(-90)" {axis_font} text-anchor="middle">'
            f"{svg_charts.svg.escape_text(y_axis_label)}</text>"
        ),
    ]


@dataclasses.dataclass(frozen=True, kw_only=True)
class LegendEntry:
    """A label identifies a visible line's series color and stroke style."""

    label: str
    color: str
    style: svg_charts.models.StrokeStyle


def legend_entries(
    series_list: tuple[svg_charts.models.PlotSeries, ...],
) -> tuple[LegendEntry, ...]:
    """Only styles that form rendered segments need a legend entry.

    Args:
        series_list: Plot series whose visible segments determine the legend.

    Returns:
        One entry per visible style, with solid lines before dashed lines.
    """
    entries: list[LegendEntry] = []
    for series in series_list:
        styles = {style for _points, style in line_segments(series.points)}
        entries.extend(
            LegendEntry(
                label=(series.dashed_label or series.label)
                if style is svg_charts.models.StrokeStyle.DASHED
                else series.label,
                color=series.color,
                style=style,
            )
            for style in sorted(styles)
        )
    return tuple(entries)


def legend_entry_elements(entry: LegendEntry, start: float) -> tuple[str, str]:
    """Return the swatch and the label of one legend entry.

    Args:
        entry: The visible line's label and style.
        start: The x coordinate the entry starts at.

    Returns:
        The swatch element and the label element.
    """
    swatch_y = LEGEND_BASELINE_Y - LEGEND_SWATCH_RISE
    return (
        (
            f'<line x1="{start:.1f}" y1="{swatch_y:.1f}" '
            f'x2="{start + LEGEND_SWATCH_WIDTH:.1f}" y2="{swatch_y:.1f}" '
            f"{stroke_attributes(entry.color, style=entry.style)} "
            f'stroke-width="{LINE_WIDTH}"/>'
        ),
        (
            f'<text x="{start + LEGEND_SWATCH_WIDTH + LEGEND_SWATCH_GAP:.1f}" '
            f'y="{LEGEND_BASELINE_Y:.1f}">'
            f"{svg_charts.svg.escape_text(entry.label)}</text>"
        ),
    )


def legend_elements(entries: tuple[LegendEntry, ...], width: int) -> list[str]:
    """Return the one-row legend centred above the plot area.

    Args:
        entries: The visible lines' labels and styles, in order.
        width: The canvas width the legend is centred within.

    Returns:
        The elements.
    """
    if not entries:
        return []
    labels = tuple(entry.label for entry in entries)
    spacing = [legend_entry_width(label) + LEGEND_ENTRY_GAP for label in labels]
    starts = itertools.accumulate([(width - legend_width(labels)) / 2, *spacing[:-1]])
    return [
        (
            f'<g font-family="{svg_charts.svg.FONT_STACK}" '
            f'font-size="{TICK_FONT_SIZE:.0f}" fill="{TEXT_COLOR}">'
        ),
        *(
            element
            for entry, start in zip(entries, starts, strict=True)
            for element in legend_entry_elements(entry, start)
        ),
        "</g>",
    ]


def draw_plot(
    series_list: tuple[svg_charts.models.PlotSeries, ...],
    *,
    y_axis_label: str = "",
) -> bytes:
    """Draw *series_list* as an SVG document and return its bytes.

    Args:
        series_list: The lines to draw, each already known to span enough observation
            times.
        y_axis_label: The unit shown at the plot's y-axis.

    Returns:
        The plot as SVG bytes.
    """
    layout = plot_layout(series_list)
    elements = [
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{layout.width}" '
            f'height="{layout.height}" '
            f'viewBox="0 0 {layout.width} {layout.height}">'
        ),
        (
            '<defs><clipPath id="plot-area">'
            f'<rect x="{layout.plot_left:.1f}" y="{layout.plot_top:.1f}" '
            f'width="{layout.plot_width:.1f}" height="{layout.plot_height:.1f}"/>'
            "</clipPath></defs>"
        ),
        f'<rect width="{layout.width}" height="{layout.height}" fill="#ffffff"/>',
        *gridline_elements(layout),
        *frame_elements(layout),
        *series_elements(series_list, layout),
        *label_elements(layout, y_axis_label),
        *legend_elements(legend_entries(series_list), layout.width),
        "</svg>",
    ]
    return ("\n".join(elements) + "\n").encode()
