"""SVG distribution curves, logarithmic share axes, and optional annotations."""

from __future__ import annotations

import collections.abc
import dataclasses
import html
import math

import numpy as np

import svg_charts.svg
from measurement_units import units


@dataclasses.dataclass(frozen=True, kw_only=True)
class CurveAnnotation:
    """Caller-owned text at a numeric value and complementary share."""

    value: float
    share: float
    lines: tuple[str, ...]


# The distribution chart's size.
CCDF_CHART_WIDTH = 1024 * units.pixels
CCDF_CHART_HEIGHT = 768 * units.pixels

# The chart's margins in pixels. The right margin is wide because the knee labels sit
# outside the curve, beside the knee they describe.
CCDF_PAD_LEFT = 110.0
CCDF_PAD_RIGHT = 300.0
CCDF_PAD_TOP = 50.0
CCDF_PAD_BOTTOM = 80.0

# The chart's fonts and palette.
CCDF_TICK_FONT_SIZE = 16.0
CCDF_LABEL_FONT_SIZE = 18.0
CCDF_TITLE_FONT_SIZE = 22.0
CCDF_TEXT_COLOR = "#262626"
CCDF_CURVE_COLOR = "#4c72b0"
CCDF_GRID_COLOR = "#dddddd"
CCDF_KNEE_COLOR = "#888888"

# The value axis aims for this many intervals; the share axis is labelled at every power
# of ten.
CCDF_TARGET_VALUE_INTERVALS = 8

# The fewest decades the share axis spans, so a chart whose shares never fall below a
# tenth still has a readable, non-degenerate axis.
CCDF_MINIMUM_DECADES = 1


def share_curve(
    samples: collections.abc.Sequence[float],
) -> tuple[np.ndarray, np.ndarray]:
    """Return the complementary CDF of *samples*.

    Each point is a distinct value and the share of samples exceeding it. Values whose
    share is zero are dropped, because a logarithmic share axis cannot show them.

    Args:
        samples: The numeric samples to plot.

    Returns:
        The distinct samples and their complementary shares.

    Examples:
        >>> values, shares = share_curve([1, 2, 2, 4])
        >>> values.tolist(), shares.tolist()
        ([1, 2], [0.75, 0.25])
    """
    values, counts = np.unique(samples, return_counts=True)
    total = len(samples)
    shares = (total - np.cumsum(counts)) / total
    visible = shares > 0
    return values[visible], shares[visible]


def share_decades(smallest_share: float) -> int:
    """Return how many decades the share axis spans below one.

    Args:
        smallest_share: The smallest share the axis must show.

    Returns:
        The number of decades, at least :data:`CCDF_MINIMUM_DECADES`.

    Examples:
        >>> share_decades(0.004)
        3
        >>> share_decades(1.0)
        1
    """
    if smallest_share >= 1.0:
        return CCDF_MINIMUM_DECADES
    return max(CCDF_MINIMUM_DECADES, math.ceil(-math.log10(smallest_share)))


def share_tick_text(value: float) -> str:
    """Return the label for one complementary-share tick.

    Shares are labelled as plain decimals rather than powers, so the axis reads
    directly.

    Args:
        value: The tick's share.

    Returns:
        The label.

    Examples:
        >>> share_tick_text(1.0)
        '1'
        >>> share_tick_text(0.01)
        '0.01'
    """
    exponent = math.floor(math.log10(value))
    if exponent >= 0:
        return "1"
    return f"{value:.{-exponent}f}"


def curve_knees(samples: collections.abc.Sequence[float]) -> list[tuple[float, float]]:
    """Return the (value, complementary share) pairs where the CCDF bends most.

    The curve is the complementary share plotted with a logarithmic y-axis, so the fit
    is over (value, log share) coordinates. The two knees are the breakpoints of the
    three-line-segment fit with the smallest total squared error; fewer than five
    visible points leaves no room for two breakpoints.

    Args:
        samples: The numeric samples to plot.

    Returns:
        The knee points as (value, complementary share) pairs, in value order.

    Examples:
        >>> curve_knees([1, 2, 3, 4])
        []
    """
    values, shares = share_curve(samples)
    points = np.column_stack((values, np.log10(shares)))

    def fit_error(first: int, second: int) -> float:
        """Compare candidate knees by the error of their three-segment fit.

        Args:
            first: The point index of the first proposed breakpoint.
            second: The point index of the second proposed breakpoint.

        Returns:
            The total squared error in logarithmic complementary share.
        """
        error = 0.0
        for low, high in ((0, first), (first, second), (second, len(points))):
            segment = points[low : high + 1]
            x, y = segment[:, 0], segment[:, 1]
            design = np.column_stack((x, np.ones(len(x))))
            coefficients, *_ = np.linalg.lstsq(design, y, rcond=None)
            error += float(np.sum((y - design @ coefficients) ** 2))
        return error

    best = None
    for first in range(2, len(points) - 2):
        for second in range(first + 2, len(points)):
            error = fit_error(first, second)
            if best is None or error < best[0]:
                best = (error, first, second)
    if best is None:
        return []
    _, first, second = best
    return [
        (float(values[first]), float(shares[first])),
        (float(values[second]), float(shares[second])),
    ]


@dataclasses.dataclass(frozen=True, kw_only=True)
class CcdfLayout:
    """Where every part of the distribution chart is drawn.

    The value axis is linear from zero and the share axis is logarithmic, spanning
    ``decades`` powers of ten below one.
    """

    width: int
    height: int
    left: float
    right: float
    top: float
    bottom: float
    highest_value: float
    decades: int

    @property
    def plot_width(self) -> float:
        """The plot area's width in pixels.

        Returns:
            The width in pixels.
        """
        return self.right - self.left

    @property
    def plot_height(self) -> float:
        """The plot area's height in pixels.

        Returns:
            The height in pixels.
        """
        return self.bottom - self.top

    def x_of(self, value: float) -> float:
        """Return the x coordinate of *value*.

        Args:
            value: The value to place.

        Returns:
            The x coordinate.
        """
        return self.left + value / self.highest_value * self.plot_width

    def y_of(self, share: float) -> float:
        """Return the y coordinate of *share* on the logarithmic share axis.

        Args:
            share: The complementary share to place.

        Returns:
            The y coordinate.
        """
        fraction = (math.log10(share) + self.decades) / self.decades
        return self.bottom - fraction * self.plot_height

    def value_ticks(self) -> tuple[float, ...]:
        """Return the value-axis tick values.

        Returns:
            The tick values from zero to the axis top.
        """
        step = svg_charts.svg.nice_step(
            self.highest_value,
            CCDF_TARGET_VALUE_INTERVALS,
        )
        return tuple(
            index * step for index in range(round(self.highest_value / step) + 1)
        )

    def share_ticks(self) -> tuple[float, ...]:
        """Return the share-axis tick values, one per decade.

        Returns:
            The tick values, largest first.
        """
        return tuple(10.0**-power for power in range(self.decades + 1))


def ccdf_layout(samples: collections.abc.Sequence[float]) -> CcdfLayout:
    """Return where every part of the distribution chart is drawn.

    Args:
        samples: The numeric samples to plot.

    Returns:
        The layout.
    """
    width = int(CCDF_CHART_WIDTH.magnitude)
    height = int(CCDF_CHART_HEIGHT.magnitude)
    values, shares = share_curve(samples)
    return CcdfLayout(
        width=width,
        height=height,
        left=CCDF_PAD_LEFT,
        right=width - CCDF_PAD_RIGHT,
        top=CCDF_PAD_TOP,
        bottom=height - CCDF_PAD_BOTTOM,
        highest_value=float(values.max()) if len(values) else 1.0,
        decades=share_decades(float(shares.min()) if len(shares) else 1.0),
    )


def ccdf_curve_path(values: np.ndarray, shares: np.ndarray, layout: CcdfLayout) -> str:
    """Return the SVG path data drawing the complementary CDF as a step curve.

    The curve steps rather than slopes: samples between the ones that occur hold their
    share flat, which is what a cumulative distribution actually does.

    Args:
        values: The distinct samples.
        shares: Their complementary shares.
        layout: The chart's layout.

    Returns:
        The path ``d`` attribute text.
    """
    commands = [
        f"M {layout.x_of(float(values[0])):.1f} {layout.y_of(float(shares[0])):.1f}",
    ]
    commands.extend(
        f"H {layout.x_of(float(values[index])):.1f} "
        f"V {layout.y_of(float(shares[index])):.1f}"
        for index in range(1, len(values))
    )
    return " ".join(commands)


def ccdf_grid_elements(layout: CcdfLayout) -> list[str]:
    """Return the chart's gridlines, frame, and tick labels.

    Args:
        layout: The chart's layout.

    Returns:
        The elements.
    """
    font = (
        f'font-family="{svg_charts.svg.FONT_STACK}" fill="{CCDF_TEXT_COLOR}" '
        f'font-size="{CCDF_TICK_FONT_SIZE:.0f}"'
    )
    return [
        f'<g stroke="{CCDF_GRID_COLOR}" stroke-width="1" shape-rendering="crispEdges">',
        *(
            f'<line x1="{layout.x_of(tick):.1f}" y1="{layout.top:.1f}" '
            f'x2="{layout.x_of(tick):.1f}" y2="{layout.bottom:.1f}"/>'
            for tick in layout.value_ticks()
        ),
        "</g>",
        (
            f'<rect x="{layout.left:.1f}" y="{layout.top:.1f}" '
            f'width="{layout.plot_width:.1f}" height="{layout.plot_height:.1f}" '
            f'fill="none" stroke="{CCDF_TEXT_COLOR}" stroke-width="1" '
            f'shape-rendering="crispEdges"/>'
        ),
        *(
            f'<text x="{layout.x_of(tick):.1f}" y="{layout.bottom + 26:.1f}" '
            f'{font} text-anchor="middle">{tick:g}</text>'
            for tick in layout.value_ticks()
        ),
        *(
            f'<text x="{layout.left - 14:.1f}" y="{layout.y_of(tick) + 6:.1f}" '
            f'{font} text-anchor="end">{share_tick_text(tick)}</text>'
            for tick in layout.share_ticks()
        ),
    ]


def annotation_elements(
    annotations: tuple[CurveAnnotation, ...],
    layout: CcdfLayout,
) -> list[str]:
    """Return caller-provided labels beside points on the curve.

    Args:
        annotations: Positions and text supplied by the caller.
        layout: The chart's layout.

    Returns:
        The elements.
    """
    font = (
        f'font-family="{svg_charts.svg.FONT_STACK}" fill="{CCDF_TEXT_COLOR}" '
        f'font-size="{CCDF_TICK_FONT_SIZE:.0f}"'
    )
    elements: list[str] = []
    for annotation in annotations:
        x = layout.x_of(annotation.value)
        y = layout.y_of(annotation.share)
        elements.extend((
            (
                f'<line x1="{x:.1f}" y1="{y:.1f}" x2="{x + 24:.1f}" '
                f'y2="{y:.1f}" stroke="{CCDF_KNEE_COLOR}" stroke-width="1"/>'
            ),
            *(
                f'<text x="{x + 30:.1f}" y="{y - 6 + index * 24:.1f}" {font}>'
                f"{html.escape(line)}</text>"
                for index, line in enumerate(annotation.lines)
            ),
        ))
    return elements


def draw_ccdf(
    samples: collections.abc.Sequence[float],
    *,
    title: str,
    x_axis_label: str,
    y_axis_label: str,
    annotations: tuple[CurveAnnotation, ...] = (),
) -> str:
    """Draw numeric samples as a complementary cumulative distribution chart.

    Each point shows the share of samples whose value exceeds that value. The share axis
    is logarithmic because that share spans several orders of magnitude.

    Args:
        samples: The numeric samples to plot.
        title: The visible title and accessible chart label.
        x_axis_label: The unit or meaning of the numeric samples.
        y_axis_label: The label for the complementary share axis.
        annotations: Caller-provided labels beside points on the curve.

    Returns:
        The SVG document text.
    """
    layout = ccdf_layout(samples)
    values, shares = share_curve(samples)
    title_font = (
        f'font-family="{svg_charts.svg.FONT_STACK}" fill="{CCDF_TEXT_COLOR}" '
        f'font-size="{CCDF_TITLE_FONT_SIZE:.0f}"'
    )
    label_font = (
        f'font-family="{svg_charts.svg.FONT_STACK}" fill="{CCDF_TEXT_COLOR}" '
        f'font-size="{CCDF_LABEL_FONT_SIZE:.0f}"'
    )
    elements: list[str] = [
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{layout.width}" '
            f'height="{layout.height}" viewBox="0 0 {layout.width} {layout.height}" '
            f'role="img" aria-label="{html.escape(title)}">'
        ),
        f'<rect width="{layout.width}" height="{layout.height}" fill="#ffffff"/>',
        (
            f'<text x="{layout.width / 2:.1f}" y="{CCDF_PAD_TOP / 2:.1f}" '
            f'{title_font} text-anchor="middle">{html.escape(title)}</text>'
        ),
        *ccdf_grid_elements(layout),
    ]
    if len(values):
        elements.append(
            f'<path d="{ccdf_curve_path(values, shares, layout)}" fill="none" '
            f'stroke="{CCDF_CURVE_COLOR}" stroke-width="2" '
            f'stroke-linejoin="round"/>',
        )
    elements.extend(annotation_elements(annotations, layout))
    elements.extend((
        (
            f'<text x="{layout.left + layout.plot_width / 2:.1f}" '
            f'y="{layout.height - 22:.1f}" {label_font} text-anchor="middle">'
            f"{html.escape(x_axis_label)}</text>"
        ),
        (
            f'<text x="0" y="0" '
            f'transform="translate({CCDF_PAD_LEFT / 3:.1f},'
            f'{(layout.top + layout.bottom) / 2:.1f}) rotate(-90)" {label_font} '
            f'text-anchor="middle">{html.escape(y_axis_label)}</text>'
        ),
    ))
    elements.append("</svg>")
    return "\n".join(elements) + "\n"
