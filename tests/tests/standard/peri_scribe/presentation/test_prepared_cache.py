"""Persistent fire facts retain original measurement and timestamp representations."""

from __future__ import annotations

import pandas as pd
import pytest

import peri_scribe.areas
import peri_scribe.incidents
import peri_scribe.presentation.descriptions
import peri_scribe.presentation.prepared_cache
import spatial_data.cache_values
from measurement_units import units


def test_history_bytes_round_trip_preserves_exact_evidence() -> None:
    time = pd.Timestamp("2026-09-01T00:00:00.123456789Z")
    assert isinstance(time, pd.Timestamp)
    area = 1234.5678901234567 * units.Unit("meters ** 2")
    history = peri_scribe.areas.PreparedHistory(
        updates=(
            peri_scribe.incidents.IncidentUpdate(
                observation_time=time,
                report_time=time,
                confirmed=True,
                source="source",
                source_file="snapshot.gpkg",
                serial=7,
                measurements={"incident_size": 42.0},
            ),
        ),
        estimates=(
            peri_scribe.areas.AreaEstimate(
                time=time,
                observation_time=time,
                area=area,
                source=peri_scribe.areas.AreaSource.MAPPED,
                source_file="snapshot.gpkg",
            ),
        ),
        latest_area=area,
        historical_area=area,
    )

    restored = peri_scribe.presentation.prepared_cache.read_history(
        peri_scribe.presentation.prepared_cache.history_bytes(history),
    )

    assert restored == history
    assert restored.estimates[0].area.units == area.units
    assert isinstance(restored.estimates[0].time, pd.Timestamp)
    assert restored.estimates[0].time.value == time.value


def test_read_history_rejects_coerced_measurement_fields() -> None:
    payload = spatial_data.cache_values.dumps({
        "updates": (),
        "estimates": [],
        "latest_area": None,
        "historical_area": None,
    })
    with pytest.raises(ValueError, match="changed during validation"):
        peri_scribe.presentation.prepared_cache.read_history(payload)


def test_description_bytes_round_trip_preserves_time_and_original_units() -> None:
    time = pd.Timestamp("2026-09-01T00:00:00.123456789Z")
    assert isinstance(time, pd.Timestamp)
    description = peri_scribe.presentation.descriptions.FireDescription(
        area=123.45678901234567 * units.Unit("meters ** 2"),
        exterior_perimeter=42.123456789012345 * units.meters,
        estimated_cost_to_date=123.0 * units.dollars,
        observation_time=time,
    )
    restored = peri_scribe.presentation.prepared_cache.read_description(
        peri_scribe.presentation.prepared_cache.description_bytes(description),
    )
    assert restored == description


def test_read_description_rejects_missing_fields_in_a_partial_record() -> None:
    payload = spatial_data.cache_values.dumps({})
    with pytest.raises(ValueError, match="changed during validation"):
        peri_scribe.presentation.prepared_cache.read_description(payload)


@pytest.mark.parametrize("value", [[], {"unexpected": 1}])
def test_read_history_rejects_invalid_domain_records(value: object) -> None:
    with pytest.raises(ValueError, match="validation error"):
        peri_scribe.presentation.prepared_cache.read_history(
            spatial_data.cache_values.dumps(value),
        )
