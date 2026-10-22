"""Concrete immutable string sharing agrees with the proved pure memo oracle."""

import itertools

import pytest

import peri_scribe.geo.attribute_strings
import tests.formal.helpers.oracle


@pytest.mark.parametrize("capacity", [0, 1, 2, 8])
def test_attribute_strings_share_matches_checked_identity_memo(
    monkeypatch: pytest.MonkeyPatch,
    capacity: int,
) -> None:
    monkeypatch.setattr(
        peri_scribe.geo.attribute_strings,
        "MAXIMUM_STRING_COUNT",
        capacity,
    )
    values = ("name with spaces", "火🔥\n\0", "name with spaces")
    tokens = {value: index for index, value in enumerate(dict.fromkeys(values))}
    table = [tokens[value] for value in values]
    histories = [
        history
        for length in range(5)
        for history in itertools.product(range(len(values)), repeat=length)
    ]
    expected = tests.formal.helpers.oracle.evaluate(
        [
            " ".join(["source-path", *map(str, table), "--", *map(str, history)])
            for history in histories
        ],
        executable="oraclePresentationFlow",
    )
    for history, checked in zip(histories, expected, strict=True):
        pool = peri_scribe.geo.attribute_strings.AttributeStrings()
        actual = tuple(tokens[pool.share(values[index])] for index in history)
        assert actual == checked
        assert len(pool.values) <= capacity
