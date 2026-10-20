"""Growth measurement follows polygon-only and cumulative surface policy."""

import pytest

import peri_scribe.perimeters.progression
import spatial_data.surface_measurements
import tests.formal.helpers.growth_measurement
import tests.formal.helpers.oracle


def test_area_filters_nonpolygon_contributions_as_lean_specifies() -> None:
    geometries = tests.formal.helpers.growth_measurement.mixed_geometries()
    expected = tests.formal.helpers.oracle.evaluate(
        [
            " ".join([
                "growth-filter",
                *tests.formal.helpers.growth_measurement.geometry_tokens(geometry),
            ])
            for geometry in geometries
        ],
        executable="oracleSpatial",
    )
    for geometry, (area,) in zip(geometries, expected, strict=True):
        assert spatial_data.surface_measurements.area(geometry).m_as(
            "meters ** 2",
        ) == pytest.approx(
            area / tests.formal.helpers.growth_measurement.AREA_SCALE,
            abs=tests.formal.helpers.growth_measurement.AREA_TOLERANCE,
        )


def test_added_areas_matches_lean_weighted_surface_coverage() -> None:
    cases = tests.formal.helpers.growth_measurement.histories()
    weights = tests.formal.helpers.growth_measurement.weights()
    expected = tests.formal.helpers.oracle.evaluate(
        [
            tests.formal.helpers.growth_measurement.command(history, weights)
            for history in cases
        ],
        executable="oracleSpatial",
    )
    for history, areas in zip(cases, expected, strict=True):
        actual = peri_scribe.perimeters.progression.added_areas(
            tests.formal.helpers.growth_measurement.footprint(mask) for mask in history
        )
        assert [area.m_as("meters ** 2") for area in actual] == pytest.approx(
            [
                area / tests.formal.helpers.growth_measurement.AREA_SCALE
                for area in areas
            ],
            abs=tests.formal.helpers.growth_measurement.AREA_TOLERANCE,
        )
