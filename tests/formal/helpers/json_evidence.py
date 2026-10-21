"""Compare source JSON evidence with the proved immutable-scalar equality rule."""

from __future__ import annotations

import copy
import itertools
import struct
import typing

import peri_scribe.geo.fingerprints
import tests.formal.helpers.oracle


COMPARISON_COUNT = 11_552


def cases() -> list[object]:
    """Compose exact scalar distinctions into complete ordered and mapping examples.

    Returns:
        Native scalar values and detached nested trees, including signed zero and NaNs.
    """
    scalars: list[object] = [
        None,
        False,
        True,
        -(10**40),
        -1,
        0,
        1,
        10**40,
        "",
        "source",
        "火🔥\x00",
        0.0,
        -0.0,
        1.0,
        float("inf"),
        float("-inf"),
        struct.unpack("!d", bytes.fromhex("7ff8000000000001"))[0],
        struct.unpack("!d", bytes.fromhex("fff8000000000002"))[0],
    ]
    result = list(scalars)
    for value in scalars:
        result.extend(([value], {"value": value}, {"nested": [{"value": value}]}))
    result.extend(([], {}, {"a": 1, "b": [None]}, {"b": [None], "a": 1}))
    return result


def tokens(value: object) -> list[str]:
    """Expose exact scalar tags and canonical dictionary contents to the proved codec.

    Args:
        value: One finite native JSON tree from the declared input catalogue.

    Returns:
        Prefix tokens for CacheCodec.Value without production equality decisions.

    Raises:
        TypeError: If a value is outside the native JSON conformance catalogue.
    """
    kind = type(value)
    if kind is list:
        items = typing.cast("list[object]", value)
        return [token for item in items for token in ("2 6", *tokens(item))] + ["1 6"]
    if kind is dict:
        mapping = typing.cast("dict[str, object]", value)
        items = [field for key in sorted(mapping) for field in (key, mapping[key])]
        return [token for item in items for token in ("2 5", *tokens(item))] + ["1 5"]
    tags: dict[type, int] = {type(None): 0, bool: 1, int: 2, float: 3, str: 4}
    if kind not in tags:
        message = "JSON evidence conformance requires native scalar and container types"
        raise TypeError(message)
    payload = (
        value.hex()
        if isinstance(value, float)
        else typing.cast("str", value)
        if kind is str
        else str(value)
    )
    return [
        " ".join(map(str, (0, tags[kind], *payload.encode("utf-8", "surrogatepass")))),
    ]


def compare() -> int:
    """Evaluate real unchanged, detached and differently typed values through Lean.

    Returns:
        The number of independent complete JSON comparisons checked.
    """
    values = cases()
    pairs = list(itertools.product(values, repeat=2))
    expected = tests.formal.helpers.oracle.evaluate(
        [
            "json-equal|" + ";".join(tokens(left)) + "|" + ";".join(tokens(right))
            for left, right in pairs
        ],
        executable="oracleCodec",
    )
    for (left, right), (same,) in zip(pairs, expected, strict=True):
        assert peri_scribe.geo.fingerprints.same_json_value(left, right) == bool(same)
        assert peri_scribe.geo.fingerprints.same_json_value(
            left,
            copy.deepcopy(right),
        ) == bool(same)
    return len(pairs) * 2
