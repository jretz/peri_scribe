"""Prepared evidence retains its established typed-cache representation."""

from __future__ import annotations

import dataclasses
import datetime
import hashlib

import hypothesis
import hypothesis.strategies

import peri_scribe.execution
import peri_scribe.incidents
import peri_scribe.presentation.descriptions
import peri_scribe.presentation.prepared_cache
import spatial_data.cache_values
import tests.helpers.factories.peri_scribe.presentation.prepared_cache
from measurement_units import units


@hypothesis.given(
    time=hypothesis.strategies.datetimes(
        timezones=hypothesis.strategies.just(datetime.UTC),
    ),
    magnitude=hypothesis.strategies.one_of(
        hypothesis.strategies.none(),
        hypothesis.strategies.floats(),
    ),
    unit=hypothesis.strategies.sampled_from(("acre", "meter ** 2", "hectare")),
    measurements=hypothesis.strategies.dictionaries(
        hypothesis.strategies.sampled_from(peri_scribe.incidents.VALUE_COLUMNS),
        hypothesis.strategies.floats(),
    ),
)
def test_history_bytes_matches_reference_for_original_units_and_optional_evidence(
    time: datetime.datetime,
    magnitude: float | None,
    unit: str,
    measurements: dict[str, float],
) -> None:
    history = tests.helpers.factories.peri_scribe.presentation.prepared_cache.history(
        time=time,
        area=None if magnitude is None else units.Quantity(magnitude, unit),
        measurements=measurements,
    )
    reference = spatial_data.cache_values.dumps(dataclasses.asdict(history))

    assert peri_scribe.presentation.prepared_cache.history_bytes(history) == reference
    restored = peri_scribe.presentation.prepared_cache.read_history(reference)
    assert peri_scribe.presentation.prepared_cache.history_bytes(restored) == reference


@hypothesis.given(
    observation_time=hypothesis.strategies.one_of(
        hypothesis.strategies.none(),
        hypothesis.strategies.datetimes(
            timezones=hypothesis.strategies.just(datetime.UTC),
        ),
    ),
    percent_contained=hypothesis.strategies.one_of(
        hypothesis.strategies.none(),
        hypothesis.strategies.floats(),
    ),
    identifier=hypothesis.strategies.one_of(
        hypothesis.strategies.none(),
        hypothesis.strategies.text(),
    ),
)
def test_description_bytes_matches_reference_for_missing_and_typed_facts(
    observation_time: datetime.datetime | None,
    percent_contained: float | None,
    identifier: str | None,
) -> None:
    description = peri_scribe.presentation.descriptions.FireDescription(
        observation_time=observation_time,
        percent_contained=percent_contained,
        identifier=identifier,
    )
    reference = spatial_data.cache_values.dumps(dataclasses.asdict(description))

    assert (
        peri_scribe.presentation.prepared_cache.description_bytes(
            description,
        )
        == reference
    )
    restored = peri_scribe.presentation.prepared_cache.read_description(reference)
    assert (
        peri_scribe.presentation.prepared_cache.description_bytes(
            restored,
        )
        == reference
    )


@hypothesis.given(
    original=hypothesis.strategies.floats(),
    replacement=hypothesis.strategies.floats(),
    unit=hypothesis.strategies.sampled_from(("acre", "meter ** 2", "hectare")),
    remember_identity=hypothesis.strategies.booleans(),
)
def test_history_digest_matches_complete_current_payload_after_nested_mutation(
    original: float,
    replacement: float,
    unit: str,
    *,
    remember_identity: bool,
) -> None:
    history = tests.helpers.factories.peri_scribe.presentation.prepared_cache.history(
        time=datetime.datetime(2026, 9, 1, tzinfo=datetime.UTC),
        area=units.Quantity(original, unit),
        measurements={"incident_size": original},
    )
    with peri_scribe.execution.sharing():
        history = peri_scribe.presentation.prepared_cache.read_history(
            peri_scribe.presentation.prepared_cache.history_bytes(history),
            remember_identity=remember_identity,
        )
        history.updates[0].measurements["incident_size"] = replacement
        current = peri_scribe.presentation.prepared_cache.history_digest(history)
        assert (
            current
            == hashlib.sha256(
                peri_scribe.presentation.prepared_cache.history_bytes(history),
            ).digest()
        )
