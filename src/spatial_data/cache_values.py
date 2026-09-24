"""Typed cache values preserve measurements without executing stored objects."""

from __future__ import annotations

import datetime
import enum
import json
import struct
import typing

import numpy as np
import pandas as pd
import pint
import shapely

from measurement_units import units


def dumps(value: object) -> bytes:
    """Preserve exact scalar types and ordered containers in cache payloads.

    Args:
        value: Supported data composed of scalar values and containers.

    Returns:
        A tagged JSON payload with exact floating-point bytes.

    """
    return json.dumps(encode(value), ensure_ascii=False, separators=(",", ":")).encode()


def encode(value: object) -> list[object]:
    """Keep nulls, numeric types, original units, and timestamp precision distinct.

    Args:
        value: One supported value, possibly containing further values.

    Returns:
        Its tagged JSON representation.

    """
    if value is None or value is pd.NA or value is pd.NaT:
        tag = "none" if value is None else "missing" if value is pd.NA else "not_a_time"
        return [tag]
    if isinstance(
        value,
        (
            enum.Enum,
            pint.Quantity,
            datetime.datetime,
            datetime.timedelta,
            np.generic,
            shapely.Geometry,
        ),
    ):
        return encode_special(value)
    return encode_builtin(value)


def encode_special(value: object) -> list[object]:
    """Preserve domain scalar representations before considering their base types.

    Args:
        value: An enum, quantity, timestamp, NumPy scalar, or geometry.

    Returns:
        The tagged scalar representation.

    Raises:
        ValueError: When a NumPy scalar could contain executable object references.
    """
    if isinstance(value, enum.Enum):
        return ["enum", type_name(type(value)), encode(value.value)]
    if isinstance(value, pint.Quantity):
        return ["quantity", encode(value.magnitude), str(value.units)]
    if isinstance(value, datetime.datetime):
        return (
            ["timestamp", value.isoformat(), value.fold, value.unit]
            if isinstance(value, pd.Timestamp)
            else ["datetime", value.isoformat(), value.fold]
        )
    if isinstance(value, datetime.timedelta):
        return (
            ["pandas_timedelta", encode(value.asm8)]
            if isinstance(value, pd.Timedelta)
            else ["timedelta", value.days, value.seconds, value.microseconds]
        )
    if isinstance(value, np.generic):
        if value.dtype.hasobject or value.dtype.fields is not None:
            message = "Object and structured NumPy scalars are not cache values"
            raise ValueError(message)
        return ["numpy", value.dtype.str, value.tobytes().hex()]
    return ["geometry", shapely.to_wkb(value, include_srid=True).hex()]


def encode_builtin(value: object) -> list[object]:
    """Retain Python numeric type and floating-point bits without JSON coercion.

    Args:
        value: A builtin scalar or container.

    Returns:
        The tagged representation.
    """
    if isinstance(value, bool):
        return ["bool", value]
    if isinstance(value, int):
        return ["int", str(value)]
    if isinstance(value, float):
        return ["float", struct.pack("!d", value).hex()]
    if isinstance(value, str):
        return ["str", value]
    if isinstance(value, bytes):
        return ["bytes", value.hex()]
    return encode_container(value)


def encode_container(value: object) -> list[object]:
    """Keep sequence and mapping order while refusing arbitrary object storage.

    Args:
        value: A supported container holding further cache values.

    Returns:
        Its recursively tagged representation.

    Raises:
        ValueError: When the value is not a supported container.
    """
    if isinstance(value, tuple):
        return ["tuple", [encode(item) for item in value]]
    if isinstance(value, list):
        return ["list", [encode(item) for item in value]]
    if isinstance(value, frozenset):
        return ["frozenset", sorted((encode(item) for item in value), key=json.dumps)]
    if isinstance(value, dict):
        return ["dict", [[encode(key), encode(item)] for key, item in value.items()]]
    message = f"Unsupported cache value: {type_name(type(value))}"
    raise ValueError(message)


def type_name(value: type) -> str:
    """Identify explicitly allowed enum types without importing names from a cache.

    Args:
        value: The concrete class being identified.

    Returns:
        Its module-qualified name.
    """
    return f"{value.__module__}.{value.__qualname__}"


def loads(
    payload: bytes,
    *,
    enums: tuple[type[enum.Enum], ...] = (),
) -> object:
    """Read supported values while requiring an explicit whitelist for enums.

    Args:
        payload: A tagged JSON cache payload.
        enums: Domain enum types that the caller permits constructing.

    Returns:
        The decoded values.

    Raises:
        ValueError: When the payload is invalid, unsupported, or noncanonical.
    """
    try:
        value = decode(json.loads(payload), {type_name(item): item for item in enums})
        if dumps(value) != payload:
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


def decode(value: object, enums: typing.Mapping[str, type[enum.Enum]]) -> object:
    """Construct only the safe scalar and container types used by stored products.

    Args:
        value: One tagged JSON value.
        enums: Explicit domain enum constructors keyed by qualified name.

    Returns:
        The decoded value.

    Raises:
        TypeError: When a stored pandas duration contains a different scalar type.

    """
    match value:
        case ["pandas_timedelta", ["numpy", str(dtype), str(item)]]:
            duration = numpy_scalar(dtype, item)
            if not isinstance(duration, np.timedelta64):
                message = "A pandas duration requires a NumPy timedelta scalar"
                raise TypeError(message)
            return pd.Timedelta(duration)
        case ["quantity", magnitude, str(unit)]:
            return quantity(decode(magnitude, enums), unit)
        case ["enum", str(name), item] if name in enums:
            return enums[name](decode(item, enums))
        case [str(kind), list(items)] if kind in {"tuple", "list", "frozenset"}:
            constructor = {"tuple": tuple, "list": list, "frozenset": frozenset}[kind]
            return constructor(decode(item, enums) for item in items)
        case ["dict", list(items)]:
            return {decode(key, enums): decode(item, enums) for key, item in items}
        case _:
            return decode_scalar(value)


def decode_scalar(value: object) -> object:
    """Interpret builtin scalar tags without accepting implicit type conversions.

    Args:
        value: A tagged scalar representation.

    Returns:
        Its exact decoded scalar value.
    """
    match value:
        case [str(kind)] if kind in {"none", "missing", "not_a_time"}:
            return {"none": None, "missing": pd.NA, "not_a_time": pd.NaT}[kind]
        case ["bool", bool(item)]:
            return item
        case ["int", str(item)]:
            return int(item)
        case ["float", str(item)]:
            return struct.unpack("!d", bytes.fromhex(item))[0]
        case [str(kind), str(item)] if kind in {"str", "bytes"}:
            return item if kind == "str" else bytes.fromhex(item)
        case _:
            return decode_special(value)


def decode_special(value: object) -> object:
    """Reconstruct known native scalars while refusing unknown executable types.

    Args:
        value: A tagged timestamp, NumPy scalar, or geometry.

    Returns:
        Its safely reconstructed value.

    Raises:
        ValueError: When a tag has no supported reconstruction.
        TypeError: When a pandas timestamp contains a missing value.
    """
    match value:
        case ["datetime", str(item), int(fold)]:
            return datetime.datetime.fromisoformat(item).replace(fold=fold)
        case ["timestamp", str(item), int(fold), str(unit)]:
            timestamp = pd.Timestamp(item)
            if not isinstance(timestamp, pd.Timestamp):
                message = "A cached timestamp cannot contain a missing value"
                raise TypeError(message)
            return timestamp.as_unit(
                typing.cast("typing.Literal['s', 'ms', 'us', 'ns']", unit),
            ).replace(fold=fold)
        case ["timedelta", int(days), int(seconds), int(microseconds)]:
            return datetime.timedelta(
                days=days,
                seconds=seconds,
                microseconds=microseconds,
            )
        case ["numpy", str(dtype), str(item)]:
            return numpy_scalar(dtype, item)
        case ["geometry", str(item)]:
            return shapely.from_wkb(bytes.fromhex(item))
        case _:
            message = "Unsupported or invalid cache value"
            raise ValueError(message)


def numpy_scalar(dtype: str, payload: str) -> np.generic:
    """Exclude object arrays and ambiguous scalar buffers from cache reconstruction.

    Args:
        dtype: A plain NumPy scalar dtype descriptor.
        payload: Its exact scalar bytes as hexadecimal text.

    Returns:
        The single numeric or textual scalar.

    Raises:
        ValueError: When the dtype or buffer does not identify one safe scalar.
    """
    scalar_type = np.dtype(dtype)
    if scalar_type.hasobject or scalar_type.fields is not None:
        message = "Unsafe NumPy cache dtype"
        raise ValueError(message)
    elements = np.frombuffer(bytes.fromhex(payload), dtype=scalar_type)
    if len(elements) != 1:
        message = "A NumPy cache scalar must hold exactly one value"
        raise ValueError(message)
    return elements[0]


def quantity(magnitude: object, unit: str) -> pint.Quantity:
    """Reject nonscalar measurements instead of introducing implicit array conversion.

    Args:
        magnitude: The decoded numeric magnitude in its original unit.
        unit: The original unit expression.

    Returns:
        The exact scalar quantity using the application's shared registry.

    Raises:
        TypeError: When the magnitude is not a supported numeric scalar.
    """
    if not isinstance(magnitude, (int, float, np.integer, np.floating)):
        message = "A cached quantity requires a numeric scalar"
        raise TypeError(message)
    return units.Quantity(magnitude, unit)
