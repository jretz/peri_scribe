"""Tests for peri_scribe.perimeters.border_classification."""

from __future__ import annotations

import dataclasses

import hypothesis
import hypothesis.strategies
import pytest
import shapely.affinity

import peri_scribe.perimeters.classification_data
import peri_scribe.perimeters.signals
import tests.helpers.factories.peri_scribe.perimeters.signals
import tests.helpers.strategies.geometry
import tests.helpers.strategies.peri_scribe.perimeters.classification
from peri_scribe.units import units


@hypothesis.given(
    geometry=tests.helpers.strategies.geometry.local_shapes(),
    exponent=hypothesis.strategies.integers(-5, 8),
    buffer_meters=hypothesis.strategies.integers(0, 10),
    outside_square_meters=hypothesis.strategies.integers(1, 30),
    fraction_threshold=hypothesis.strategies.sampled_from([0.0, 0.25, 0.5, 1.0]),
)
def test_geometry_signal_scales_with_geometry_and_dimensioned_thresholds(
    geometry: shapely.Geometry,
    exponent: int,
    buffer_meters: int,
    outside_square_meters: int,
    fraction_threshold: float,
) -> None:
    factor = 2.0**exponent
    boundaries = peri_scribe.perimeters.classification_data.Boundaries(
        box=shapely.box(0, 0, 4, 8),
        border=shapely.LineString([(4, 0), (4, 8)]),
    )
    config = dataclasses.replace(
        tests.helpers.factories.peri_scribe.perimeters.signals.CONFIG,
        near_border_buffer=buffer_meters * units.meters,
        outside_area_threshold=outside_square_meters * units.Unit("meters ** 2"),
        outside_area_fraction_threshold=fraction_threshold,
    )
    original = peri_scribe.perimeters.signals.geometry_signal(
        geometry,
        boundaries,
        config,
    )
    scaled = peri_scribe.perimeters.signals.geometry_signal(
        shapely.affinity.scale(geometry, xfact=factor, yfact=factor, origin=(0, 0)),
        peri_scribe.perimeters.classification_data.Boundaries(
            box=shapely.box(0, 0, 4 * factor, 8 * factor),
            border=shapely.LineString([(4 * factor, 0), (4 * factor, 8 * factor)]),
        ),
        dataclasses.replace(
            config,
            near_border_buffer=config.near_border_buffer * factor,
            outside_area_threshold=config.outside_area_threshold * factor**2,
        ),
    )
    assert (scaled.inside, scaled.near, scaled.crosses) == (
        original.inside,
        original.near,
        original.crosses,
    )
    assert scaled.inside_area_fraction == pytest.approx(original.inside_area_fraction)
    assert scaled.outside_area_fraction == pytest.approx(original.outside_area_fraction)
    assert scaled.outside_area.m_as("meters**2") == pytest.approx(
        original.outside_area.m_as("meters**2") * factor**2,
    )
    assert scaled.distance_to_boundary.m_as("meters") == pytest.approx(
        original.distance_to_boundary.m_as("meters") * factor,
    )


@hypothesis.given(
    scenario=tests.helpers.strategies.peri_scribe.perimeters.classification.extent_histories(),
)
def test_extent_signal_ignores_older_observations_and_history_order(
    scenario: tuple[
        list[peri_scribe.perimeters.classification_data.FireObservation],
        list[peri_scribe.perimeters.classification_data.FireObservation],
    ],
) -> None:
    latest, history = scenario
    assert peri_scribe.perimeters.signals.extent_signal(
        history,
        tests.helpers.factories.peri_scribe.perimeters.signals.CONFIG,
    ) == (
        peri_scribe.perimeters.signals.extent_signal(
            latest,
            tests.helpers.factories.peri_scribe.perimeters.signals.CONFIG,
        )
    )
