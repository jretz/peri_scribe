"""Application-neutral data and stroke choices for time-series charts."""

from __future__ import annotations

import dataclasses
import datetime
import enum


class StrokeStyle(enum.IntEnum):
    """Order solid legend entries before dashed entries for a stable presentation."""

    SOLID = 0
    DASHED = 1


class SeriesColor(enum.StrEnum):
    """Keep series colors stable when neighboring series are absent."""

    BLUE = "#4c72b0"
    ORANGE = "#dd8452"


@dataclasses.dataclass(frozen=True, kw_only=True)
class SeriesPoint:
    """One numeric observation with the style of its incoming line segment."""

    observation_time: datetime.datetime
    value: float
    style: StrokeStyle = StrokeStyle.SOLID


@dataclasses.dataclass(frozen=True, kw_only=True)
class PlotSeries:
    """One time series with caller-defined labels and color."""

    label: str
    points: tuple[SeriesPoint, ...]
    dashed_label: str | None = None
    color: str = SeriesColor.BLUE
