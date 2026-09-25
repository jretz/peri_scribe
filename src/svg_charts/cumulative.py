"""Raster empirical CDFs with shared elapsed-time axes and compact statistics."""

from __future__ import annotations

import dataclasses
import io
import math
import re
import typing

import PIL.Image
import PIL.ImageDraw
import PIL.ImageFont

import svg_charts.svg
from measurement_units import units


if typing.TYPE_CHECKING:
    import pint


SECONDS_PER_MINUTE = 60
SECONDS_PER_HOUR = 3600
SECONDS_PER_DAY = 86400
CDF_CHART_WIDTH = 1000 * units.pixels
CDF_CHART_HEIGHT = 768 * units.pixels
BACKGROUND_COLOR = "#111827"
TEXT_COLOR = "#e5e7eb"
FONT_SIZE = 20.0
RASTER_SCALE = 2


@dataclasses.dataclass(frozen=True, kw_only=True)
class Series:
    """A caller supplies observations and labels independently of rendering."""

    label: str
    durations: tuple[pint.Quantity, ...]
    color: str


def duration_label(seconds: float) -> str:
    """Keep ticks and statistics readable from milliseconds through days.

    Args:
        seconds: A duration converted to seconds at the rendering boundary.

    Returns:
        A compact, unit-bearing duration label.
    """
    if seconds < 1:
        return f"{seconds * 1000:.3g} ms"
    if seconds < SECONDS_PER_MINUTE:
        return f"{seconds:.3g} s"
    if seconds < SECONDS_PER_HOUR:
        minutes, remainder = divmod(round(seconds), SECONDS_PER_MINUTE)
        return f"{minutes}m {remainder:02d}s" if remainder else f"{minutes}m"
    if seconds < SECONDS_PER_DAY:
        hours, minutes = divmod(round(seconds / SECONDS_PER_MINUTE), SECONDS_PER_MINUTE)
        return f"{hours}h {minutes:02d}m" if minutes else f"{hours}h"
    return f"{seconds / SECONDS_PER_DAY:.3g} d"


def legend_label(series: Series, ordered: list[float]) -> str:
    """Use inverse empirical percentiles without interpolating between runs.

    Args:
        series: The caller's label and samples.
        ordered: Durations sorted in seconds.

    Returns:
        The series label, count, and its P50, P90, and maximum.
    """
    if not ordered:
        return f"{series.label} (n = 0)\nP50 —   ·   P90 —   ·   Max —"
    values = (
        ordered[math.ceil(len(ordered) * 0.5) - 1],
        ordered[math.ceil(len(ordered) * 0.9) - 1],
        ordered[-1],
    )
    statistics = "   ·   ".join(
        f"{label} {duration_label(value)}"
        for label, value in zip(("P50", "P90", "Max"), values, strict=True)
    )
    return f"{series.label} (n = {len(ordered):,})\n{statistics}"


@dataclasses.dataclass(frozen=True, kw_only=True)
class Layout:
    """Elapsed time uses logarithmic coordinates; cumulative share stays linear."""

    lower: float
    upper: float
    top: float
    left: float = 140.0
    right: float = 970.0
    bottom: float = 638.0

    def x_of(self, seconds: float) -> float:
        """Keep zero-duration observations at the positive logarithmic boundary.

        Args:
            seconds: A duration in seconds at the rendering boundary.

        Returns:
            Its horizontal pixel coordinate.
        """
        fraction = math.log(max(self.lower, seconds) / self.lower) / math.log(
            self.upper / self.lower,
        )
        return self.left + fraction * (self.right - self.left)

    def y_of(self, share: float) -> float:
        """Leave a little space above complete observations.

        Args:
            share: The fraction of samples at or below an elapsed time.

        Returns:
            Its vertical pixel coordinate.
        """
        return self.bottom - share / 1.04 * (self.bottom - self.top)

    def time_ticks(self) -> tuple[float, ...]:
        """Measured label widths prevent crowded ticks on short or broad windows.

        Returns:
            Readable elapsed-time ticks within the displayed interval.
        """
        candidates = sorted({
            base * multiple
            for base, multiples in (
                (0.001, (1, 2, 5)),
                (0.01, (1, 2, 5)),
                (0.1, (1, 2, 5)),
                (1, (1, 2, 5, 10, 30)),
                (60, (1, 2, 5, 10, 30)),
                (3600, (1, 2, 5, 10, 30)),
                (86400, (1, 2, 5, 10, 30)),
            )
            for multiple in multiples
            if self.lower <= base * multiple <= self.upper
        })
        selected = []
        previous_right = -math.inf
        for value in candidates or [self.lower, self.upper]:
            half_width = svg_charts.svg.text_width(duration_label(value), FONT_SIZE) / 2
            position = self.x_of(value)
            if position - half_width >= previous_right + 16:
                selected.append(value)
                previous_right = position + half_width
        return tuple(selected)


def layout(values: list[list[float]]) -> Layout:
    """Keep the chart stable when an interval has no observations or only zeros.

    Args:
        values: Each series' ordered samples in seconds.

    Returns:
        A shared axis interval and room for two-line legend entries.
    """
    positives = [value for ordered in values for value in ordered if value > 0]
    return Layout(
        lower=min(positives, default=1) / 1.4,
        upper=max(positives, default=10) * 1.4,
        top=48 + 64 * len(values),
    )


def curve_points(ordered: list[float], chart: Layout) -> list[tuple[float, float]]:
    """Empirical shares change vertically at observations and stay flat between them.

    Args:
        ordered: Durations sorted in seconds.
        chart: The shared logarithmic elapsed-time and linear-share coordinates.

    Returns:
        The marker-free step curve, extending to both horizontal boundaries.
    """
    points = [(chart.left, chart.y_of(0))]
    for index, value in enumerate(ordered):
        position = chart.x_of(value)
        points.extend((
            (position, chart.y_of(index / len(ordered))),
            (position, chart.y_of((index + 1) / len(ordered))),
        ))
    points.append((chart.right, chart.y_of(1 if ordered else 0)))
    return points


@dataclasses.dataclass(frozen=True, kw_only=True)
class Canvas:
    """A bundled font and supersampling keep rendering portable and deterministic."""

    image: PIL.Image.Image
    font: PIL.ImageFont.FreeTypeFont | PIL.ImageFont.ImageFont

    def line(
        self,
        points: list[tuple[float, float]],
        color: str,
        width: float = 1,
    ) -> None:
        """Smooth axes and curves at their final display size.

        Args:
            points: Connected pixel coordinates in the final chart.
            color: The line color.
            width: Its final width in pixels.
        """
        PIL.ImageDraw.Draw(self.image).line(
            [(round(x * RASTER_SCALE), round(y * RASTER_SCALE)) for x, y in points],
            fill=color,
            width=round(width * RASTER_SCALE),
        )

    def text(
        self,
        position: tuple[float, float],
        value: str,
        *,
        anchor: str = "mm",
    ) -> None:
        """Supplement the bundled font with the chart's arrow and window separator.

        Args:
            position: The text anchor in final-image pixels.
            value: The label to display.
            anchor: Pillow's horizontal and vertical text alignment.
        """
        parts = re.split(r"([→—])", value)
        widths = [
            FONT_SIZE
            if part in {"→", "—"}
            else self.font.getlength(part) / RASTER_SCALE
            for part in parts
        ]
        alignment = {"l": 0, "m": 0.5, "r": 1}[anchor[0]]
        x = position[0] - alignment * sum(widths)
        for part, width in zip(parts, widths, strict=True):
            if part in {"→", "—"}:
                center = position[1] + (FONT_SIZE / 2 if anchor[1] == "t" else 0)
                self.symbol((x, center), part)
            else:
                PIL.ImageDraw.Draw(self.image).text(
                    (x * RASTER_SCALE, position[1] * RASTER_SCALE),
                    part,
                    font=self.font,
                    fill=TEXT_COLOR,
                    anchor="l" + anchor[1],
                )
            x += width

    def symbol(self, position: tuple[float, float], value: str) -> None:
        """Small vector glyphs avoid dependence on platform font coverage.

        Args:
            position: The left edge and vertical center in final-image pixels.
            value: The right arrow or em dash used by chart labels.
        """
        x, y = position
        self.line([(x + 1, y), (x + FONT_SIZE - 1, y)], TEXT_COLOR, 1.3)
        if value == "→":
            self.line(
                [
                    (x + FONT_SIZE - 6, y - 5),
                    (x + FONT_SIZE - 1, y),
                    (x + FONT_SIZE - 6, y + 5),
                ],
                TEXT_COLOR,
                1.3,
            )

    def vertical_text(self, position: tuple[float, float], value: str) -> None:
        """A rotated label retains the same font size as horizontal labels.

        Args:
            position: The center in final-image pixels.
            value: The vertical axis label.
        """
        left, top, right, bottom = self.font.getbbox(value)
        label = PIL.Image.new(
            "RGBA",
            (math.ceil(right - left) + 8, math.ceil(bottom - top) + 8),
        )
        PIL.ImageDraw.Draw(label).text(
            (4 - left, 4 - top),
            value,
            font=self.font,
            fill=TEXT_COLOR,
        )
        rotated = label.transpose(PIL.Image.Transpose.ROTATE_90)
        x, y = position
        self.image.paste(
            rotated,
            (
                round(x * RASTER_SCALE - rotated.width / 2),
                round(y * RASTER_SCALE - rotated.height / 2),
            ),
            rotated,
        )


def axes(canvas: Canvas, chart: Layout) -> None:
    """Gridlines and labels make both distributions readable on their shared axes.

    Args:
        canvas: The image being drawn.
        chart: The shared logarithmic elapsed-time and linear-share coordinates.
    """
    for index in range(6):
        share = index / 5
        position = chart.y_of(share)
        canvas.line([(chart.left, position), (chart.right, position)], "#334155")
        canvas.text((chart.left - 15, position), f"{share:.0%}", anchor="rm")
    for seconds in chart.time_ticks():
        position = chart.x_of(seconds)
        canvas.line([(position, chart.top), (position, chart.bottom)], "#263445")
        canvas.text((position, chart.bottom + 28), duration_label(seconds))
    canvas.line(
        [
            (chart.left, chart.top),
            (chart.left, chart.bottom),
            (chart.right, chart.bottom),
        ],
        "#64748b",
    )
    canvas.text(((chart.left + chart.right) / 2, chart.bottom + 60), "Elapsed time")
    canvas.vertical_text((40, (chart.top + chart.bottom) / 2), "Cumulative share")


def image(series: tuple[Series, ...], footer: str) -> PIL.Image.Image:
    """Draw combined CDFs directly, without a plotting backend or font discovery.

    Args:
        series: Samples to compare on the same axes.
        footer: The measurement window printed below the axes.

    Returns:
        The 1000-by-768-pixel chart on an opaque dark background.
    """
    width = int(CDF_CHART_WIDTH.m_as("pixels"))
    height = int(CDF_CHART_HEIGHT.m_as("pixels"))
    canvas = Canvas(
        image=PIL.Image.new(
            "RGB",
            (width * RASTER_SCALE, height * RASTER_SCALE),
            BACKGROUND_COLOR,
        ),
        font=PIL.ImageFont.load_default(size=FONT_SIZE * RASTER_SCALE),
    )
    values = [
        sorted(float(value.m_as("seconds")) for value in item.durations)
        for item in series
    ]
    chart = layout(values)
    axes(canvas, chart)
    for index, (item, ordered) in enumerate(zip(series, values, strict=True)):
        canvas.line(curve_points(ordered, chart), item.color, 3)
        top = 30 + index * 64
        canvas.line(
            [(chart.left, top + 10), (chart.left + 60, top + 10)],
            item.color,
            3,
        )
        for line, text in enumerate(legend_label(item, ordered).splitlines()):
            canvas.text((chart.left + 80, top + line * 28), text, anchor="lt")
    canvas.text((width / 2, height - 36), footer)
    return canvas.image.resize((width, height), PIL.Image.Resampling.LANCZOS)


def png(series: tuple[Series, ...], footer: str) -> bytes:
    """Encode directly drawn CDFs without temporary files or external renderers.

    Args:
        series: Samples to plot.
        footer: The measurement window shown below the axes.

    Returns:
        PNG bytes suitable for saving or an inline terminal image.
    """
    with io.BytesIO() as output:
        image(series, footer).save(output, format="PNG")
        return output.getvalue()
