"""Tests for peri_scribe.sources.borders."""

from __future__ import annotations

import hypothesis
import pytest
import shapely.geometry

import peri_scribe.exceptions
import peri_scribe.sources.borders
import tests.helpers.strategies.peri_scribe.sources.borders


@hypothesis.given(
    scenario=tests.helpers.strategies.peri_scribe.sources.borders.split_paths(),
)
def test_ordered_border_coordinates_ignores_splitting_order_and_direction(
    scenario: tuple[list[tuple[float, float]], list[shapely.LineString]],
) -> None:
    coordinates, parts = scenario
    assert peri_scribe.sources.borders.ordered_border_coordinates(parts) == coordinates


@hypothesis.given(
    scenario=tests.helpers.strategies.peri_scribe.sources.borders.split_paths(),
)
def test_ordered_border_coordinates_rejects_disconnected_closed_components(
    scenario: tuple[list[tuple[float, float]], list[shapely.LineString]],
) -> None:
    _coordinates, parts = scenario
    closed_component = shapely.LineString([(172, 0), (173, 0), (173, 1), (172, 0)])
    with pytest.raises(
        peri_scribe.exceptions.AdministrativeBoundariesError,
        match="not a single continuous path",
    ):
        peri_scribe.sources.borders.ordered_border_coordinates(
            [*parts, closed_component],
        )
