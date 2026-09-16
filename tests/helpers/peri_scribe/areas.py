"""Inspect areas behavior with shared test utilities."""

from __future__ import annotations

import typing


if typing.TYPE_CHECKING:
    import pint


def acres(value: pint.Quantity[float] | None) -> float | None:
    """Keep acreage assertions independent of a quantity's internal unit.

    Args:
        value: The selected area, including a possible missing result.

    Returns:
        The area in acres, or None when the measurement is absent.
    """
    return None if value is None else value.m_as("acres")
