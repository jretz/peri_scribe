"""Exact typed cache values and rejection of unsafe or corrupt payloads."""

from __future__ import annotations

import datetime
import json
import struct
import typing

import numpy as np
import pandas as pd
import pint
import pytest
import shapely

import peri_scribe.areas
import spatial_data.cache_values
from measurement_units import units


@pytest.mark.parametrize(
    "value",
    [
        None,
        pd.NA,
        pd.NaT,
        True,
        False,
        10**40,
        -0.0,
        float("inf"),
        struct.unpack("!d", bytes.fromhex("7ff8000000000007"))[0],
        "Unicode 🔥",
        b"\x00\xff",
        (1, "two"),
        [1, "two"],
        {"second": 2, "first": 1},
        frozenset({"a", "b"}),
        datetime.datetime(2026, 9, 1, 2, 3, 4, 5, tzinfo=datetime.UTC),
        datetime.timedelta(days=-1, seconds=13, microseconds=7),
        pd.Timedelta(1, unit="ns"),
        pd.Timedelta(1, unit="s").as_unit("s"),
        pd.Timestamp("2026-09-01T02:03:04.123456789Z"),
        np.float32(1.234567),
        np.int64(-42),
        np.datetime64("2026-09-01", "ns"),
        1.2345678901234567 * units.Unit("meters ** 2"),
        shapely.set_srid(shapely.Point(1.23456789012345, 2), 4326),
        peri_scribe.areas.AreaSource.MAPPED,
    ],
)
def test_dumps_round_trip_preserves_exact_scalar_and_container_representations(
    value: object,
) -> None:
    payload = spatial_data.cache_values.dumps(value)
    restored = spatial_data.cache_values.loads(
        payload,
        enums=(peri_scribe.areas.AreaSource,),
    )
    assert type(restored) is type(value)
    assert spatial_data.cache_values.dumps(restored) == payload


def test_loads_preserves_quantity_magnitude_bits_and_original_units() -> None:
    original = 1234.5678901234567 * units.Unit("meters ** 2")
    restored = spatial_data.cache_values.loads(
        spatial_data.cache_values.dumps(original),
    )
    assert isinstance(restored, pint.Quantity)
    assert restored.units == original.units
    assert struct.pack("!d", restored.magnitude) == struct.pack(
        "!d",
        original.magnitude,
    )


def test_loads_preserves_timestamp_nanoseconds() -> None:
    original = pd.Timestamp("2026-09-01T02:03:04.123456789Z")
    restored = spatial_data.cache_values.loads(
        spatial_data.cache_values.dumps(original),
    )
    assert isinstance(restored, pd.Timestamp)
    assert restored.value == original.value


@pytest.mark.parametrize(
    ("text", "unit"),
    [
        ("2026-09-01T00:00:00Z", "s"),
        ("2026-09-01T00:00:00Z", "us"),
        ("2026-09-01T00:00:00.123Z", "ms"),
        ("2026-09-01T00:00:00.123456Z", "us"),
        ("2026-09-01T00:00:00.123456789Z", "ns"),
    ],
)
def test_loads_retains_pandas_timestamp_storage_resolution(
    text: str,
    unit: typing.Literal["s", "ms", "us", "ns"],
) -> None:
    original = pd.Timestamp(text)
    assert isinstance(original, pd.Timestamp)
    original = original.as_unit(unit)
    restored = spatial_data.cache_values.loads(
        spatial_data.cache_values.dumps(original),
    )
    assert isinstance(restored, pd.Timestamp)
    assert restored.value == original.value
    assert restored.unit == original.unit


def test_dumps_keeps_distinct_nanosecond_pandas_durations_distinct() -> None:
    first = pd.Timedelta(1, unit="ns")
    second = pd.Timedelta(2, unit="ns")
    assert spatial_data.cache_values.dumps(first) != spatial_data.cache_values.dumps(
        second,
    )


@pytest.mark.parametrize(
    "value",
    [
        object(),
        np.array([(object(),)], dtype=[("value", object)])[0],
        np.array([(1,)], dtype=[("value", "i4")])[0],
    ],
)
def test_dumps_rejects_unsupported_or_object_bearing_scalars(value: object) -> None:
    with pytest.raises(ValueError, match=r"[Cc]ache|NumPy"):
        spatial_data.cache_values.dumps(value)


@pytest.mark.parametrize(
    "value",
    [
        ["unknown"],
        ["bool", 1],
        ["float", "00"],
        ["int", "01"],
        ["dict", [[["list", []], ["int", "1"]]]],
        ["numpy", "O", "0000000000000000"],
        ["numpy", "i4,i4", "0000000000000000"],
        ["numpy", "i4", ""],
        ["numpy", "i4", "0000000000000000"],
        ["timestamp", "NaT", 0, "ns"],
        ["pandas_timedelta", ["numpy", "i4", "00000000"]],
        ["quantity", ["list", []], "acre"],
        ["quantity", ["int", "1"], "not_an_existing_unit"],
        ["geometry", "00"],
        ["enum", "os.system", ["str", "anything"]],
    ],
)
def test_loads_rejects_malformed_or_unapproved_reconstruction(value: object) -> None:
    payload = json.dumps(value, separators=(",", ":")).encode()
    with pytest.raises(ValueError, match=r"[Cc]ache|NumPy"):
        spatial_data.cache_values.loads(payload)


def test_loads_requires_explicit_enum_permission() -> None:
    payload = spatial_data.cache_values.dumps(peri_scribe.areas.AreaSource.MAPPED)
    with pytest.raises(ValueError, match="Unsupported"):
        spatial_data.cache_values.loads(payload)
