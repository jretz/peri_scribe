"""Selection retains complete facts while limiting eager identity guard memory."""

from __future__ import annotations

import datetime
import pathlib

import pint
import pytest

import peri_scribe.areas
import peri_scribe.execution
import peri_scribe.presentation.prepared_cache
import peri_scribe.presentation.selection
import spatial_data.product_cache
import tests.helpers.factories.geography
from measurement_units import units


@pytest.mark.parametrize("cached", [True, False])
def test_prepare_histories_retains_guards_only_for_qualifying_evidence(
    tmp_path: pathlib.Path,
    *,
    cached: bool,
) -> None:
    points = tests.helpers.factories.geography.geo_frame(
        {
            "fire_identifier": ["unknown", "small", "boundary", "large"],
            "fire_name": ["Unknown", "Small", "Boundary", "Large"],
            "observation_time": [datetime.datetime(2026, 9, 1, tzinfo=datetime.UTC)]
            * 4,
            "incident_size": [None, 24.0, 25.0, 40.0],
        },
        [None] * 4,
    )
    empty = points.iloc[0:0]
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "runtime"):
        if cached:
            peri_scribe.presentation.selection.prepare_histories(empty, points)
        with peri_scribe.execution.sharing():
            histories = peri_scribe.presentation.selection.prepare_histories(
                empty,
                points,
            )
            assert set(histories) == {
                ("id", identifier)
                for identifier in ("unknown", "small", "boundary", "large")
            }
            for key, history in histories.items():
                identity = peri_scribe.execution.get(
                    peri_scribe.execution.Group.HISTORIES,
                    ("prepared_history_identity", id(history)),
                )
                assert isinstance(
                    identity,
                    peri_scribe.presentation.prepared_cache.HistoryIdentity,
                ) == (key[1] in {"boundary", "large"})
                payload = peri_scribe.presentation.prepared_cache.history_bytes(history)
                assert (
                    peri_scribe.presentation.prepared_cache.read_history(
                        payload,
                        remember_identity=False,
                    )
                    == history
                )


@pytest.mark.parametrize(
    ("historical_area", "latest_area", "retained"),
    [
        (None, 40.0 * units.acres, False),
        (24.0 * units.acres, 40.0 * units.acres, False),
        (25.0 * units.acres, 10.0 * units.acres, True),
        (40.0 * units.acres, 10.0 * units.acres, True),
        (40.0 * units.meters, 40.0 * units.acres, False),
        (pint.UnitRegistry().Quantity(40.0, "acre"), 40.0 * units.acres, False),
    ],
)
def test_remember_qualified_history_uses_historical_area_without_changing_facts(
    historical_area: pint.Quantity[float] | None,
    latest_area: pint.Quantity[float],
    *,
    retained: bool,
) -> None:
    history = peri_scribe.areas.PreparedHistory(
        updates=(),
        estimates=(),
        latest_area=latest_area,
        historical_area=historical_area,
    )
    payload = peri_scribe.presentation.prepared_cache.history_bytes(history)
    with peri_scribe.execution.sharing():
        peri_scribe.presentation.selection.remember_qualified_history(history, payload)
        assert (
            isinstance(
                peri_scribe.execution.get(
                    peri_scribe.execution.Group.HISTORIES,
                    ("prepared_history_identity", id(history)),
                ),
                peri_scribe.presentation.prepared_cache.HistoryIdentity,
            )
            == retained
        )
    assert peri_scribe.presentation.prepared_cache.history_bytes(history) == payload
