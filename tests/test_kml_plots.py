"""Tests for peri_scribe.kml_plots."""

from __future__ import annotations

import datetime

import geopandas
import pytest
import shapely.geometry

import peri_scribe.kml_plots
import peri_scribe.units


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def square(side: float) -> shapely.geometry.Polygon:
    """Return a square of *side* degrees centered at the origin.

    Args:
        side: The length of each side.

    Returns:
        The square.
    """
    half = side / 2
    return shapely.geometry.box(-half, -half, half, half)


def exterior_length(geometry: shapely.Geometry) -> float:
    """Return *geometry*'s exterior perimeter length, which is always known.

    Args:
        geometry: A non-empty polygon.

    Returns:
        The exterior perimeter length in miles.
    """
    length = peri_scribe.units.exterior_perimeter_in_miles(geometry)
    assert length is not None
    return length


def observation_time(day: int, hour: int = 0) -> datetime.datetime:
    """Return an aware UTC observation time on August *day*.

    Args:
        day: The day of the month.
        hour: The hour of the day.

    Returns:
        The observation time.
    """
    return datetime.datetime(2026, 8, day, hour, tzinfo=datetime.UTC)


def series_point(
    day: int,
    value: float,
    hour: int = 0,
) -> peri_scribe.kml_plots.SeriesPoint:
    """Return a series point at *day* with *value*.

    Args:
        day: The day of the observation.
        value: The measurement.
        hour: The hour of the observation.

    Returns:
        The point.
    """
    return peri_scribe.kml_plots.SeriesPoint(
        observation_time=observation_time(day, hour),
        value=value,
    )


def geo_frame(
    columns: dict[str, list[object]],
    geometry: list[shapely.Geometry],
) -> geopandas.GeoDataFrame:
    """Build a WGS84 GeoDataFrame from *columns* and *geometry*.

    Args:
        columns: Each column name and its row values.
        geometry: The geometry of each row.

    Returns:
        The frame.
    """
    return geopandas.GeoDataFrame(
        columns,
        geometry=geometry,
        crs="EPSG:4326",
    )


def perimeter_frame(
    observations: list[
        tuple[
            datetime.datetime | None,
            shapely.Geometry,
            float | None,
            float | None,
            float | None,
            float | None,
        ]
    ],
) -> geopandas.GeoDataFrame:
    """Build a perimeter history frame.

    Each observation is (observation_time, geometry, area_acres, percent_contained,
    estimated_cost_to_date, estimated_final_cost).

    Args:
        observations: One tuple per perimeter row.

    Returns:
        The perimeter history frame.
    """
    return geo_frame(
        {
            "fire_identifier": ["id-bug"] * len(observations),
            "fire_name": ["Bug"] * len(observations),
            "observation_time": [row[0] for row in observations],
            "area_acres": [row[2] for row in observations],
            "percent_contained": [row[3] for row in observations],
            "estimated_cost_to_date": [row[4] for row in observations],
            "estimated_final_cost": [row[5] for row in observations],
        },
        [row[1] for row in observations],
    )


def point_frame(
    observations: list[
        tuple[
            datetime.datetime | None,
            float | None,
            float | None,
            float | None,
        ]
    ],
) -> geopandas.GeoDataFrame:
    """Build a point history frame.

    Each observation is (observation_time, incident_size, estimated_cost_to_date,
    estimated_final_cost).

    Args:
        observations: One tuple per point row.

    Returns:
        The point history frame.
    """
    return geo_frame(
        {
            "fire_identifier": ["id-bug"] * len(observations),
            "fire_name": ["Bug"] * len(observations),
            "observation_time": [row[0] for row in observations],
            "incident_size": [row[1] for row in observations],
            "estimated_cost_to_date": [row[2] for row in observations],
            "estimated_final_cost": [row[3] for row in observations],
        },
        [shapely.geometry.Point(0.0, 0.0)] * len(observations),
    )


def test_matching_rows_matches_identifier() -> None:
    frame = geo_frame(
        {
            "fire_identifier": ["id-bug", "id-alta", "id-bug"],
            "fire_name": ["Bug", "ALTA", "Bug"],
        },
        [square(1.0), square(2.0), square(3.0)],
    )
    matched = peri_scribe.kml_plots.matching_rows(
        frame,
        frozenset({"id-bug"}),
        "Bug",
    )
    assert list(matched["fire_identifier"]) == ["id-bug", "id-bug"]


def test_matching_rows_falls_back_to_name() -> None:
    frame = geo_frame(
        {
            "fire_identifier": ["id-bug", "id-alta", "id-bug"],
            "fire_name": ["Bug", "ALTA", "Bug"],
        },
        [square(1.0), square(2.0), square(3.0)],
    )
    matched = peri_scribe.kml_plots.matching_rows(
        frame,
        frozenset(),
        "Bug",
    )
    assert list(matched["fire_name"]) == ["Bug", "Bug"]


def test_matching_rows_returns_empty_without_match() -> None:
    frame = geo_frame(
        {
            "fire_identifier": ["id-bug"],
            "fire_name": ["Bug"],
        },
        [square(1.0)],
    )
    matched = peri_scribe.kml_plots.matching_rows(
        frame,
        frozenset({"id-alta"}),
        "ALTA",
    )
    assert matched.empty


def test_series_points_reads_values_and_times() -> None:
    frame = geo_frame(
        {
            "observation_time": [
                observation_time(1),
                observation_time(2),
            ],
            "area_acres": [10.0, 20.0],
        },
        [square(1.0), square(2.0)],
    )
    assert peri_scribe.kml_plots.series_points(
        frame,
        "observation_time",
        "area_acres",
    ) == (
        series_point(1, 10.0),
        series_point(2, 20.0),
    )


def test_series_points_skips_missing_values() -> None:
    frame = geo_frame(
        {
            "observation_time": [
                observation_time(1),
                None,
                observation_time(3),
            ],
            "area_acres": [10.0, 20.0, None],
        },
        [square(1.0), square(2.0), square(3.0)],
    )
    assert peri_scribe.kml_plots.series_points(
        frame,
        "observation_time",
        "area_acres",
    ) == (series_point(1, 10.0),)


def test_series_points_returns_empty_for_missing_columns() -> None:
    frame = geo_frame(
        {"observation_time": [observation_time(1)]},
        [square(1.0)],
    )
    assert (
        peri_scribe.kml_plots.series_points(
            frame,
            "observation_time",
            "area_acres",
        )
        == ()
    )


def test_exterior_perimeter_points_computes_lengths() -> None:
    frame = perimeter_frame(
        [
            (observation_time(1), square(1.0), None, None, None, None),
            (observation_time(2), square(2.0), None, None, None, None),
        ],
    )
    points = peri_scribe.kml_plots.exterior_perimeter_points(frame)
    assert [point.observation_time for point in points] == [
        observation_time(1),
        observation_time(2),
    ]
    assert points[0].value == pytest.approx(
        exterior_length(square(1.0)),
    )
    assert points[1].value == pytest.approx(
        exterior_length(square(2.0)),
    )


def test_exterior_perimeter_points_skips_missing_time() -> None:
    frame = perimeter_frame(
        [
            (observation_time(1), square(1.0), None, None, None, None),
            (None, square(2.0), None, None, None, None),
        ],
    )
    points = peri_scribe.kml_plots.exterior_perimeter_points(frame)
    assert [point.observation_time for point in points] == [observation_time(1)]


def test_contained_perimeter_points_multiplies_by_percent() -> None:
    frame = perimeter_frame(
        [
            (observation_time(1), square(1.0), None, 50.0, None, None),
            (observation_time(2), square(2.0), None, 25.0, None, None),
        ],
    )
    points = peri_scribe.kml_plots.contained_perimeter_points(frame)
    assert points[0].value == pytest.approx(exterior_length(square(1.0)) * 0.5)
    assert points[1].value == pytest.approx(exterior_length(square(2.0)) * 0.25)


def test_contained_perimeter_points_skips_missing_percent_or_time() -> None:
    frame = perimeter_frame(
        [
            (observation_time(1), square(1.0), None, 50.0, None, None),
            (observation_time(2), square(2.0), None, None, None, None),
            (None, square(3.0), None, 50.0, None, None),
        ],
    )
    points = peri_scribe.kml_plots.contained_perimeter_points(frame)
    assert [point.observation_time for point in points] == [observation_time(1)]


def test_exterior_perimeter_points_returns_empty_without_observation_time() -> None:
    frame = geo_frame({"area_acres": [1.0]}, [square(1.0)])
    assert peri_scribe.kml_plots.exterior_perimeter_points(frame) == ()


def test_contained_perimeter_points_returns_empty_without_observation_time() -> None:
    frame = geo_frame({"percent_contained": [50.0]}, [square(1.0)])
    assert peri_scribe.kml_plots.contained_perimeter_points(frame) == ()


def test_contained_perimeter_points_returns_empty_without_percent() -> None:
    frame = geo_frame({"observation_time": [observation_time(1)]}, [square(1.0)])
    assert peri_scribe.kml_plots.contained_perimeter_points(frame) == ()


def test_merge_series_points_combines_in_chronological_order() -> None:
    merged = peri_scribe.kml_plots.merge_series_points(
        [series_point(3, 30.0), series_point(1, 10.0)],
        [series_point(2, 20.0)],
    )
    assert [point.value for point in merged] == [10.0, 20.0, 30.0]


def test_scaled_points_divides_each_value() -> None:
    scaled = peri_scribe.kml_plots.scaled_points(
        (series_point(1, 10.0), series_point(2, 20.0)),
        1000.0,
    )
    assert [point.observation_time for point in scaled] == [
        observation_time(1),
        observation_time(2),
    ]
    assert [point.value for point in scaled] == pytest.approx([0.01, 0.02])


def test_fire_plots_builds_three_plots_with_labels() -> None:
    plots = peri_scribe.kml_plots.fire_plots(
        frozenset({"id-bug"}),
        "Bug",
        perimeter_frame(
            [
                (
                    observation_time(1),
                    square(1.0),
                    10.0,
                    50.0,
                    1000.0,
                    2000.0,
                ),
                (
                    observation_time(2),
                    square(2.0),
                    20.0,
                    50.0,
                    2000.0,
                    3000.0,
                ),
            ],
        ),
        point_frame([]),
    )
    assert [plot.filename_suffix for plot in plots] == [
        "area",
        "perimeter",
        "cost",
    ]
    assert [plot.series[0].label for plot in plots] == [
        "Area",
        "Exterior perimeter",
        "Cost to date",
    ]
    assert [plot.y_axis_label for plot in plots] == [
        "Thousands of acres",
        "Miles",
        "Millions of $",
    ]
    assert plots[1].series[1].label == "Contained perimeter"
    assert plots[2].series[1].label == "Estimated final cost"


def test_fire_plots_merges_area_and_cost_from_both_feeds() -> None:
    plots = peri_scribe.kml_plots.fire_plots(
        frozenset({"id-bug"}),
        "Bug",
        perimeter_frame(
            [
                (
                    observation_time(1),
                    square(1.0),
                    10.0,
                    None,
                    1000.0,
                    2000.0,
                ),
            ],
        ),
        point_frame(
            [
                (observation_time(2), 20.0, 1500.0, 2500.0),
            ],
        ),
    )
    area = plots[0].series[0]
    assert [point.value for point in area.points] == pytest.approx([0.01, 0.02])
    cost = plots[2].series[0]
    assert [point.value for point in cost.points] == pytest.approx([0.001, 0.0015])
    final_cost = plots[2].series[1]
    assert [point.value for point in final_cost.points] == pytest.approx(
        [0.002, 0.0025],
    )


def test_has_multiple_observation_times_requires_two_distinct_times() -> None:
    assert peri_scribe.kml_plots.has_multiple_observation_times(
        (series_point(1, 10.0), series_point(2, 20.0)),
    )
    assert not peri_scribe.kml_plots.has_multiple_observation_times(())
    assert not peri_scribe.kml_plots.has_multiple_observation_times(
        (series_point(1, 10.0),),
    )
    assert not peri_scribe.kml_plots.has_multiple_observation_times(
        (series_point(1, 10.0), series_point(1, 20.0)),
    )


def test_retained_series_drops_lines_with_too_few_times() -> None:
    retained = peri_scribe.kml_plots.retained_series(
        (
            peri_scribe.kml_plots.PlotSeries(
                label="Area",
                points=(series_point(1, 10.0), series_point(2, 20.0)),
            ),
            peri_scribe.kml_plots.PlotSeries(
                label="Cost to date",
                points=(series_point(1, 1000.0),),
            ),
        ),
    )
    assert [series.label for series in retained] == ["Area"]


def test_plot_frame_melts_series() -> None:
    frame = peri_scribe.kml_plots.plot_frame(
        (
            peri_scribe.kml_plots.PlotSeries(
                label="Area",
                points=(series_point(1, 10.0),),
            ),
            peri_scribe.kml_plots.PlotSeries(
                label="Cost to date",
                points=(series_point(1, 1000.0),),
            ),
        ),
    )
    assert list(frame.columns) == ["label", "observation_time", "value"]
    assert frame["label"].tolist() == ["Area", "Cost to date"]
    assert frame["value"].tolist() == [10.0, 1000.0]


def test_format_tick_uses_thousands_for_large_values() -> None:
    assert peri_scribe.kml_plots.format_tick(1234567.0, 0) == "1,234,567"


def test_format_tick_uses_one_decimal_for_medium_values() -> None:
    assert peri_scribe.kml_plots.format_tick(33.1, 0) == "33.1"


def test_format_tick_uses_two_decimals_for_small_values() -> None:
    assert peri_scribe.kml_plots.format_tick(0.5, 0) == "0.5"


def test_format_tick_drops_trailing_zero() -> None:
    assert peri_scribe.kml_plots.format_tick(33.0, 0) == "33"
    assert peri_scribe.kml_plots.format_tick(0.0, 0) == "0"


def test_x_axis_ticks_returns_empty_without_points() -> None:
    assert peri_scribe.kml_plots.x_axis_ticks(()) == ()


def test_x_axis_ticks_uses_each_midnight_when_days_fit() -> None:
    series = (
        peri_scribe.kml_plots.PlotSeries(
            label="Area",
            points=(series_point(1, 10.0), series_point(3, 20.0)),
        ),
    )
    assert peri_scribe.kml_plots.x_axis_ticks(series) == (
        observation_time(1),
        observation_time(2),
        observation_time(3),
    )


def test_x_axis_ticks_thins_when_days_do_not_fit() -> None:
    series = (
        peri_scribe.kml_plots.PlotSeries(
            label="Area",
            points=(series_point(1, 10.0), series_point(20, 20.0)),
        ),
    )
    assert peri_scribe.kml_plots.x_axis_ticks(series) == (
        observation_time(1),
        observation_time(5),
        observation_time(9),
        observation_time(13),
        observation_time(17),
        observation_time(20),
    )


def test_render_plot_returns_png_for_one_series() -> None:
    content = peri_scribe.kml_plots.render_plot(
        (
            peri_scribe.kml_plots.PlotSeries(
                label="Area",
                points=(series_point(1, 10.0), series_point(2, 20.0)),
            ),
        ),
        y_axis_label="Thousands of acres",
    )
    assert content.startswith(PNG_SIGNATURE)


def test_render_plot_returns_png_for_multiple_series() -> None:
    content = peri_scribe.kml_plots.render_plot(
        (
            peri_scribe.kml_plots.PlotSeries(
                label="Cost to date",
                points=(series_point(1, 10.0), series_point(2, 20.0)),
            ),
            peri_scribe.kml_plots.PlotSeries(
                label="Estimated final cost",
                points=(series_point(1, 5.0), series_point(2, 15.0)),
            ),
        ),
        y_axis_label="Millions of $",
    )
    assert content.startswith(PNG_SIGNATURE)


def test_plot_filename_joins_prefix_and_suffix() -> None:
    assert peri_scribe.kml_plots.plot_filename("id-bug", "area") == "id-bug-area.png"


def test_filename_prefix_uses_identifier() -> None:
    assert peri_scribe.kml_plots.filename_prefix("2026-cabug-000001", "Bug") == (
        "2026-cabug-000001"
    )


def test_filename_prefix_slugifies_name() -> None:
    assert peri_scribe.kml_plots.filename_prefix(None, "Santa Rosa!") == "santa-rosa"


def test_filename_prefix_falls_back_to_fire_for_empty_name() -> None:
    assert peri_scribe.kml_plots.filename_prefix(None, "!!!") == "fire"


def test_plot_images_renders_retained_plots_and_skips_empty() -> None:
    images = peri_scribe.kml_plots.plot_images(
        (
            peri_scribe.kml_plots.FirePlot(
                filename_suffix="area",
                series=(
                    peri_scribe.kml_plots.PlotSeries(
                        label="Area",
                        points=(series_point(1, 10.0), series_point(2, 20.0)),
                    ),
                ),
                y_axis_label="Thousands of acres",
            ),
            peri_scribe.kml_plots.FirePlot(
                filename_suffix="cost",
                series=(
                    peri_scribe.kml_plots.PlotSeries(
                        label="Cost to date",
                        points=(series_point(1, 1000.0),),
                    ),
                ),
                y_axis_label="Millions of $",
            ),
        ),
        "id-bug",
    )
    assert [image.filename for image in images] == ["id-bug-area.png"]
    assert images[0].content.startswith(PNG_SIGNATURE)
