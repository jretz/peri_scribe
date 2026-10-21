"""Qualified manifests preserve identity namespaces and latest row demand."""

from __future__ import annotations

import compression.zstd
import dataclasses

import hypothesis
import hypothesis.strategies

import peri_scribe.kml.prepared_inputs
import peri_scribe.presentation.prepared_cache
import tests.helpers.factories.peri_scribe.kml.prepared_inputs
from measurement_units import units


@hypothesis.given(
    selections=hypothesis.strategies.lists(
        hypothesis.strategies.lists(
            hypothesis.strategies.integers(min_value=0, max_value=1_000),
            max_size=10,
        ).map(tuple),
        max_size=10,
    ).map(tuple),
)
def test_latest_positions_demands_exactly_each_final_selected_row(
    selections: tuple[tuple[int, ...], ...],
) -> None:
    actual = peri_scribe.kml.prepared_inputs.latest_positions(selections)
    assert len(actual) == len(set(actual))
    assert list(actual) == sorted(actual)
    assert all(
        any(selection and selection[-1] == row for selection in selections)
        for row in actual
    )
    assert all(not selection or selection[-1] in actual for selection in selections)


@hypothesis.given(
    value=hypothesis.strategies.text(max_size=40),
    area=hypothesis.strategies.floats(
        min_value=25,
        max_value=1_000_000,
        allow_nan=False,
        allow_infinity=False,
    ),
    unit=hypothesis.strategies.sampled_from(["acre", "hectare", "meter ** 2"]),
    level=hypothesis.strategies.sampled_from([-5, 1, 2, 9]),
)
def test_decoded_histories_preserves_units_and_distinct_identity_namespaces(
    value: str,
    area: float,
    unit: str,
    level: int,
) -> None:
    source = tests.helpers.factories.peri_scribe.kml.prepared_inputs.history(area)
    quantity = (area * units.acres).to(unit)
    history = dataclasses.replace(
        source,
        latest_area=quantity,
        historical_area=quantity,
    )
    content = compression.zstd.compress(
        peri_scribe.presentation.prepared_cache.history_bytes(history),
        level=level,
    )
    records = tuple(((tag, value), content) for tag in ("id", "name", "component"))
    actual = peri_scribe.kml.prepared_inputs.decoded_histories(records)
    assert set(actual) == {("id", value), ("name", value), ("component", value)}
    assert all(item == history for item in actual.values())
    for item in actual.values():
        assert item.historical_area is not None
        assert item.historical_area.units == quantity.units
