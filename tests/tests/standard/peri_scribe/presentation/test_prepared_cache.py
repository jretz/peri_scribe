"""Persistent fire facts retain original measurement and timestamp representations."""

from __future__ import annotations

import dataclasses
import hashlib
import struct
import unittest.mock

import pandas as pd
import pytest

import peri_scribe.areas
import peri_scribe.execution
import peri_scribe.incidents
import peri_scribe.presentation.descriptions
import peri_scribe.presentation.prepared_cache
import spatial_data.cache_values
import tests.helpers.doubles.peri_scribe.presentation.prepared_cache
import tests.helpers.factories.peri_scribe.presentation.descriptions
import tests.helpers.factories.peri_scribe.presentation.prepared_cache
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


@pytest.mark.parametrize("remember_identity", [True, False])
def test_read_history_rejects_coerced_measurement_fields(
    *,
    remember_identity: bool,
) -> None:
    payload = spatial_data.cache_values.dumps({
        "updates": (),
        "estimates": [],
        "latest_area": None,
        "historical_area": None,
    })
    with pytest.raises(ValueError, match="changed during validation"):
        peri_scribe.presentation.prepared_cache.read_history(
            payload,
            remember_identity=remember_identity,
        )


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
@pytest.mark.parametrize("remember_identity", [True, False])
def test_read_history_rejects_invalid_domain_records(
    value: object,
    *,
    remember_identity: bool,
) -> None:
    with pytest.raises(ValueError, match="validation error"):
        peri_scribe.presentation.prepared_cache.read_history(
            spatial_data.cache_values.dumps(value),
            remember_identity=remember_identity,
        )


@pytest.mark.parametrize(
    "magnitude",
    [
        -0.0,
        1234.5678901234567,
        float("inf"),
        struct.unpack("!d", bytes.fromhex("7ff8000000000007"))[0],
    ],
)
def test_history_bytes_preserves_reference_bytes_without_changing_evidence(
    magnitude: float,
) -> None:
    time = pd.Timestamp("2026-09-01T00:00:00.123456789Z")
    assert isinstance(time, pd.Timestamp)
    history = tests.helpers.factories.peri_scribe.presentation.prepared_cache.history(
        time=time,
        area=magnitude * units.Unit("meters ** 2"),
        measurements={"percent_contained": -0.0, "incident_size": magnitude},
    )
    reference = spatial_data.cache_values.dumps(dataclasses.asdict(history))

    assert peri_scribe.presentation.prepared_cache.history_bytes(history) == reference
    assert spatial_data.cache_values.dumps(dataclasses.asdict(history)) == reference


def test_description_bytes_preserves_every_populated_field_in_reference_order() -> None:
    description = (
        tests.helpers.factories.peri_scribe.presentation.descriptions.full_description()
    )
    assert peri_scribe.presentation.prepared_cache.description_bytes(
        description,
    ) == spatial_data.cache_values.dumps(dataclasses.asdict(description))


def test_history_bytes_preserves_subclass_and_nested_dataclass_fields() -> None:
    history = tests.helpers.factories.peri_scribe.presentation.prepared_cache.extended()
    assert peri_scribe.presentation.prepared_cache.history_bytes(
        history,
    ) == spatial_data.cache_values.dumps(dataclasses.asdict(history))


def test_record_field_names_rejects_types_without_dataclass_fields() -> None:
    with pytest.raises(TypeError, match="requires dataclass fields"):
        peri_scribe.presentation.prepared_cache.record_field_names(dict)


def test_record_values_does_not_treat_dataclass_types_as_instances() -> None:
    value = peri_scribe.areas.PreparedHistory
    with pytest.raises(ValueError, match="Unsupported cache value"):
        spatial_data.cache_values.dumps(
            peri_scribe.presentation.prepared_cache.record_values(value),
        )


def test_history_digest_reuses_validated_payload_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    time = pd.Timestamp("2026-09-01T00:00:00.123456789Z")
    assert isinstance(time, pd.Timestamp)
    original = tests.helpers.factories.peri_scribe.presentation.prepared_cache.history(
        time=time,
        area=42.0 * units.acres,
        measurements={"incident_size": 42.0},
    )
    payload = peri_scribe.presentation.prepared_cache.history_bytes(original)
    with peri_scribe.execution.sharing():
        history = peri_scribe.presentation.prepared_cache.read_history(payload)
        monkeypatch.setattr(
            peri_scribe.presentation.prepared_cache,
            "history_bytes",
            tests.helpers.doubles.peri_scribe.presentation.prepared_cache.reject_serialization,
        )
        assert (
            peri_scribe.presentation.prepared_cache.history_digest(
                history,
            )
            == hashlib.sha256(payload).digest()
        )


def test_read_history_can_defer_guards_until_current_evidence_is_used() -> None:
    time = pd.Timestamp("2026-09-01T00:00:00Z")
    assert isinstance(time, pd.Timestamp)
    original = tests.helpers.factories.peri_scribe.presentation.prepared_cache.history(
        time=time,
        area=24.0 * units.acres,
        measurements={"incident_size": 24.0},
    )
    payload = peri_scribe.presentation.prepared_cache.history_bytes(original)
    with peri_scribe.execution.sharing():
        history = peri_scribe.presentation.prepared_cache.read_history(
            payload,
            remember_identity=False,
        )
        key = ("prepared_history_identity", id(history))
        assert (
            peri_scribe.execution.get(peri_scribe.execution.Group.HISTORIES, key)
            is None
        )
        assert history == original
        history.updates[0].measurements["incident_size"] = 30.0
        current = peri_scribe.presentation.prepared_cache.history_digest(history)
        assert (
            current
            == hashlib.sha256(
                peri_scribe.presentation.prepared_cache.history_bytes(history),
            ).digest()
        )
        assert current != hashlib.sha256(payload).digest()
        assert isinstance(
            peri_scribe.execution.get(peri_scribe.execution.Group.HISTORIES, key),
            peri_scribe.presentation.prepared_cache.HistoryIdentity,
        )


def test_history_digest_batches_foreign_children_in_one_encoding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    time = pd.Timestamp("2026-09-01T00:00:00Z")
    assert isinstance(time, pd.Timestamp)
    original = tests.helpers.factories.peri_scribe.presentation.prepared_cache.history(
        time=time,
        area=42.0 * units.acres,
        measurements={"incident_size": 42.0},
    )
    payload = peri_scribe.presentation.prepared_cache.history_bytes(original)
    with peri_scribe.execution.sharing():
        history = peri_scribe.presentation.prepared_cache.read_history(payload)
        encode = unittest.mock.Mock(wraps=spatial_data.cache_values.dumps)
        monkeypatch.setattr(spatial_data.cache_values, "dumps", encode)
        assert (
            peri_scribe.presentation.prepared_cache.history_digest(history)
            == hashlib.sha256(payload).digest()
        )
        assert encode.call_count == 1


@pytest.mark.parametrize(
    "change",
    ["measurement", "type", "signed_zero", "order", "units", "record"],
)
def test_history_digest_rejects_mutated_retained_evidence(change: str) -> None:
    time = pd.Timestamp("2026-09-01T00:00:00.123456789Z")
    assert isinstance(time, pd.Timestamp)
    original = tests.helpers.factories.peri_scribe.presentation.prepared_cache.history(
        time=time,
        area=42.0 * units.acres,
        measurements={"incident_size": 42.0, "percent_contained": -0.0},
    )
    with peri_scribe.execution.sharing():
        history = peri_scribe.presentation.prepared_cache.read_history(
            peri_scribe.presentation.prepared_cache.history_bytes(original),
        )
        previous = peri_scribe.presentation.prepared_cache.history_digest(history)
        match change:
            case "measurement":
                history.updates[0].measurements["incident_size"] = 43.0
            case "type":
                history.updates[0].measurements["incident_size"] = 42
            case "signed_zero":
                history.updates[0].measurements["percent_contained"] = 0.0
            case "order":
                value = history.updates[0].measurements.pop("incident_size")
                history.updates[0].measurements["incident_size"] = value
            case "units":
                assert history.latest_area is not None
                history.latest_area.ito("meters ** 2")
            case _:
                vars(history)["updates"] = ()
        payload = peri_scribe.presentation.prepared_cache.history_bytes(history)
        current = peri_scribe.presentation.prepared_cache.history_digest(history)
        assert current == hashlib.sha256(payload).digest()
        assert current != previous


def test_history_digest_covers_nested_subclass_evidence() -> None:
    history = tests.helpers.factories.peri_scribe.presentation.prepared_cache.extended()
    with peri_scribe.execution.sharing():
        previous = peri_scribe.presentation.prepared_cache.history_digest(history)
        evidence = vars(history.evidence)["values"]
        assert isinstance(evidence, dict)
        evidence["second", 2].append("changed")
        payload = peri_scribe.presentation.prepared_cache.history_bytes(history)
        current = peri_scribe.presentation.prepared_cache.history_digest(history)
        assert current == hashlib.sha256(payload).digest()
        assert current != previous


def test_history_digest_has_no_identity_authority_between_execution_scopes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    history = peri_scribe.areas.PreparedHistory(
        updates=(),
        estimates=(),
        latest_area=None,
        historical_area=None,
    )
    with peri_scribe.execution.sharing():
        peri_scribe.presentation.prepared_cache.history_digest(history)
    monkeypatch.setattr(
        peri_scribe.presentation.prepared_cache,
        "history_bytes",
        tests.helpers.doubles.peri_scribe.presentation.prepared_cache.reject_serialization,
    )
    with (
        peri_scribe.execution.sharing(),
        pytest.raises(ValueError, match="Unsupported cache value"),
    ):
        peri_scribe.presentation.prepared_cache.history_digest(history)


def test_history_payload_reuses_guarded_immutable_bytes() -> None:
    history = peri_scribe.areas.PreparedHistory(
        updates=(),
        estimates=(),
        latest_area=25.0 * units.acres,
        historical_area=25.0 * units.acres,
    )
    payload = peri_scribe.presentation.prepared_cache.history_bytes(history)
    with peri_scribe.execution.sharing():
        peri_scribe.presentation.prepared_cache.remember_history(history, payload)
        assert (
            peri_scribe.presentation.prepared_cache.history_payload(history) is payload
        )


def test_history_payload_rebuilds_after_mutable_measurement_changes() -> None:
    area = 25.0 * units.acres
    history = peri_scribe.areas.PreparedHistory(
        updates=(),
        estimates=(),
        latest_area=area,
        historical_area=area,
    )
    payload = peri_scribe.presentation.prepared_cache.history_bytes(history)
    with peri_scribe.execution.sharing():
        peri_scribe.presentation.prepared_cache.remember_history(history, payload)
        area.ito("meter ** 2")
        current = peri_scribe.presentation.prepared_cache.history_payload(history)
        assert current != payload
        assert current == peri_scribe.presentation.prepared_cache.history_bytes(history)
