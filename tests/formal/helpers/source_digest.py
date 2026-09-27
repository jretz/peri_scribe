"""Source identity fixtures retain independent normalized values and Lean framing."""

from __future__ import annotations

import dataclasses
import datetime
import hashlib
import itertools
import typing

import geopandas
import pandas as pd
import shapely

import tests.formal.helpers.oracle


@dataclasses.dataclass(frozen=True, kw_only=True)
class Scalar:
    """Declare storage normalization without calling the production normalizer."""

    value: object
    fragment: bytes


@dataclasses.dataclass(frozen=True, kw_only=True)
class Frame:
    """Keep a concrete dataframe beside its independently declared semantic fields."""

    value: geopandas.GeoDataFrame
    schema: tuple[bytes, ...]
    rows: tuple[tuple[bytes, ...], ...]


def scalars() -> tuple[Scalar, ...]:
    """Exercise scalar tags and intentionally equivalent missing representations.

    Returns:
        Explicit attribute normalization contracts.
    """
    return (
        *(Scalar(value=value, fragment=b"m") for value in (None, pd.NA, pd.NaT)),
        Scalar(value=float("nan"), fragment=b"m"),
        Scalar(value=False, fragment=b"f"),
        Scalar(value=True, fragment=b"t"),
        Scalar(value=1, fragment=b"n1"),
        Scalar(value=1.0, fragment=b"n1.0"),
        Scalar(value=-1, fragment=b"n-1"),
        Scalar(value=0.0, fragment=b"n0.0"),
        Scalar(value=-0.0, fragment=b"n-0.0"),
        Scalar(value=float("inf"), fragment=b"ninf"),
        Scalar(value=b"\x00s\xff", fragment=b"x\x00s\xff"),
        Scalar(value=datetime.date(2026, 9, 26), fragment=b"d2026-09-26"),
        Scalar(value=datetime.time(1, 2, 3), fragment=b"d01:02:03"),
        Scalar(
            value=datetime.datetime(2026, 9, 26, tzinfo=datetime.UTC),
            fragment=b"d2026-09-26T00:00:00+00:00",
        ),
        *(
            Scalar(value=value, fragment=b"s" + value.encode())
            for value in ("", "a", "as", "b", "sb", "\x00", "\x00\x01", "火🔥")
        ),
    )


def frame(
    names: tuple[str, ...],
    rows: tuple[tuple[Scalar, ...], ...],
    *,
    reference: int | None = 4326,
) -> Frame:
    """Keep schema and payload order explicit while preserving pandas scalar types.

    Args:
        names: Attribute names, which source comparison orders by name.
        rows: Complete attributes for each point observation.
        reference: Optional EPSG coordinate reference identifier.

    Returns:
        A source frame and the declared structured inputs to its fingerprint.
    """
    ordered = sorted(range(len(names)), key=names.__getitem__)
    geometry = shapely.Point(0, 0)
    dataframe = geopandas.GeoDataFrame(
        {
            name: pd.Series([row[index].value for row in rows], dtype=object)
            for index, name in enumerate(names)
        },
        geometry=[geometry] * len(rows),
        crs=None if reference is None else f"EPSG:{reference}",
    )
    return Frame(
        value=dataframe,
        schema=(
            b"m" if reference is None else f"c('EPSG', '{reference}')".encode(),
            *(b"s" + names[index].encode() for index in ordered),
        ),
        rows=tuple(
            (*(row[index].fragment for index in ordered), b"g" + geometry.wkb)
            for row in rows
        ),
    )


def cases() -> tuple[Frame, ...]:
    """Exercise schema, boundaries, normalization, multiplicity, and row permutations.

    Returns:
        Concrete frames with an independent structured identity.
    """
    values = scalars()
    result = [frame(("value",), ((value,),)) for value in values]
    strings = tuple(value for value in values if isinstance(value.value, str))
    result.extend(
        frame(("first", "second"), ((first, second),))
        for first, second in itertools.product(strings, repeat=2)
    )
    result.extend(
        frame(names, (), reference=reference)
        for names in ((), ("first",), ("renamed",), ("first", "second"))
        for reference in (None, 4326, 3857)
    )
    result.extend(
        frame(("value",), ((strings[1],),), reference=reference)
        for reference in (None, 4326, 3857)
    )
    rows = ((strings[0],), (strings[1],), (strings[2],))
    result.extend(
        frame(("value",), permutation) for permutation in itertools.permutations(rows)
    )
    result.extend(frame(("value",), rows * count) for count in range(3))
    result.extend((
        frame(("second", "first"), ((strings[1], strings[2]),)),
        frame(("first", "second"), ((strings[2], strings[1]),)),
    ))
    return tuple(result)


def numbers(values: typing.Iterable[int]) -> str:
    """Keep oracle transport independent of source values and delimiter content.

    Args:
        values: Exact natural-number tokens.

    Returns:
        Space-separated decimal transport values.
    """
    return " ".join(map(str, values))


def encode(parts: typing.Sequence[tuple[bytes, ...]]) -> list[bytes]:
    """Evaluate the actual prefix-free definition used by the Lean proofs.

    Args:
        parts: Ordered fields; empty fields and empty field lists stay distinct.

    Returns:
        The executable specification's exact framed bytes.
    """
    commands = [
        "|".join(("fields", *(numbers(part) for part in fields))) for fields in parts
    ]
    return [
        bytes(result)
        for result in tests.formal.helpers.oracle.evaluate(
            commands,
            executable="oracleSourceDigest",
        )
    ]


def expected_fingerprints(fixtures: tuple[Frame, ...]) -> list[str]:
    """Let proved framing and canonical ordering supply the real SHA-256 preimages.

    Args:
        fixtures: Independently declared semantic fields for concrete frames.

    Returns:
        Expected production fingerprints; cryptographic hashing remains trusted.
    """
    schemas = [
        hashlib.sha256(value).digest()
        for value in encode([case.schema for case in fixtures])
    ]
    flat_rows = [row for case in fixtures for row in case.rows]
    row_hashes = iter(hashlib.sha256(value).digest() for value in encode(flat_rows))
    rows = [tuple(next(row_hashes) for _ in case.rows) for case in fixtures]
    sorted_rows = tests.formal.helpers.oracle.evaluate(
        ["rows|" + numbers(int.from_bytes(row) for row in case) for case in rows],
        executable="oracleSourceDigest",
    )
    structured = [
        (schema, *(row.to_bytes(32) for row in ordered))
        for schema, ordered in zip(schemas, sorted_rows, strict=True)
    ]
    return [hashlib.sha256(value).hexdigest() for value in encode(structured)]


def framing_cases() -> list[tuple[bytes, ...]]:
    """Include arbitrary delimiter bytes and changes to field partition boundaries.

    Returns:
        Exhaustive short strings plus wider raw byte fields.
    """
    values = [
        bytes(value)
        for size in range(4)
        for value in itertools.product((0, 1, 115), repeat=size)
    ]
    return [
        (),
        *((value,) for value in values),
        *itertools.product(values, repeat=2),
        *((bytes([value]), b"\x00", bytes([value, 0, 1])) for value in range(256)),
        (bytes(range(256)), b"\x00\x00", bytes(reversed(range(256)))),
    ]


def equivalences(fixtures: tuple[Frame, ...]) -> list[tuple[int, int, bool]]:
    """Compare source semantics before hashing, including exact row multiplicities.

    Args:
        fixtures: Source frames with independent normalized field declarations.

    Returns:
        Every frame pair and the proved schema-and-row-bag equivalence decision.
    """
    schemas = encode([case.schema for case in fixtures])
    encoded_rows = iter(encode([row for case in fixtures for row in case.rows]))
    rows = [
        [int.from_bytes(b"\x01" + next(encoded_rows)) for _ in case.rows]
        for case in fixtures
    ]
    pairs = list(itertools.combinations(range(len(fixtures)), 2))
    results = tests.formal.helpers.oracle.evaluate(
        [
            "|".join((
                "equal",
                numbers(schemas[first]),
                numbers(rows[first]),
                numbers(schemas[second]),
                numbers(rows[second]),
            ))
            for first, second in pairs
        ],
        executable="oracleSourceDigest",
    )
    return [
        (first, second, bool(result[0]))
        for (first, second), result in zip(pairs, results, strict=True)
    ]
