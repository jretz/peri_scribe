"""Inspect plot histories behavior with shared test utilities."""

from __future__ import annotations

import typing

import spatial_data.measurements


if typing.TYPE_CHECKING:
    import shapely.geometry


def exterior_length(geometry: shapely.Geometry) -> float:
    """Return *geometry*'s exterior perimeter length, which is always known.

    Args:
        geometry: A non-empty polygon.

    Returns:
        The exterior perimeter length in miles.
    """
    length = spatial_data.measurements.exterior_perimeter(geometry)
    assert length is not None
    return length.m_as("miles")
