"""Tests for peri_scribe.kml_plot_data."""

from __future__ import annotations

import json

import pytest

import peri_scribe.kml_plot_data
import tests.kml_plot_helpers


def test_matching_rows_matches_identifier() -> None:
    frame = tests.kml_plot_helpers.geo_frame(
        {
            "fire_identifier": ["id-bug", "id-alta", "id-bug"],
            "fire_name": ["Bug", "ALTA", "Bug"],
        },
        [
            tests.kml_plot_helpers.square(1.0),
            tests.kml_plot_helpers.square(2.0),
            tests.kml_plot_helpers.square(3.0),
        ],
    )
    matched = peri_scribe.kml_plot_data.matching_rows(
        frame,
        frozenset({"id-bug"}),
        "Bug",
    )
    assert list(matched["fire_identifier"]) == ["id-bug", "id-bug"]


def test_matching_rows_falls_back_to_name() -> None:
    frame = tests.kml_plot_helpers.geo_frame(
        {
            "fire_identifier": ["id-bug", "id-alta", "id-bug"],
            "fire_name": ["Bug", "ALTA", "Bug"],
        },
        [
            tests.kml_plot_helpers.square(1.0),
            tests.kml_plot_helpers.square(2.0),
            tests.kml_plot_helpers.square(3.0),
        ],
    )
    matched = peri_scribe.kml_plot_data.matching_rows(
        frame,
        frozenset(),
        "Bug",
    )
    assert list(matched["fire_name"]) == ["Bug", "Bug"]


def test_matching_rows_returns_empty_without_match() -> None:
    frame = tests.kml_plot_helpers.geo_frame(
        {
            "fire_identifier": ["id-bug"],
            "fire_name": ["Bug"],
        },
        [tests.kml_plot_helpers.square(1.0)],
    )
    matched = peri_scribe.kml_plot_data.matching_rows(
        frame,
        frozenset({"id-alta"}),
        "ALTA",
    )
    assert matched.empty


def test_series_points_reads_values_and_times() -> None:
    frame = tests.kml_plot_helpers.geo_frame(
        {
            "observation_time": [
                tests.kml_plot_helpers.observation_time(1),
                tests.kml_plot_helpers.observation_time(2),
            ],
            "area_acres": [10.0, 20.0],
        },
        [tests.kml_plot_helpers.square(1.0), tests.kml_plot_helpers.square(2.0)],
    )
    assert peri_scribe.kml_plot_data.series_points(
        frame,
        "observation_time",
        "area_acres",
    ) == (
        tests.kml_plot_helpers.series_point(1, 10.0),
        tests.kml_plot_helpers.series_point(2, 20.0),
    )


def test_series_points_skips_missing_values() -> None:
    frame = tests.kml_plot_helpers.geo_frame(
        {
            "observation_time": [
                tests.kml_plot_helpers.observation_time(1),
                None,
                tests.kml_plot_helpers.observation_time(3),
            ],
            "area_acres": [10.0, 20.0, None],
        },
        [
            tests.kml_plot_helpers.square(1.0),
            tests.kml_plot_helpers.square(2.0),
            tests.kml_plot_helpers.square(3.0),
        ],
    )
    assert peri_scribe.kml_plot_data.series_points(
        frame,
        "observation_time",
        "area_acres",
    ) == (tests.kml_plot_helpers.series_point(1, 10.0),)


def test_series_points_returns_empty_for_missing_columns() -> None:
    frame = tests.kml_plot_helpers.geo_frame(
        {"observation_time": [tests.kml_plot_helpers.observation_time(1)]},
        [tests.kml_plot_helpers.square(1.0)],
    )
    assert (
        peri_scribe.kml_plot_data.series_points(
            frame,
            "observation_time",
            "area_acres",
        )
        == ()
    )


def test_exterior_perimeter_points_computes_lengths() -> None:
    frame = tests.kml_plot_helpers.perimeter_frame(
        [
            (
                tests.kml_plot_helpers.observation_time(1),
                tests.kml_plot_helpers.square(1.0),
                None,
                None,
                None,
                None,
            ),
            (
                tests.kml_plot_helpers.observation_time(2),
                tests.kml_plot_helpers.square(2.0),
                None,
                None,
                None,
                None,
            ),
        ],
    )
    points = peri_scribe.kml_plot_data.exterior_perimeter_points(frame)
    assert [point.observation_time for point in points] == [
        tests.kml_plot_helpers.observation_time(1),
        tests.kml_plot_helpers.observation_time(2),
    ]
    assert points[0].value == pytest.approx(
        tests.kml_plot_helpers.exterior_length(tests.kml_plot_helpers.square(1.0)),
    )
    assert points[1].value == pytest.approx(
        tests.kml_plot_helpers.exterior_length(tests.kml_plot_helpers.square(2.0)),
    )


def test_exterior_perimeter_points_skips_missing_time() -> None:
    frame = tests.kml_plot_helpers.perimeter_frame(
        [
            (
                tests.kml_plot_helpers.observation_time(1),
                tests.kml_plot_helpers.square(1.0),
                None,
                None,
                None,
                None,
            ),
            (None, tests.kml_plot_helpers.square(2.0), None, None, None, None),
        ],
    )
    points = peri_scribe.kml_plot_data.exterior_perimeter_points(frame)
    assert [point.observation_time for point in points] == [
        tests.kml_plot_helpers.observation_time(1),
    ]


def test_contained_perimeter_points_multiplies_by_percent() -> None:
    frame = tests.kml_plot_helpers.perimeter_frame(
        [
            (
                tests.kml_plot_helpers.observation_time(1),
                tests.kml_plot_helpers.square(1.0),
                None,
                50.0,
                None,
                None,
            ),
            (
                tests.kml_plot_helpers.observation_time(2),
                tests.kml_plot_helpers.square(2.0),
                None,
                25.0,
                None,
                None,
            ),
        ],
    )
    points = peri_scribe.kml_plot_data.contained_perimeter_points(frame)
    assert points[0].value == pytest.approx(
        tests.kml_plot_helpers.exterior_length(tests.kml_plot_helpers.square(1.0))
        * 0.5,
    )
    assert points[1].value == pytest.approx(
        tests.kml_plot_helpers.exterior_length(tests.kml_plot_helpers.square(2.0))
        * 0.25,
    )


def test_contained_perimeter_points_skips_missing_percent_or_time() -> None:
    frame = tests.kml_plot_helpers.perimeter_frame(
        [
            (
                tests.kml_plot_helpers.observation_time(1),
                tests.kml_plot_helpers.square(1.0),
                None,
                50.0,
                None,
                None,
            ),
            (
                tests.kml_plot_helpers.observation_time(2),
                tests.kml_plot_helpers.square(2.0),
                None,
                None,
                None,
                None,
            ),
            (None, tests.kml_plot_helpers.square(3.0), None, 50.0, None, None),
        ],
    )
    points = peri_scribe.kml_plot_data.contained_perimeter_points(frame)
    assert [point.observation_time for point in points] == [
        tests.kml_plot_helpers.observation_time(1),
    ]


def test_exterior_perimeter_points_returns_empty_without_observation_time() -> None:
    frame = tests.kml_plot_helpers.geo_frame(
        {"area_acres": [1.0]},
        [tests.kml_plot_helpers.square(1.0)],
    )
    assert peri_scribe.kml_plot_data.exterior_perimeter_points(frame) == ()


def test_contained_perimeter_points_returns_empty_without_observation_time() -> None:
    frame = tests.kml_plot_helpers.geo_frame(
        {"percent_contained": [50.0]},
        [tests.kml_plot_helpers.square(1.0)],
    )
    assert peri_scribe.kml_plot_data.contained_perimeter_points(frame) == ()


def test_contained_perimeter_points_returns_empty_without_percent() -> None:
    frame = tests.kml_plot_helpers.geo_frame(
        {"observation_time": [tests.kml_plot_helpers.observation_time(1)]},
        [tests.kml_plot_helpers.square(1.0)],
    )
    assert peri_scribe.kml_plot_data.contained_perimeter_points(frame) == ()


def test_merge_series_points_combines_in_chronological_order() -> None:
    merged = peri_scribe.kml_plot_data.merge_series_points(
        [
            tests.kml_plot_helpers.series_point(3, 30.0),
            tests.kml_plot_helpers.series_point(1, 10.0),
        ],
        [tests.kml_plot_helpers.series_point(2, 20.0)],
    )
    assert [point.value for point in merged] == [10.0, 20.0, 30.0]


def test_scaled_points_divides_each_value() -> None:
    scaled = peri_scribe.kml_plot_data.scaled_points(
        (
            tests.kml_plot_helpers.series_point(1, 10.0),
            tests.kml_plot_helpers.series_point(2, 20.0),
        ),
        1000.0,
    )
    assert [point.observation_time for point in scaled] == [
        tests.kml_plot_helpers.observation_time(1),
        tests.kml_plot_helpers.observation_time(2),
    ]
    assert [point.value for point in scaled] == pytest.approx([0.01, 0.02])


def test_source_attribute_points_reads_values_and_times() -> None:
    frame = tests.kml_plot_helpers.geo_frame(
        {
            "observation_time": [
                tests.kml_plot_helpers.observation_time(1),
                tests.kml_plot_helpers.observation_time(2),
            ],
            "source_attributes": [
                json.dumps({"TotalIncidentPersonnel": 100}),
                json.dumps({"TotalIncidentPersonnel": 200}),
            ],
        },
        [tests.kml_plot_helpers.square(1.0), tests.kml_plot_helpers.square(2.0)],
    )
    assert peri_scribe.kml_plot_data.source_attribute_points(
        frame,
        "TotalIncidentPersonnel",
    ) == (
        tests.kml_plot_helpers.series_point(1, 100.0),
        tests.kml_plot_helpers.series_point(2, 200.0),
    )


def test_source_attribute_points_skips_missing_values() -> None:
    frame = tests.kml_plot_helpers.geo_frame(
        {
            "observation_time": [
                tests.kml_plot_helpers.observation_time(1),
                None,
                tests.kml_plot_helpers.observation_time(3),
            ],
            "source_attributes": [
                json.dumps({"TotalIncidentPersonnel": 100}),
                json.dumps({"TotalIncidentPersonnel": 200}),
                json.dumps({}),
            ],
        },
        [
            tests.kml_plot_helpers.square(1.0),
            tests.kml_plot_helpers.square(2.0),
            tests.kml_plot_helpers.square(3.0),
        ],
    )
    assert peri_scribe.kml_plot_data.source_attribute_points(
        frame,
        "TotalIncidentPersonnel",
    ) == (tests.kml_plot_helpers.series_point(1, 100.0),)


def test_source_attribute_points_returns_empty_for_missing_columns() -> None:
    frame = tests.kml_plot_helpers.geo_frame(
        {"observation_time": [tests.kml_plot_helpers.observation_time(1)]},
        [tests.kml_plot_helpers.square(1.0)],
    )
    assert (
        peri_scribe.kml_plot_data.source_attribute_points(
            frame,
            "TotalIncidentPersonnel",
        )
        == ()
    )


def test_fire_plots_builds_four_plots_with_labels() -> None:
    plots = peri_scribe.kml_plot_data.fire_plots(
        frozenset({"id-bug"}),
        "Bug",
        tests.kml_plot_helpers.perimeter_frame(
            [
                (
                    tests.kml_plot_helpers.observation_time(1),
                    tests.kml_plot_helpers.square(1.0),
                    10.0,
                    50.0,
                    1000.0,
                    2000.0,
                ),
                (
                    tests.kml_plot_helpers.observation_time(2),
                    tests.kml_plot_helpers.square(2.0),
                    20.0,
                    50.0,
                    2000.0,
                    3000.0,
                ),
            ],
        ),
        tests.kml_plot_helpers.point_frame([]),
    )
    assert [plot.filename_suffix for plot in plots] == [
        "area",
        "perimeter",
        "cost",
        "personnel",
    ]
    assert [plot.series[0].label for plot in plots] == [
        "Area",
        "Exterior perimeter",
        "Cost to date",
        "Personnel",
    ]
    assert [plot.y_axis_label for plot in plots] == [
        "Thousands of acres",
        "Miles",
        "Millions of $",
        "Personnel",
    ]
    assert plots[1].series[1].label == "Contained perimeter"
    assert plots[2].series[1].label == "Estimated final cost"


def test_fire_plots_merges_area_and_cost_from_both_feeds() -> None:
    plots = peri_scribe.kml_plot_data.fire_plots(
        frozenset({"id-bug"}),
        "Bug",
        tests.kml_plot_helpers.perimeter_frame(
            [
                (
                    tests.kml_plot_helpers.observation_time(1),
                    tests.kml_plot_helpers.square(1.0),
                    10.0,
                    None,
                    1000.0,
                    2000.0,
                ),
            ],
        ),
        tests.kml_plot_helpers.point_frame(
            [
                (tests.kml_plot_helpers.observation_time(2), 20.0, 1500.0, 2500.0),
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


def test_fire_plots_merges_personnel_from_both_feeds() -> None:
    perimeter = tests.kml_plot_helpers.geo_frame(
        {
            "fire_identifier": ["id-bug", "id-bug"],
            "fire_name": ["Bug", "Bug"],
            "observation_time": [
                tests.kml_plot_helpers.observation_time(1),
                tests.kml_plot_helpers.observation_time(3),
            ],
            "source_attributes": [
                json.dumps({"attr_TotalIncidentPersonnel": 100}),
                json.dumps({"attr_TotalIncidentPersonnel": 300}),
            ],
        },
        [tests.kml_plot_helpers.square(1.0), tests.kml_plot_helpers.square(2.0)],
    )
    point = tests.kml_plot_helpers.geo_frame(
        {
            "fire_identifier": ["id-bug"],
            "fire_name": ["Bug"],
            "observation_time": [tests.kml_plot_helpers.observation_time(2)],
            "source_attributes": [
                json.dumps({"TotalIncidentPersonnel": 200}),
            ],
        },
        [tests.kml_plot_helpers.square(3.0)],
    )
    plots = peri_scribe.kml_plot_data.fire_plots(
        frozenset({"id-bug"}),
        "Bug",
        perimeter,
        point,
    )
    personnel = plots[3].series[0]
    assert [point.value for point in personnel.points] == pytest.approx(
        [100.0, 200.0, 300.0],
    )


def test_has_multiple_observation_times_requires_two_distinct_times() -> None:
    assert peri_scribe.kml_plot_data.has_multiple_observation_times(
        (
            tests.kml_plot_helpers.series_point(1, 10.0),
            tests.kml_plot_helpers.series_point(2, 20.0),
        ),
    )
    assert not peri_scribe.kml_plot_data.has_multiple_observation_times(())
    assert not peri_scribe.kml_plot_data.has_multiple_observation_times(
        (tests.kml_plot_helpers.series_point(1, 10.0),),
    )
    assert not peri_scribe.kml_plot_data.has_multiple_observation_times(
        (
            tests.kml_plot_helpers.series_point(1, 10.0),
            tests.kml_plot_helpers.series_point(1, 20.0),
        ),
    )


def test_retained_series_drops_lines_with_too_few_times() -> None:
    retained = peri_scribe.kml_plot_data.retained_series(
        (
            peri_scribe.kml_plot_data.PlotSeries(
                label="Area",
                points=(
                    tests.kml_plot_helpers.series_point(1, 10.0),
                    tests.kml_plot_helpers.series_point(2, 20.0),
                ),
            ),
            peri_scribe.kml_plot_data.PlotSeries(
                label="Cost to date",
                points=(tests.kml_plot_helpers.series_point(1, 1000.0),),
            ),
        ),
    )
    assert [series.label for series in retained] == ["Area"]


def test_plot_frame_melts_series() -> None:
    frame = peri_scribe.kml_plot_data.plot_frame(
        (
            peri_scribe.kml_plot_data.PlotSeries(
                label="Area",
                points=(tests.kml_plot_helpers.series_point(1, 10.0),),
            ),
            peri_scribe.kml_plot_data.PlotSeries(
                label="Cost to date",
                points=(tests.kml_plot_helpers.series_point(1, 1000.0),),
            ),
        ),
    )
    assert list(frame.columns) == ["label", "observation_time", "value"]
    assert frame["label"].tolist() == ["Area", "Cost to date"]
    assert frame["value"].tolist() == [10.0, 1000.0]
