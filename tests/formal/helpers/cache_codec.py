"""Compare stored typed values with independent representation fixtures and Lean."""

from __future__ import annotations

import dataclasses
import datetime
import itertools
import struct
import typing

import numpy as np
import pandas as pd
import pytest
import shapely

import peri_scribe.areas
import spatial_data.cache_values
import tests.formal.helpers.oracle
from measurement_units import units


@dataclasses.dataclass(frozen=True, kw_only=True)
class Case:
    """Keep a value and its declared storage representation independently specified."""

    value: object
    representation: list[object]


def scalar_cases() -> tuple[Case, ...]:
    """Exercise distinctions that JSON's untagged scalar grammar would erase.

    Returns:
        Explicit scalar contracts, including exact binary floating-point payloads.
    """
    cases = [
        Case(value=None, representation=["none"]),
        Case(value=pd.NA, representation=["missing"]),
        Case(value=pd.NaT, representation=["not_a_time"]),
        Case(value=False, representation=["bool", False]),
        Case(value=True, representation=["bool", True]),
        Case(value=0, representation=["int", "0"]),
        Case(value=1, representation=["int", "1"]),
        Case(value=-(10**40), representation=["int", "-" + "1" + "0" * 40]),
        Case(value="", representation=["str", ""]),
        Case(value="火🔥|;\n\x00", representation=["str", "火🔥|;\n\x00"]),
        Case(value=b"\x00\xff", representation=["bytes", "00ff"]),
        Case(
            value=datetime.datetime(2026, 9, 1, 2, 3, 4, 5, tzinfo=datetime.UTC),
            representation=["datetime", "2026-09-01T02:03:04.000005+00:00", 0],
        ),
        Case(
            value=datetime.datetime(2026, 9, 1, 2, 3, 4, 5, fold=1),
            representation=["datetime", "2026-09-01T02:03:04.000005", 1],
        ),
        Case(
            value=datetime.timedelta(days=-1, seconds=7, microseconds=3),
            representation=["timedelta", -1, 7, 3],
        ),
        Case(
            value=peri_scribe.areas.AreaSource.MAPPED,
            representation=[
                "enum",
                "peri_scribe.areas.AreaSource",
                ["str", peri_scribe.areas.AreaSource.MAPPED.value],
            ],
        ),
        Case(
            value=units.Quantity(1, "meter"),
            representation=["quantity", ["int", "1"], "meter"],
        ),
        Case(
            value=units.Quantity(100, "centimeter"),
            representation=["quantity", ["int", "100"], "centimeter"],
        ),
    ]
    cases.extend(
        Case(
            value=struct.unpack("!d", bytes.fromhex(bits))[0],
            representation=["float", bits],
        )
        for bits in (
            "0000000000000000",
            "8000000000000000",
            "3ff0000000000000",
            "3ff0000000000001",
            "7ff0000000000000",
            "fff0000000000000",
            "7ff8000000000001",
            "7ff8000000000002",
        )
    )
    for dtype in ("i1", "i2", "i4", "i8", "u1", "u2", "u4", "u8", "f4", "f8"):
        value = np.array([1], dtype=dtype)[0]
        cases.append(
            Case(
                value=value,
                representation=["numpy", value.dtype.str, value.tobytes().hex()],
            ),
        )
    cases.extend(
        Case(
            value=value,
            representation=["numpy", value.dtype.str, value.tobytes().hex()],
        )
        for value in (
            np.bool_(1),
            np.str_("a"),
            np.bytes_(b"a"),
            np.datetime64("2026-09-01", "ns"),
            np.timedelta64(1, "ns"),
        )
    )
    for unit in ("s", "ms", "us", "ns"):
        timestamp = pd.Timestamp("2026-09-01T02:03:04Z").as_unit(unit)
        cases.append(
            Case(
                value=timestamp,
                representation=["timestamp", "2026-09-01T02:03:04+00:00", 0, unit],
            ),
        )
    for nanoseconds in (1, 2):
        instant = f"2026-09-01T02:03:04.00000000{nanoseconds}+00:00"
        cases.append(
            Case(
                value=pd.Timestamp(instant),
                representation=["timestamp", instant, 0, "ns"],
            ),
        )
        duration = pd.Timedelta(nanoseconds, unit="ns")
        cases.append(
            Case(
                value=duration,
                representation=[
                    "pandas_timedelta",
                    ["numpy", "<m8[ns]", nanoseconds.to_bytes(8, "little").hex()],
                ],
            ),
        )
    for identifier in (0, 4326):
        geometry = shapely.set_srid(shapely.Point(1, 2), identifier)
        cases.append(
            Case(
                value=geometry,
                representation=[
                    "geometry",
                    shapely.to_wkb(geometry, include_srid=True).hex(),
                ],
            ),
        )
    return tuple(cases)


def cases() -> tuple[Case, ...]:
    """Compose declared scalar fixtures without using the production encoder.

    Returns:
        Nested, ordered, empty, and unordered container representations.
    """
    scalars = scalar_cases()
    result = list(scalars)
    for case in scalars:
        for constructor, tag in ((tuple, "tuple"), (list, "list")):
            result.append(
                Case(
                    value=constructor((case.value,)),
                    representation=[tag, [case.representation]],
                ),
            )
    for tag, value in (
        ("tuple", ()),
        ("list", []),
        ("dict", {}),
        ("frozenset", frozenset()),
    ):
        result.append(Case(value=value, representation=[tag, []]))
    for ordered in itertools.permutations(("a", "b", "c")):
        result.extend((
            Case(
                value={name: position for position, name in enumerate(ordered)},
                representation=[
                    "dict",
                    [
                        [["str", name], ["int", str(position)]]
                        for position, name in enumerate(ordered)
                    ],
                ],
            ),
            Case(
                value=frozenset(ordered),
                representation=[
                    "frozenset",
                    [["str", name] for name in ("a", "b", "c")],
                ],
            ),
        ))
    nested = Case(value=1, representation=["int", "1"])
    for depth in range(12):
        nested = Case(
            value=(nested.value, [None, depth]),
            representation=[
                "tuple",
                [nested.representation, ["list", [["none"], ["int", str(depth)]]]],
            ],
        )
        result.append(nested)
    return tuple(result)


def tokens(value: object) -> list[str]:
    """Lower parsed JSON into the proved ordered tree without interpreting cache tags.

    Args:
        value: An independently specified or actually stored JSON tree.

    Returns:
        Prefix tokens; scalar payloads are complete UTF-8 bytes.

    Raises:
        TypeError: If the value is outside the cache wire grammar.
    """
    if isinstance(value, list):
        return [token for item in value for token in ("2 0", *tokens(item))] + ["1 0"]
    if isinstance(value, (str, bool, int)):
        tag = 1 if isinstance(value, str) else 2 if isinstance(value, bool) else 3
        payload = value if isinstance(value, str) else str(value)
        return [" ".join(map(str, (0, tag, *payload.encode("utf-8"))))]
    message = f"Unsupported codec contract field: {type(value)}"
    raise TypeError(message)


def command(first: object, second: object) -> str:
    """Keep every field and ordering choice visible to the compiled reference.

    Args:
        first: The expected typed JSON representation.
        second: The actual representation being compared.

    Returns:
        One request to the checked prefix-tree codec.
    """
    return ";".join(tokens(first)) + "|" + ";".join(tokens(second))


def compare_round_trips() -> None:
    """Check actual writes and restored values against declared field-level evidence."""
    commands = []
    for case in cases():
        payload = spatial_data.cache_values.dumps(case.value)
        restored = spatial_data.cache_values.loads(
            payload,
            enums=(peri_scribe.areas.AreaSource,),
        )
        assert type(restored) is type(case.value)
        assert payload == canonical_payload(case.representation)
        commands.extend((
            command(case.representation, wire_representation(payload)),
            command(
                case.representation,
                wire_representation(spatial_data.cache_values.dumps(restored)),
            ),
        ))
    assert tests.formal.helpers.oracle.evaluate(commands, executable="oracleCodec") == [
        (1, 1, 1, 1),
    ] * len(commands)


def compare_distinctions() -> None:
    """Equal actual payloads must agree with the proved typed-tree equality relation."""
    fixtures = cases()
    representations = [case.representation for case in fixtures]
    payloads = [spatial_data.cache_values.dumps(case.value) for case in fixtures]
    pairs = list(itertools.combinations(range(len(fixtures)), 2))
    outcomes = tests.formal.helpers.oracle.evaluate(
        [
            command(representations[first], representations[second])
            for first, second in pairs
        ],
        executable="oracleCodec",
    )
    for (first, second), (valid_first, valid_second, same_value, same_wire) in zip(
        pairs,
        outcomes,
        strict=True,
    ):
        assert valid_first == valid_second == 1
        assert (
            (payloads[first] == payloads[second]) == bool(same_wire) == bool(same_value)
        )


def compare_framing() -> None:
    """Omitting a child or adding a trailing value cannot produce an accepted root."""
    requests = []
    for case in cases():
        payload = spatial_data.cache_values.dumps(case.value)
        for malformed_payload in (payload[:-1], payload + b"\0", payload[:5]):
            with pytest.raises(ValueError, match=r"[Cc]ache"):
                spatial_data.cache_values.loads(
                    malformed_payload,
                    enums=(peri_scribe.areas.AreaSource,),
                )
        encoded = tokens(case.representation)
        original = ";".join(encoded)
        requests.extend(
            original + "|" + ";".join(malformed)
            for malformed in (encoded[:-1], [*encoded, "1 0"])
        )
    assert tests.formal.helpers.oracle.evaluate(requests, executable="oracleCodec") == [
        (1, 0, 0, 0),
    ] * len(requests)


def canonical_payload(representation: typing.Sequence[object]) -> bytes:
    """Produce independent malformed fixtures without using a production encoder.

    Args:
        representation: The deliberately invalid typed wire value.

    Returns:
        Independently framed binary bytes suitable for the real decoder.
    """
    return b"PSCV\x02" + wire_node(representation)


WIRE_NAMES = (
    "none",
    "missing",
    "not_a_time",
    "bool",
    "int",
    "float",
    "str",
    "bytes",
    "tuple",
    "list",
    "frozenset",
    "dict",
    "enum",
    "quantity",
    "datetime",
    "timestamp",
    "timedelta",
    "pandas_timedelta",
    "numpy",
    "geometry",
)


def wire_node(representation: typing.Sequence[object]) -> bytes:
    """Frame independently declared semantic fixtures using the specified wire grammar.

    Args:
        representation: One tagged fixture, including deliberate malformed cases.

    Returns:
        Its binary node without the root version prefix.
    """
    kind = str(representation[0])
    fields = representation[1:]
    match kind, fields:
        case (("none" | "missing" | "not_a_time"), []):
            payload = b""
        case "bool", [value]:
            payload = bytes((int(value) if isinstance(value, bool) else 2,))
        case (("int" | "str"), [str(value)]):
            payload = value.encode()
        case (("float" | "bytes" | "geometry"), [str(value)]):
            payload = bytes.fromhex(value)
        case (("tuple" | "list" | "frozenset"), [list(children)]):
            nodes = [wire_node(child) for child in children]
            payload = b"".join(sorted(nodes) if kind == "frozenset" else nodes)
        case "dict", [list(children)]:
            payload = b"".join(wire_node(child) for pair in children for child in pair)
        case "numpy", [str(dtype), str(value)]:
            payload = wire_node(["str", dtype]) + wire_node(["bytes", value])
        case _:
            payload = b"".join(
                wire_node(
                    field
                    if isinstance(field, list)
                    else ["int", str(field)]
                    if isinstance(field, int)
                    else ["str", field],
                )
                for field in fields
            )
    return bytes((WIRE_NAMES.index(kind),)) + len(payload).to_bytes(4, "big") + payload


def wire_representation(payload: bytes) -> object:
    """Interpret real wire bytes independently of the application decoder.

    Args:
        payload: One production-encoded value.

    Returns:
        The semantic tagged tree consumed by the checked Lean oracle.
    """
    assert payload[:5] == b"PSCV\x02"
    representation, end = wire_tree(payload, 5)
    assert end == len(payload)
    return representation


def wire_tree(payload: bytes, offset: int) -> tuple[list[object], int]:
    """Lower framed bytes into the independent semantic fixture vocabulary.

    Args:
        payload: One complete parent payload.
        offset: The next child's start position.

    Returns:
        The semantic tree and the next unread position.
    """
    kind = WIRE_NAMES[payload[offset]]
    first = offset + 5
    end = first + int.from_bytes(payload[offset + 1 : first], "big")
    assert end <= len(payload)
    content = payload[first:end]
    if kind in {"none", "missing", "not_a_time"}:
        assert not content
        return [kind], end
    if kind in {"bool", "int", "str", "float", "bytes", "geometry"}:
        value = (
            bool(content[0])
            if kind == "bool"
            else content.decode()
            if kind in {"int", "str"}
            else content.hex()
        )
        return [kind, value], end
    children = []
    position = 0
    while position < len(content):
        child, position = wire_tree(content, position)
        children.append(child)
    if kind in {"tuple", "list", "frozenset"}:
        return [kind, children], end
    if kind == "dict":
        return [
            kind,
            [children[index : index + 2] for index in range(0, len(children), 2)],
        ], end
    if kind == "numpy":
        return [kind, children[0][1], children[1][1]], end
    fields = [
        child
        if child[0] not in {"str", "int"}
        else int(str(child[1]))
        if child[0] == "int"
        else child[1]
        for child in children
    ]
    # Enum values and quantity magnitudes retain their own scalar tags.
    if kind == "enum":
        fields[1] = children[1]
    if kind == "quantity":
        fields[0] = children[0]
    return [kind, *fields], end
