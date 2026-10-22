"""Attribute sharing preserves values and independent mutable containers."""

import json
import sys

import pytest

import peri_scribe.geo.attribute_strings
import spatial_data.cache_values


@pytest.mark.parametrize(
    "encoded",
    [
        "{}",
        '{"same": "first", "same": "last", "other": "last"}',
        '{"nested": [["fire", {"fire": ["fire"]}]], "fire": "fire"}',
        '{"火🔥": "火🔥", "zero": -0.0, "integer": 0, "boolean": false}',
        '{"escaped": "\\u0000\\n", "null": null, "large": 10000000000000000}',
        '{"not_finite": NaN, "positive": Infinity, "negative": -Infinity}',
    ],
)
def test_attribute_strings_mapping_preserves_exact_decoded_values(encoded: str) -> None:
    pool = peri_scribe.geo.attribute_strings.AttributeStrings()
    actual = json.loads(encoded, object_pairs_hook=pool.mapping)
    expected = json.loads(encoded)
    assert spatial_data.cache_values.dumps(actual) == spatial_data.cache_values.dumps(
        expected,
    )


def test_attribute_strings_share_reuses_equal_native_strings() -> None:
    pool = peri_scribe.geo.attribute_strings.AttributeStrings()
    value = "a separate source name"
    first = value.encode().decode()
    second = value.encode().decode()
    assert first is not second
    assert pool.share(first) is first
    assert pool.share(second) is first


def test_attribute_strings_share_preserves_misses_after_capacity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(peri_scribe.geo.attribute_strings, "MAXIMUM_STRING_COUNT", 1)
    pool = peri_scribe.geo.attribute_strings.AttributeStrings()
    first = "retained name"
    assert pool.share(first) is first
    assert pool.share("another name") == "another name"
    assert len(pool.values) == 1
    assert pool.share(first.encode().decode()) is first


def test_attribute_strings_share_does_not_retain_long_values() -> None:
    pool = peri_scribe.geo.attribute_strings.AttributeStrings()
    value = "x" * (peri_scribe.geo.attribute_strings.MAXIMUM_STRING_LENGTH + 1)
    assert pool.share(value) is value
    assert not pool.values


def test_attribute_strings_mapping_keeps_mutable_containers_independent() -> None:
    pool = peri_scribe.geo.attribute_strings.AttributeStrings()
    encoded = '{"key": [{"nested": ["a repeated source value"]}]}'
    first = json.loads(encoded, object_pairs_hook=pool.mapping)
    second = json.loads(encoded, object_pairs_hook=pool.mapping)
    assert first["key"][0]["nested"][0] is second["key"][0]["nested"][0]
    first["key"][0]["nested"].append("changed")
    first["key"][0]["another"] = "changed"
    assert second == json.loads(encoded)


def test_attribute_strings_share_is_scoped_to_one_owner() -> None:
    first = peri_scribe.geo.attribute_strings.AttributeStrings()
    second = peri_scribe.geo.attribute_strings.AttributeStrings()
    assert first.share("a source value") == "a source value"
    assert not second.values


def test_attribute_strings_mapping_retains_standard_decoder_nesting_limit() -> None:
    pool = peri_scribe.geo.attribute_strings.AttributeStrings()
    for depth in range(sys.getrecursionlimit(), 0, -1):
        encoded = '{"deep":' + "[" * depth + '"same"' + "]" * depth + "}"
        try:
            json.loads(encoded)
        except RecursionError:
            continue
        actual = json.loads(encoded, object_pairs_hook=pool.mapping)["deep"]
        for _position in range(depth):
            actual = actual[0]
        assert actual == "same"
        break
    else:
        pytest.fail("The standard JSON decoder accepted no nested document")
