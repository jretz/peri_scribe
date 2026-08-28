"""Building the line-plot data for each fire's KML balloon.

Each fire's history supplies the measurements for its area, perimeter, and cost lines.
These helpers read the history layers into the points and series a plot draws, keeping
only the lines that span enough observation times to show growth.
"""

from __future__ import annotations

import dataclasses
import datetime
import typing

import pandas as pd

import peri_scribe.geo_package
import peri_scribe.kml_row_values
import peri_scribe.units


if typing.TYPE_CHECKING:
    import geopandas


# A line is skipped unless its measurement exists on at least this many distinct
# observation times; one point cannot show how a fire grew.
MINIMUM_OBSERVATION_TIMES = 2

# Area and cost are scaled to these units before plotting so their values stay in a
# readable range.
ACRES_PER_THOUSAND = 1_000.0
DOLLARS_PER_MILLION = 1_000_000.0

# Containment percentages are reported in whole percent (0-100), so the contained
# perimeter is that fraction of the exterior perimeter length.
CONTAINMENT_IN_PERCENT = 100.0

# Column names in the tidy frame handed to seaborn.
LABEL_COLUMN = "label"
OBSERVATION_TIME_COLUMN = "observation_time"
VALUE_COLUMN = "value"

# The filename suffix for each plot, used to build its image filename.
AREA_PLOT_SUFFIX = "area"
PERIMETER_PLOT_SUFFIX = "perimeter"
COST_PLOT_SUFFIX = "cost"
PERSONNEL_PLOT_SUFFIX = "personnel"

# The legend label for each line. Units are not part of the label; each plot's unit is
# shown once at its y-axis instead.
AREA_SERIES_LABEL = "Area"
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

# The personnel count is preserved under each feed's own source-attribute key: the point
# feed keeps the plain name and the perimeter feed prefixes it with ``attr_``.
POINT_PERSONNEL_ATTRIBUTE_KEY = "TotalIncidentPersonnel"
PERIMETER_PERSONNEL_ATTRIBUTE_KEY = "attr_TotalIncidentPersonnel"


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


def matching_rows(
    frame: geopandas.GeoDataFrame,
    fire_identifiers: frozenset[str],
    entry_name: str,
) -> geopandas.GeoDataFrame:
    """Return the rows of *frame* that belong to one fire.

    A fire with identifiers is matched by those identifiers; a fire without any is
    matched by name. The layer's rows are already in chronological order, so the result
    preserves that order.

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

    The contained length is the exterior perimeter length multiplied by the containment
    percentage, so a perimeter without a percentage has no contained length.

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


def source_attribute_points(
    frame: geopandas.GeoDataFrame,
    key: str,
) -> tuple[SeriesPoint, ...]:
    """Return each row's *key* from its preserved source attributes over time.

    The history layers keep each row's original source attributes as JSON, which is
    where the personnel count lives under the feed's own key. Rows with a missing
    observation time or attribute value are left out, since neither can be plotted. When
    either column is absent the layer carries no measurement to plot.

    Args:
        frame: The history layer to read.
        key: The attribute key to read from each row's preserved attributes.

    Returns:
        The plotted points, in the layer's row order.
    """
    if (
        "observation_time" not in frame.columns
        or "source_attributes" not in frame.columns
    ):
        return ()
    points: list[SeriesPoint] = []
    for observation_time, attributes_value in zip(
        frame["observation_time"],
        frame["source_attributes"],
        strict=True,
    ):
        time = peri_scribe.geo_package.observation_time_from(observation_time)
        attributes = peri_scribe.kml_row_values.source_attributes_dictionary(
            attributes_value,
        )
        value = attributes.get(key) if attributes is not None else None
        number = peri_scribe.geo_package.numeric_value(value)
        if time is not None and number is not None:
            points.append(SeriesPoint(observation_time=time, value=number))
    return tuple(points)


def fire_plots(
    fire_identifiers: frozenset[str],
    entry_name: str,
    perimeters: geopandas.GeoDataFrame,
    points: geopandas.GeoDataFrame,
) -> tuple[FirePlot, ...]:
    """Return the four plots describing one fire's history.

    The area plot has one line, the perimeter plot has exterior and contained perimeter
    lines, and the cost plot has cost-to-date and estimated-final-cost lines. Area and
    cost are read from both the perimeter and point histories, while the two perimeter
    lengths come only from the perimeter history, whose geometry is the only source of a
    length. The personnel plot's single line is read from both histories' preserved
    source attributes, since the personnel count has no derived column.

    Args:
        fire_identifiers: The fire's identifiers.
        entry_name: The fire's name, used when it has no identifiers.
        perimeters: The perimeter history layer.
        points: The point history layer.

    Returns:
        The fire's plots, in area, perimeter, cost, then personnel order.
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
    personnel_points = merge_series_points(
        source_attribute_points(
            perimeter_rows,
            PERIMETER_PERSONNEL_ATTRIBUTE_KEY,
        ),
        source_attribute_points(point_rows, POINT_PERSONNEL_ATTRIBUTE_KEY),
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
