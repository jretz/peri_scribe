"""Format application values only for log rendering and timed execution."""

import contextlib
import dataclasses
import datetime
import enum
import json
import pathlib

import pint
import pyproj

from measurement_units import units


def log_value(value: object) -> object:
    """Give console and JSON logs the same representations of application values.

    Args:
        value: A logged value, possibly inside a collection.

    Returns:
        The value with quantities, paths, coordinate systems, and dates normalized.
    """
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        value = {
            field.name: getattr(value, field.name)
            for field in dataclasses.fields(value)
        }
    if isinstance(value, dict):
        return {name: log_value(item) for name, item in value.items()}
    if isinstance(value, (set, frozenset)):
        # A canonical baseline keeps incomparable or partially ordered values stable.
        value = sorted(
            value,
            key=lambda item: json.dumps(log_value(item), sort_keys=True, default=repr),
        )
        with contextlib.suppress(TypeError):
            value = sorted(value)
    if isinstance(value, (list, tuple)):
        return [log_value(item) for item in value]
    if isinstance(value, datetime.timedelta):
        value = value.total_seconds() * units.seconds
    if isinstance(value, pint.Quantity):
        unit_name = str(value.units)
        return {"value": float(value.magnitude), "units": unit_name}
    if isinstance(value, (enum.StrEnum, pathlib.PurePath, pyproj.CRS)):
        return str(value)
    if isinstance(value, (datetime.date, datetime.time)):
        return value.isoformat()
    return value


def seconds(value: float) -> pint.Quantity[float]:
    """Attach the shared time unit to the monotonic clock's reading.

    Args:
        value: A reading from the monotonic clock in seconds.

    Returns:
        The same reading as a quantity for log timing.
    """
    return value * units.seconds
