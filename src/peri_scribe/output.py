"""Output operations for peri_scribe."""

import dataclasses
import html
import json
import math
import pathlib
import shutil

import numpy as np
import pydantic
import structlog

import peri_scribe.models
import peri_scribe.svg
from peri_scribe.units import units


logger = structlog.get_logger()


DATA_DIRECTORY = pathlib.Path("data")

# The fire-scores chart's size.
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

# The score axis aims for this many intervals; the share axis is labelled at every power
# of ten.
CCDF_TARGET_SCORE_INTERVALS = 8

# The fewest decades the share axis spans, so a chart whose shares never fall below a
# tenth still has a readable, non-degenerate axis.
CCDF_MINIMUM_DECADES = 1

CCDF_TITLE = "Fire score distribution"
CCDF_Y_AXIS_LABEL = "Complementary CDF"
CCDF_X_AXIS_LABEL = "Score"


def score_share_curve(scores: list[int]) -> tuple[np.ndarray, np.ndarray]:
    """Return the complementary CDF of *scores*.

    Each point is a distinct score and the share of fires whose score exceeds it. Scores
    whose share is zero are dropped, because a logarithmic share axis cannot show them.

    Args:
        scores: Every fire's score.

    Returns:
        The distinct scores and their complementary shares.

    Examples:
        >>> values, shares = score_share_curve([1, 2, 2, 4])
        >>> values.tolist(), shares.tolist()
        ([1, 2], [0.75, 0.25])
    """
    values, counts = np.unique(scores, return_counts=True)
    total = len(scores)
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
    return max(
        CCDF_MINIMUM_DECADES,
        math.ceil(-math.log10(smallest_share)),
    )


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


def nice_step(span: float, target_intervals: int) -> float:
    """Return a 1/2/2.5/5/10 x 10**n axis step covering *span* in even intervals.

    Args:
        span: The data range the axis must cover.
        target_intervals: The approximate number of intervals wanted.

    Returns:
        The step between ticks.

    Examples:
        >>> round(nice_step(500.0, 8), 3)
        100.0
        >>> round(nice_step(1.0, 8), 3)
        0.2
    """
    if span <= 0:
        return 1.0
    raw = span / target_intervals
    magnitude = 10.0 ** math.floor(math.log10(raw))
    # Dividing by the decade's magnitude always leaves a value below ten, and the ladder
    # ends at ten, so one rung always covers *raw*.
    for multiple in (1.0, 2.0, 2.5, 5.0, 10.0):
        if raw <= multiple * magnitude:
            break
    return multiple * magnitude


def curve_knees(scores: list[int]) -> list[tuple[int, float]]:
    """Return the (score, complementary share) pairs where the CCDF bends most.

    The curve is the complementary share plotted with a logarithmic y-axis, so the fit
    is over (score, log share) coordinates. The two knees are the breakpoints of the
    three-line-segment fit with the smallest total squared error; fewer than five
    visible points leaves no room for two breakpoints.

    Args:
        scores: Every fire's score.

    Returns:
        The knee points as (score, complementary share) pairs, in score order.

    Examples:
        >>> curve_knees([1, 2, 3, 4])
        []
    """
    values, shares = score_share_curve(scores)
    points = np.column_stack((values, np.log10(shares)))

    def fit_error(first: int, second: int) -> float:
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
        (int(values[first]), float(shares[first])),
        (int(values[second]), float(shares[second])),
    ]


@dataclasses.dataclass(frozen=True, kw_only=True)
class CcdfLayout:
    """Where every part of the fire-scores chart is drawn.

    The score axis is linear from zero and the share axis is logarithmic, spanning
    ``decades`` powers of ten below one.
    """

    width: int
    height: int
    left: float
    right: float
    top: float
    bottom: float
    highest_score: float
    decades: int

    @property
    def plot_width(self) -> float:
        """Return the plot area's width.

        Returns:
            The width in pixels.
        """
        return self.right - self.left

    @property
    def plot_height(self) -> float:
        """Return the plot area's height.

        Returns:
            The height in pixels.
        """
        return self.bottom - self.top

    def x_of(self, score: float) -> float:
        """Return the x coordinate of *score*.

        Args:
            score: The score to place.

        Returns:
            The x coordinate.
        """
        return self.left + score / self.highest_score * self.plot_width

    def y_of(self, share: float) -> float:
        """Return the y coordinate of *share* on the logarithmic share axis.

        Args:
            share: The complementary share to place.

        Returns:
            The y coordinate.
        """
        fraction = (math.log10(share) + self.decades) / self.decades
        return self.bottom - fraction * self.plot_height

    def score_ticks(self) -> tuple[float, ...]:
        """Return the score-axis tick values.

        Returns:
            The tick values from zero to the axis top.
        """
        step = nice_step(self.highest_score, CCDF_TARGET_SCORE_INTERVALS)
        return tuple(
            index * step for index in range(round(self.highest_score / step) + 1)
        )

    def share_ticks(self) -> tuple[float, ...]:
        """Return the share-axis tick values, one per decade.

        Returns:
            The tick values, largest first.
        """
        return tuple(10.0**-power for power in range(self.decades + 1))


def ccdf_layout(scores: list[int]) -> CcdfLayout:
    """Return where every part of the fire-scores chart is drawn.

    Args:
        scores: Every fire's score.

    Returns:
        The layout.
    """
    width = int(CCDF_CHART_WIDTH.magnitude)
    height = int(CCDF_CHART_HEIGHT.magnitude)
    values, shares = score_share_curve(scores)
    return CcdfLayout(
        width=width,
        height=height,
        left=CCDF_PAD_LEFT,
        right=width - CCDF_PAD_RIGHT,
        top=CCDF_PAD_TOP,
        bottom=height - CCDF_PAD_BOTTOM,
        highest_score=float(values.max()) if len(values) else 1.0,
        decades=share_decades(float(shares.min()) if len(shares) else 1.0),
    )


def ccdf_curve_path(
    values: np.ndarray,
    shares: np.ndarray,
    layout: CcdfLayout,
) -> str:
    """Return the SVG path data drawing the complementary CDF as a step curve.

    The curve steps rather than slopes: scores between the ones that occur hold their
    share flat, which is what a cumulative distribution actually does.

    Args:
        values: The distinct scores.
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
        f'font-family="{peri_scribe.svg.FONT_STACK}" fill="{CCDF_TEXT_COLOR}" '
        f'font-size="{CCDF_TICK_FONT_SIZE:.0f}"'
    )
    return [
        f'<g stroke="{CCDF_GRID_COLOR}" stroke-width="1" shape-rendering="crispEdges">',
        *(
            f'<line x1="{layout.x_of(tick):.1f}" y1="{layout.top:.1f}" '
            f'x2="{layout.x_of(tick):.1f}" y2="{layout.bottom:.1f}"/>'
            for tick in layout.score_ticks()
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
            for tick in layout.score_ticks()
        ),
        *(
            f'<text x="{layout.left - 14:.1f}" y="{layout.y_of(tick) + 6:.1f}" '
            f'{font} text-anchor="end">{share_tick_text(tick)}</text>'
            for tick in layout.share_ticks()
        ),
    ]


def ccdf_knee_elements(
    scores: list[int],
    layout: CcdfLayout,
) -> list[str]:
    """Return the knee labels for the chart.

    A failure to find or label the knees leaves the chart unlabelled rather than failing
    the run.

    Args:
        scores: Every fire's score.
        layout: The chart's layout.

    Returns:
        The elements.
    """
    try:
        knees = curve_knees(scores)
    except Exception:
        logger.exception("Skipped fire scores knee labels")
        return []
    font = (
        f'font-family="{peri_scribe.svg.FONT_STACK}" fill="{CCDF_TEXT_COLOR}" '
        f'font-size="{CCDF_TICK_FONT_SIZE:.0f}"'
    )
    elements: list[str] = []
    for score, share in knees:
        x = layout.x_of(float(score))
        y = layout.y_of(share)
        percentile = (1 - share) * 100
        elements.extend(
            (
                (
                    f'<line x1="{x:.1f}" y1="{y:.1f}" x2="{x + 24:.1f}" '
                    f'y2="{y:.1f}" stroke="{CCDF_KNEE_COLOR}" stroke-width="1"/>'
                ),
                f'<text x="{x + 30:.1f}" y="{y - 6:.1f}" {font}>score {score}</text>',
                (
                    f'<text x="{x + 30:.1f}" y="{y + 18:.1f}" {font}>'
                    f"percentile {percentile:.1f}</text>"
                ),
            ),
        )
    return elements


def ccdf_svg(document: peri_scribe.models.FireScores) -> str:
    """Return *document*'s scores as one SVG chart.

    Each point shows the share of fires whose score exceeds that score. The share axis
    is logarithmic because that share spans several orders of magnitude.

    Args:
        document: The validated fire scores to plot.

    Returns:
        The SVG document text.
    """
    scores = [entry.score for entry in document.fires]
    layout = ccdf_layout(scores)
    values, shares = score_share_curve(scores)
    title_font = (
        f'font-family="{peri_scribe.svg.FONT_STACK}" fill="{CCDF_TEXT_COLOR}" '
        f'font-size="{CCDF_TITLE_FONT_SIZE:.0f}"'
    )
    label_font = (
        f'font-family="{peri_scribe.svg.FONT_STACK}" fill="{CCDF_TEXT_COLOR}" '
        f'font-size="{CCDF_LABEL_FONT_SIZE:.0f}"'
    )
    elements: list[str] = [
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{layout.width}" '
            f'height="{layout.height}" viewBox="0 0 {layout.width} {layout.height}" '
            f'role="img" aria-label="{html.escape(CCDF_TITLE)}">'
        ),
        f'<rect width="{layout.width}" height="{layout.height}" fill="#ffffff"/>',
        (
            f'<text x="{layout.width / 2:.1f}" y="{CCDF_PAD_TOP / 2:.1f}" '
            f'{title_font} text-anchor="middle">{html.escape(CCDF_TITLE)}</text>'
        ),
        *ccdf_grid_elements(layout),
    ]
    if len(values):
        elements.append(
            f'<path d="{ccdf_curve_path(values, shares, layout)}" fill="none" '
            f'stroke="{CCDF_CURVE_COLOR}" stroke-width="2" '
            f'stroke-linejoin="round"/>',
        )
    elements.extend(ccdf_knee_elements(scores, layout))
    elements.extend(
        (
            (
                f'<text x="{layout.left + layout.plot_width / 2:.1f}" '
                f'y="{layout.height - 22:.1f}" {label_font} text-anchor="middle">'
                f"{html.escape(CCDF_X_AXIS_LABEL)}</text>"
            ),
            (
                f'<text x="0" y="0" '
                f'transform="translate({CCDF_PAD_LEFT / 3:.1f},'
                f'{(layout.top + layout.bottom) / 2:.1f}) rotate(-90)" {label_font} '
                f'text-anchor="middle">{html.escape(CCDF_Y_AXIS_LABEL)}</text>'
            ),
        ),
    )
    elements.append("</svg>")
    return "\n".join(elements) + "\n"


def ccdf_html(document: peri_scribe.models.FireScores) -> str:
    """Return *document*'s scores as an HTML page holding an inline SVG chart.

    The chart is inline rather than referenced so the file stands alone: it can be
    opened, mailed, or served without the chart going missing.

    Args:
        document: The validated fire scores to plot.

    Returns:
        The HTML page.
    """
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        "<title>PeriScribe fire scores</title>\n"
        "</head>\n"
        "<body>\n"
        f"{ccdf_svg(document)}\n"
        "</body>\n"
        "</html>\n"
    )


def write_geopackage(
    path: pathlib.Path,
    layers: list[peri_scribe.models.LayerData],
) -> None:
    if path.exists():
        path.unlink()
        logger.debug("Replaced existing", path=path.name)
    mode = "w"
    for layer_data in layers:
        layer_data.dataframe.to_file(
            path,
            driver="GPKG",
            layer=layer_data.name,
            mode=mode,
        )
        logger.debug(
            "Wrote layer",
            layer=layer_data.name,
            features=len(layer_data.dataframe),
        )
        mode = "a"


def remove_directory_tree(path: pathlib.Path) -> None:
    """Remove *path* and everything under it, when it is a directory.

    Args:
        path: The directory tree to remove.
    """
    if path.is_dir():
        shutil.rmtree(path)


def write_document(
    path: pathlib.Path,
    document: peri_scribe.models.FireIndex | peri_scribe.models.FireScores,
) -> None:
    """Write *document* to *path* as pretty-printed JSON.

    The fire index and the fire scores are both versioned documents holding the season's
    fires, so they share one on-disk shape and one writer.

    Args:
        path: The JSON file to write.
        document: The validated document to serialize.
    """
    with path.open("w", encoding="utf-8") as file:
        json.dump(document.model_dump(mode="json"), file, indent=4)
    logger.debug("Wrote document", path=path.name, fires=len(document.fires))


def read_document[Document: pydantic.BaseModel](
    path: pathlib.Path,
    model: type[Document],
) -> Document:
    """Return the document *path* holds, validated by *model*.

    Args:
        path: The JSON file to read.
        model: The model that validates the file's contents.

    Returns:
        The validated document.
    """
    return model.model_validate_json(path.read_text(encoding="utf-8"))


def write_fire_scores_ccdf(
    path: pathlib.Path,
    document: peri_scribe.models.FireScores,
) -> None:
    """Write *document*'s scores to *path* as an HTML page with an inline SVG chart.

    Args:
        path: The HTML file to write.
        document: The validated fire scores to plot.
    """
    path.write_text(ccdf_html(document), encoding="utf-8")
    logger.debug("Wrote fire scores ccdf", path=path.name)


def configure_logging(log_level: str) -> None:
    """Configure structlog with the minimum log level."""
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="%Y-%m-%dT%H:%M:%S%z", utc=False),
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
    )
