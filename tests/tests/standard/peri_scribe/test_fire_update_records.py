"""Reject malformed journal payloads and ambiguous serialized identity keys."""

import json

import pydantic
import pytest

import peri_scribe.fire_update_records
import tests.helpers.factories.peri_scribe.durable_updates


@pytest.mark.parametrize("kind", ["id", "name", "local", "component"])
@pytest.mark.parametrize("value", ["", "Fire", 'é"\\n'])
def test_canonical_identity_preserves_every_supported_kind(
    kind: str,
    value: str,
) -> None:
    encoded = json.dumps((kind, value))

    assert peri_scribe.fire_update_records.canonical_identity(encoded) == encoded


@pytest.mark.parametrize(
    "encoded",
    [
        "{",
        "null",
        '"id"',
        "[]",
        '["id", "a", "b"]',
        '["bad", "a"]',
        '["id", 2]',
        '["id",null]',
        '["id","a"]',
        '[ "id", "a" ]',
        '["id", "é"]',
    ],
)
def test_canonical_identity_rejects_ambiguous_or_invalid_encodings(
    encoded: str,
) -> None:
    with pytest.raises(ValueError, match=r"validation error|canonical JSON encoding"):
        peri_scribe.fire_update_records.canonical_identity(encoded)


@pytest.mark.parametrize(
    "override",
    [
        {"mapped_area": {"value": -1, "units": "acre"}},
        {"mapped_area": {"value": float("nan"), "units": "acre"}},
        {"mapped_area": {"value": float("inf"), "units": "acre"}},
        {"mapped_area": {"value": 1, "units": "meter"}},
        {"mapped_area": {"value": 1, "extra": True}},
        {"log_identity": ["bad", "a"]},
        {"log_identity": ["id", 3]},
        {"identifier": []},
        {"unexpected": "retained"},
    ],
)
def test_validated_records_rejects_incomplete_or_unreadable_batch(
    override: dict[str, object],
) -> None:
    valid = tests.helpers.factories.peri_scribe.durable_updates.record()

    with pytest.raises(pydantic.ValidationError):
        peri_scribe.fire_update_records.validated_records((valid, valid | override))


def test_validated_records_preserves_legacy_payloads_and_order() -> None:
    first = tests.helpers.factories.peri_scribe.durable_updates.record()
    second = first | {"name": "Renamed", "mapped_area": {"value": 50, "units": "acre"}}
    second.pop("log_identity")

    actual = peri_scribe.fire_update_records.validated_records((first, second))

    assert actual == (first, second)
