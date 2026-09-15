"""Building the line-plot data for each fire's KML balloon.

Each fire's history supplies the measurements for its area, perimeter, and cost lines.
These helpers read the history layers into the points and series a plot draws, keeping
only the lines that span enough observation times to show growth.
"""

from __future__ import annotations

import dataclasses
import datetime
import enum
import typing

import peri_scribe.areas
import peri_scribe.geo.measurements
import peri_scribe.geo.parsing
import peri_scribe.incidents
from peri_scribe.units import units


if typing.TYPE_CHECKING:
    import geopandas
    import pint


# A line is skipped unless its measurement exists on at least this many distinct
# observation times; one point cannot show how a fire grew.
MINIMUM_OBSERVATION_TIMES = 2

# Area and cost are scaled to these units before plotting so their values stay in a
# readable range.
ACRES_PER_THOUSAND = 1_000.0
DOLLARS_PER_MILLION = 1_000_000.0

# Containment percentages are reported in whole percent (0-100), so the contained
# perimeter is that fraction of the exterior perimeter length.
CONTAINMENT_PERCENT = 100.0 * units.percent

# The filename suffix for each plot, used to build its image filename.
AREA_PLOT_SUFFIX = "area"
PERIMETER_PLOT_SUFFIX = "perimeter"
COST_PLOT_SUFFIX = "cost"
PERSONNEL_PLOT_SUFFIX = "personnel"

# The legend label for each line. Units are not part of the label; each plot's unit is
# shown once at its y-axis instead.
AREA_SERIES_LABEL = "Mapped area"
REPORTED_AREA_SERIES_LABEL = "Reported Area"
EXTERIOR_PERIMETER_SERIES_LABEL = "Exterior perimeter"
CONTAINED_PERIMETER_SERIES_LABEL = "Contained perimeter"
COST_TO_DATE_SERIES_LABEL = "Cost to date"
ESTIMATED_FINAL_COST_SERIES_LABEL = "Estimated final cost"
PERSONNEL_SERIES_LABEL = "Personnel"

# The unit shown at each plot's y-axis.
AREA_AXIS_LABEL = "Thousands of acres"
PERIMETER_AXIS_LABEL = "Miles"
COST_AXIS_LABEL = "Millions of $"
PERSONNEL_AXIS_LABEL = "Personnel"


@dataclasses.dataclass(frozen=True, kw_only=True)
class SeriesPoint:
    """One measurement at one observation time."""

    observation_time: datetime.datetime
    value: float
    reported: bool = False


@dataclasses.dataclass(frozen=True, kw_only=True)
class ExteriorMeasurement:
    """One perimeter row's observation time and exterior length."""

    observation_time: datetime.datetime | None
    length: pint.Quantity[float] | None


class SeriesColor(enum.StrEnum):
    """Keep measurement colors stable when other series are absent from a chart."""

    BLUE = "#4c72b0"
    ORANGE = "#dd8452"


@dataclasses.dataclass(frozen=True, kw_only=True)
class PlotSeries:
    """One line to draw: a label and its measurements over time."""

    label: str
    points: tuple[SeriesPoint, ...]
    reported_label: str | None = None
    color: SeriesColor = SeriesColor.BLUE


@dataclasses.dataclass(frozen=True, kw_only=True)
class FirePlot:
    """One plot for a fire: its lines, axis label, and the filename suffix."""

    filename_suffix: str
    series: tuple[PlotSeries, ...]
    y_axis_label: str


def exterior_perimeter_measurements(
    frame: geopandas.GeoDataFrame,
) -> tuple[ExteriorMeasurement, ...]:
    """Return each perimeter row's observation time and exterior length in miles.

    Each row's exterior length is measured exactly once here, so the exterior and
    contained perimeter lines built from the measurements never measure the same
    geometry twice.

    Args:
        frame: The perimeter history layer.

    Returns:
        One measurement per row, in the layer's row order.
    """
    if "observation_time" not in frame.columns:
        return ()
    measurements: list[ExteriorMeasurement] = []
    stored_lengths = frame.get(
        peri_scribe.geo.measurements.EXTERIOR_COLUMN,
        [None] * len(frame),
    )
    for observation_time, geometry, stored in zip(
        frame["observation_time"],
        frame.geometry,
        stored_lengths,
        strict=True,
    ):
        measurements.append(
            ExteriorMeasurement(
                observation_time=peri_scribe.geo.parsing.observation_time_from(
                    observation_time,
                ),
                length=peri_scribe.geo.measurements.exterior_perimeter(
                    geometry,
                    stored,
                ),
            ),
        )
    return tuple(measurements)


def exterior_perimeter_points(
    frame: geopandas.GeoDataFrame,
    exterior_measurements: tuple[ExteriorMeasurement, ...] | None = None,
) -> tuple[SeriesPoint, ...]:
    """Return each perimeter's exterior length in miles over time.

    When *exterior_measurements* is supplied it is used instead of measuring *frame*
    again, so callers that build both perimeter lines can measure each geometry once.

    Args:
        frame: The perimeter history layer.
        exterior_measurements: Each row's exterior length, or None to measure *frame*.

    Returns:
        The exterior perimeter points, in the layer's row order.
    """
    if exterior_measurements is None:
        exterior_measurements = exterior_perimeter_measurements(frame)
    points: list[SeriesPoint] = []
    for measurement in exterior_measurements:
        observation_time = measurement.observation_time
        length = measurement.length
        if observation_time is not None and length is not None:
            points.append(
                SeriesPoint(
                    observation_time=observation_time,
                    value=length.m_as("miles"),
                ),
            )
    return tuple(points)


def contained_perimeter_points(
    frame: geopandas.GeoDataFrame,
    exterior_measurements: tuple[ExteriorMeasurement, ...] | None = None,
    *,
    point_rows: geopandas.GeoDataFrame | None = None,
    incident_rows: geopandas.GeoDataFrame | None = None,
    updates: tuple[peri_scribe.incidents.IncidentUpdate, ...] | None = None,
) -> tuple[SeriesPoint, ...]:
    """Estimate contained length from independently updated mapping and containment.

    Each event uses the latest available exterior length and containment percentage.
    Holding the percentage until another report arrives preserves the reporting evidence
    rather than implying continuous containment observations.

    Args:
        frame: The selected perimeter history.
        exterior_measurements: Shared exterior measurements, if already computed.
        point_rows: Incident location rows supplying fallback containment reports.
        incident_rows: The optional independent incident history.
        updates: Already reconciled incident updates, or None to read them.

    Returns:
        Chronological contained-length estimates in miles, beginning when both a mapped
        exterior and a reported containment percentage are available.
    """
    if exterior_measurements is None:
        exterior_measurements = exterior_perimeter_measurements(frame)
    if updates is None:
        updates = peri_scribe.incidents.history(
            frame,
            frame.iloc[0:0] if point_rows is None else point_rows,
            incident_rows,
        )
    lengths = {
        measurement.observation_time: measurement.length
        for measurement in exterior_measurements
        if measurement.observation_time is not None and measurement.length is not None
    }
    percentages = {
        update.observation_time: update.measurements["percent_contained"]
        for update in updates
        if "percent_contained" in update.measurements
    }
    length = None
    percent = None
    points: list[SeriesPoint] = []
    for time in sorted(lengths.keys() | percentages.keys()):
        length = lengths.get(time, length)
        percent = percentages.get(time, percent)
        if length is not None and percent is not None:
            points.append(
                SeriesPoint(
                    observation_time=time,
                    value=length.m_as("miles")
                    * percent
                    / CONTAINMENT_PERCENT.m_as("percent"),
                ),
            )
    return tuple(points)


def incident_points(
    updates: tuple[peri_scribe.incidents.IncidentUpdate, ...],
    column: str,
) -> tuple[SeriesPoint, ...]:
    """Preserve a metric's reporting times without inventing values for missing fields.

    Args:
        updates: Reconciled incident updates in chronological order.
        column: The normalized measurement field to plot.

    Returns:
        Points for updates that supply the field, retaining its source units.
    """
    return tuple(
        SeriesPoint(
            observation_time=update.observation_time,
            value=update.measurements[column],
        )
        for update in updates
        if column in update.measurements
    )


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
    perimeter_rows: geopandas.GeoDataFrame,
    point_rows: geopandas.GeoDataFrame,
    incident_rows: geopandas.GeoDataFrame | None = None,
    *,
    history: peri_scribe.areas.PreparedHistory | None = None,
) -> tuple[FirePlot, ...]:
    """Return the four plots describing one fire's history.

    The shared area selector supplies one line with source provenance. Costs and
    personnel follow incident update times; containment combines the latest known
    percentage with the latest known mapped exterior at each event.

    Args:
        perimeter_rows: The fire's perimeter history rows, already selected.
        point_rows: The fire's point history rows, already selected.
        incident_rows: The optional independent reporting history for this fire.
        history: Already prepared reporting and area evidence, or None to prepare it.

    Returns:
        The fire's plots, in area, perimeter, cost, then personnel order.
    """
    if history is None:
        history = peri_scribe.areas.prepare_history(
            perimeter_rows,
            point_rows,
            incident_rows,
        )
    area_points = tuple(
        SeriesPoint(
            observation_time=estimate.time,
            value=estimate.area.m_as("acres") / ACRES_PER_THOUSAND,
            reported=estimate.source is peri_scribe.areas.AreaSource.REPORTED,
        )
        for estimate in history.estimates
    )
    updates = history.updates
    cost_to_date_points = scaled_points(
        incident_points(updates, "estimated_cost_to_date"),
        DOLLARS_PER_MILLION,
    )
    estimated_final_cost_points = scaled_points(
        incident_points(updates, "estimated_final_cost"),
        DOLLARS_PER_MILLION,
    )
    personnel_points = incident_points(updates, "personnel")
    exterior_measurements = exterior_perimeter_measurements(perimeter_rows)

    return (
        FirePlot(
            filename_suffix=AREA_PLOT_SUFFIX,
            series=(
                PlotSeries(
                    label=AREA_SERIES_LABEL,
                    points=area_points,
                    reported_label=REPORTED_AREA_SERIES_LABEL,
                ),
            ),
            y_axis_label=AREA_AXIS_LABEL,
        ),
        FirePlot(
            filename_suffix=PERIMETER_PLOT_SUFFIX,
            series=(
                PlotSeries(
                    label=EXTERIOR_PERIMETER_SERIES_LABEL,
                    points=exterior_perimeter_points(
                        perimeter_rows,
                        exterior_measurements,
                    ),
                ),
                PlotSeries(
                    label=CONTAINED_PERIMETER_SERIES_LABEL,
                    color=SeriesColor.ORANGE,
                    points=contained_perimeter_points(
                        perimeter_rows,
                        exterior_measurements,
                        point_rows=point_rows,
                        incident_rows=incident_rows,
                        updates=updates,
                    ),
                ),
            ),
            y_axis_label=PERIMETER_AXIS_LABEL,
        ),
        FirePlot(
            filename_suffix=COST_PLOT_SUFFIX,
            series=(
                PlotSeries(label=COST_TO_DATE_SERIES_LABEL, points=cost_to_date_points),
                PlotSeries(
                    label=ESTIMATED_FINAL_COST_SERIES_LABEL,
                    points=estimated_final_cost_points,
                    color=SeriesColor.ORANGE,
                ),
            ),
            y_axis_label=COST_AXIS_LABEL,
        ),
        FirePlot(
            filename_suffix=PERSONNEL_PLOT_SUFFIX,
            series=(
                PlotSeries(
                    label=PERSONNEL_SERIES_LABEL,
                    points=personnel_points,
                ),
            ),
            y_axis_label=PERSONNEL_AXIS_LABEL,
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


def retained_series(series_list: typing.Iterable[PlotSeries]) -> tuple[PlotSeries, ...]:
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
