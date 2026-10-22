"""Preserve exact typed cache values in a compact, non-executable binary format.

[Representation contract](../../docs/algorithms/prepared-product-representations.md)
explains framing, canonical validation, and the checked typed-tree correspondence.
"""

from __future__ import annotations

import datetime
import enum
import functools
import struct
import typing

import numpy as np
import pandas as pd
import pint
import shapely

from measurement_units import units


MAGIC = b"PSCV\x02"
HEADER = struct.Struct("!BI")
TAGS = {
    "none": 0,
    "missing": 1,
    "not_a_time": 2,
    "bool": 3,
    "int": 4,
    "float": 5,
    "str": 6,
    "bytes": 7,
    "tuple": 8,
    "list": 9,
    "frozenset": 10,
    "dict": 11,
    "enum": 12,
    "quantity": 13,
    "datetime": 14,
    "timestamp": 15,
    "timedelta": 16,
    "pandas_timedelta": 17,
    "numpy": 18,
    "geometry": 19,
}


def dumps(value: object) -> bytes:
    """Write exact scalar bytes and ordered children without an intermediate tree.

    Args:
        value: Supported scalar values and finite, acyclic containers.

    Returns:
        One versioned, canonically framed value.
    """
    output = bytearray(MAGIC)
    write(value, output)
    return bytes(output)


def append_scalar(kind: str, payload: bytes, output: bytearray) -> None:
    """Frame a scalar so neighboring values cannot change its interpretation.

    Args:
        kind: Its declared wire type.
        payload: Exact scalar contents.
        output: The current complete value's byte buffer.
    """
    output.extend(HEADER.pack(TAGS[kind], len(payload)))
    output.extend(payload)


def append_children(
    kind: str,
    children: typing.Iterable[object],
    output: bytearray,
) -> None:
    """Write children directly and close their enclosing byte boundary afterward.

    Args:
        kind: The container or composite scalar type.
        children: Children in semantic order.
        output: The current complete value's byte buffer.
    """
    start = len(output)
    output.extend(b"\0" * HEADER.size)
    for child in children:
        write(child, output)
    HEADER.pack_into(output, start, TAGS[kind], len(output) - start - HEADER.size)


NATIVE_TYPES = frozenset({bool, int, float, str, bytes, tuple, list, frozenset, dict})


def write(value: object, output: bytearray) -> None:
    """Dispatch exact native types without probing every domain scalar family.

    The metaclass check keeps custom hashing and equality out of the type lookup.
    Subclasses still follow domain-first dispatch, preserving enums and NumPy scalars.

    Args:
        value: One supported scalar or container.
        output: The destination byte buffer.
    """
    kind = type(value)
    if type(kind) is type and kind in NATIVE_TYPES:
        write_builtin(value, output)
    else:
        write_special(value, output)


def write_special(value: object, output: bytearray) -> None:
    """Emit one value while preserving domain scalar types before their base classes.

    Args:
        value: A supported scalar or container.
        output: The buffer receiving exactly one framed value.

    Raises:
        ValueError: When NumPy storage could contain executable object references.
    """
    if value is None or value is pd.NA or value is pd.NaT:
        kind = (
            "none" if value is None else "missing" if value is pd.NA else "not_a_time"
        )
        append_scalar(kind, b"", output)
    elif isinstance(value, enum.Enum):
        append_children("enum", (type_name(type(value)), value.value), output)
    elif isinstance(value, pint.Quantity):
        append_children("quantity", (value.magnitude, str(value.units)), output)
    elif isinstance(value, datetime.datetime):
        append_children(
            "timestamp" if isinstance(value, pd.Timestamp) else "datetime",
            (value.isoformat(), value.fold, value.unit)
            if isinstance(value, pd.Timestamp)
            else (value.isoformat(), value.fold),
            output,
        )
    elif isinstance(value, datetime.timedelta):
        if isinstance(value, pd.Timedelta):
            append_children("pandas_timedelta", (value.asm8,), output)
        else:
            append_children(
                "timedelta",
                (value.days, value.seconds, value.microseconds),
                output,
            )
    elif isinstance(value, np.generic):
        if value.dtype.hasobject or value.dtype.fields is not None:
            message = "Object and structured NumPy scalars are not cache values"
            raise ValueError(message)
        append_children("numpy", (value.dtype.str, value.tobytes()), output)
    elif isinstance(value, shapely.Geometry):
        append_scalar("geometry", shapely.to_wkb(value, include_srid=True), output)
    else:
        write_builtin(value, output)


def write_builtin(value: object, output: bytearray) -> None:
    """Distinguish scalar types and retain ordered container boundaries.

    Args:
        value: A builtin scalar or supported container.
        output: The buffer receiving exactly one framed value.
    """
    if isinstance(value, bool):
        append_scalar("bool", bytes((value,)), output)
    elif isinstance(value, int):
        append_scalar("int", str(value).encode(), output)
    elif isinstance(value, float):
        append_scalar("float", struct.pack("!d", value), output)
    elif isinstance(value, str):
        append_scalar("str", value.encode(), output)
    elif isinstance(value, bytes):
        append_scalar("bytes", value, output)
    elif isinstance(value, (tuple, list)):
        append_children("tuple" if isinstance(value, tuple) else "list", value, output)
    elif isinstance(value, frozenset):
        children = sorted(dumps(child)[len(MAGIC) :] for child in value)
        append_scalar("frozenset", b"".join(children), output)
    elif isinstance(value, dict):
        append_children(
            "dict",
            (child for pair in value.items() for child in pair),
            output,
        )
    else:
        unsupported(value)


def unsupported(value: object) -> typing.Never:
    """Refuse values outside the explicitly supported cache domain.

    Args:
        value: The unsupported object.

    Raises:
        ValueError: Always; arbitrary objects cannot be stored safely.
    """
    message = f"Unsupported cache value: {type_name(type(value))}"
    raise ValueError(message)


def type_name(value: type) -> str:
    """Identify allowed enum classes without importing names from cache bytes.

    Args:
        value: The concrete class being identified.

    Returns:
        Its module-qualified name.
    """
    return f"{value.__module__}.{value.__qualname__}"


def loads(payload: bytes, *, enums: tuple[type[enum.Enum], ...] = ()) -> object:
    """Accept one complete canonical value and explicitly approved domain enums.

    Args:
        payload: One versioned binary cache value.
        enums: Enum classes the caller permits constructing.

    Returns:
        The restored scalar or container.

    Raises:
        ValueError: If framing, types, contents, or canonical ordering are invalid.
    """
    if not payload.startswith(MAGIC):
        message = "Unsupported cache value version"
        raise ValueError(message)
    try:
        value, end = read_value(
            payload,
            len(MAGIC),
            {type_name(item): item for item in enums},
        )
        if end != len(payload) or dumps(value) != payload:
            message = "Cache value has a noncanonical representation"
            raise ValueError(message)
    except (
        KeyError,
        TypeError,
        IndexError,
        OverflowError,
        struct.error,
        pint.errors.PintError,
        shapely.errors.GEOSException,
    ) as error:
        message = "Invalid cache value"
        raise ValueError(message) from error
    return value


def read_missing(payload: bytes, value: object) -> object:
    """Supply the missing sentinel while canonical validation checks empty contents.

    Args:
        payload: Framed scalar contents.
        value: The sentinel associated with its distinct type tag.

    Returns:
        The corresponding sentinel.

    Raises:
        ValueError: When a missing sentinel carries unexpected contents.
    """
    if payload:
        message = "Missing cache values require empty contents"
        raise ValueError(message)
    return value


def read_bool(payload: bytes) -> bool:
    """Decode one boolean byte for subsequent canonical validation.

    Args:
        payload: The stored boolean contents.

    Returns:
        Its truth value.
    """
    return bool(payload[0])


def read_float(payload: bytes) -> float:
    """Restore exact binary64 bits, including signed zero and NaN payloads.

    Args:
        payload: Exactly eight network-order bytes.

    Returns:
        The represented Python float.
    """
    return struct.unpack("!d", payload)[0]


LEAF_READERS: dict[int, typing.Callable[[bytes], object]] = {
    TAGS["none"]: functools.partial(read_missing, value=None),
    TAGS["missing"]: functools.partial(read_missing, value=pd.NA),
    TAGS["not_a_time"]: functools.partial(read_missing, value=pd.NaT),
    TAGS["bool"]: read_bool,
    TAGS["int"]: int,
    TAGS["float"]: read_float,
    TAGS["str"]: bytes.decode,
    TAGS["bytes"]: bytes,
    TAGS["geometry"]: shapely.from_wkb,
}


def read_value(
    payload: bytes,
    start: int,
    enums: typing.Mapping[str, type[enum.Enum]],
) -> tuple[object, int]:
    """Parse a bounded node without accepting incomplete children or trailing fields.

    Args:
        payload: The complete root buffer or one complete parent's payload.
        start: The next node's header offset.
        enums: Explicit allowed enum constructors.

    Returns:
        The restored node and the first offset after it.

    Raises:
        ValueError: If the declared node extends beyond its enclosing payload.
    """
    tag, size = HEADER.unpack_from(payload, start)
    first = start + HEADER.size
    end = first + size
    if end > len(payload):
        message = "Incomplete cache value"
        raise ValueError(message)
    content = payload[first:end]
    if tag in LEAF_READERS:
        return LEAF_READERS[tag](content), end
    children = []
    position = 0
    while position < len(content):
        child, position = read_value(content, position, enums)
        children.append(child)
    return construct(tag, children, enums), end


def construct(
    tag: int,
    children: list[object],
    enums: typing.Mapping[str, type[enum.Enum]],
) -> object:
    """Reconstruct only declared containers and safe composite scalar types.

    Args:
        tag: The wire type of this non-leaf node.
        children: Complete decoded children in their recorded order.
        enums: Explicit enum constructors supplied by the caller.

    Returns:
        The safely reconstructed value.
    """
    if tag in {TAGS["tuple"], TAGS["list"], TAGS["frozenset"]}:
        constructor = {
            TAGS["tuple"]: tuple,
            TAGS["list"]: list,
            TAGS["frozenset"]: frozenset,
        }[tag]
        return constructor(children)
    if tag == TAGS["dict"]:
        return dict(zip(children[::2], children[1::2], strict=True))
    return construct_special(tag, children, enums)


def construct_special(
    tag: int,
    children: list[object],
    enums: typing.Mapping[str, type[enum.Enum]],
) -> object:
    """Restore explicitly declared composite scalars from their ordered fields.

    Args:
        tag: The composite scalar's type tag.
        children: Complete typed fields.
        enums: Explicitly allowed enum constructors.

    Returns:
        The reconstructed scalar.
    """
    match tag, children:
        case 12, [str(name), value] if name in enums:
            return enums[name](value)
        case 13, [magnitude, str(unit)]:
            return quantity(magnitude, unit)
        case 14, [str(instant), int(fold)]:
            return datetime.datetime.fromisoformat(instant).replace(fold=fold)
        case 15, [str(instant), int(fold), str(unit)]:
            return timestamp(instant, fold, unit)
        case 16, [int(days), int(seconds), int(microseconds)]:
            return datetime.timedelta(
                days=days,
                seconds=seconds,
                microseconds=microseconds,
            )
        case _:
            return construct_numpy(tag, children)


def construct_numpy(tag: int, children: list[object]) -> object:
    """Validate NumPy field shape before interpreting its native byte representation.

    Args:
        tag: The candidate NumPy tag.
        children: Its dtype and exact bytes, when valid.

    Returns:
        The safely restored NumPy scalar.

    Raises:
        ValueError: When this is not a supported NumPy scalar shape.
    """
    match tag, children:
        case 17, [np.timedelta64() as duration]:
            return pd.Timedelta(duration)
        case 18, [str(dtype), bytes(content)]:
            return numpy_scalar(dtype, content)
        case _:
            message = "Unsupported or invalid cache value"
            raise ValueError(message)


def timestamp(instant: str, fold: int, unit: str) -> pd.Timestamp:
    """Keep timestamp storage resolution and ambiguity folds distinct.

    Args:
        instant: The exact ISO instant and offset.
        fold: The ambiguity fold bit.
        unit: The original storage resolution.

    Returns:
        The reconstructed timestamp.

    Raises:
        TypeError: When the instant names a missing sentinel instead of a timestamp.
    """
    value = pd.Timestamp(instant)
    if not isinstance(value, pd.Timestamp):
        message = "A cached timestamp cannot contain a missing value"
        raise TypeError(message)
    return value.as_unit(
        typing.cast("typing.Literal['s', 'ms', 'us', 'ns']", unit),
    ).replace(fold=fold)


def numpy_scalar(dtype: str, payload: bytes) -> np.generic:
    """Exclude object arrays and ambiguous buffers from scalar reconstruction.

    Args:
        dtype: One plain NumPy scalar dtype descriptor.
        payload: Its exact native scalar bytes.

    Returns:
        The single numeric or textual scalar.

    Raises:
        ValueError: When the dtype or buffer does not identify one safe scalar.
    """
    scalar_type = np.dtype(dtype)
    if scalar_type.hasobject or scalar_type.fields is not None:
        message = "Unsafe NumPy cache dtype"
        raise ValueError(message)
    elements = np.frombuffer(payload, dtype=scalar_type)
    if len(elements) != 1:
        message = "A NumPy cache scalar must hold exactly one value"
        raise ValueError(message)
    return elements[0]


def quantity(magnitude: object, unit: str) -> pint.Quantity:
    """Keep the original unit and scalar bits using the shared measurement registry.

    Args:
        magnitude: Decoded numeric magnitude in its original unit.
        unit: The original unit expression.

    Returns:
        The exact scalar quantity.

    Raises:
        TypeError: When the magnitude is not a supported numeric scalar.
    """
    if not isinstance(magnitude, (int, float, np.integer, np.floating)):
        message = "A cached quantity requires a numeric scalar"
        raise TypeError(message)
    return units.Quantity(magnitude, unit)
