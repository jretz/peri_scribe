"""Shared helpers for the fire-geometry test modules.

These frames take explicit attribute overrides, so a scoring test can set exactly the
columns it cares about.
"""

from __future__ import annotations

import dataclasses
import pathlib
import typing

import tests.factories


if typing.TYPE_CHECKING:
    import geopandas
    import shapely.geometry

    import peri_scribe.models


@dataclasses.dataclass(frozen=True, kw_only=True)
class ScoreFiresStubs:
    """The documents score_fires wrote and the CCDF writes it made."""

    writes: list[tuple[pathlib.Path, peri_scribe.models.FireScores]]
    ccdf_writes: list[tuple[pathlib.Path, peri_scribe.models.FireScores]]


def perimeter_frame(
    records: list[dict[str, object]],
    geometries: list[shapely.geometry.base.BaseGeometry],
) -> geopandas.GeoDataFrame:
    """Build a perimeter-history GeoDataFrame from attribute overrides.

    Args:
        records: One attribute override per row.
        geometries: The rows' geometries.

    Returns:
        The rows as a GeoDataFrame with the perimeter columns scoring reads.
    """
    columns = [
        "fire_name",
        "fire_identifier",
        "area_acres",
        "area_acres_differential",
        "observation_time",
    ]
    return tests.factories.geo_frame(
        {column: [record.get(column) for record in records] for column in columns},
        list(geometries),
    )


def point_frame(
    records: list[dict[str, object]],
    geometries: list[shapely.geometry.base.BaseGeometry],
) -> geopandas.GeoDataFrame:
    """Build a point-history GeoDataFrame from attribute overrides.

    Args:
        records: One attribute override per row.
        geometries: The rows' geometries.

    Returns:
        The rows as a GeoDataFrame with the point columns scoring reads.
    """
    columns = ["fire_name", "fire_identifier", "source_attributes"]
    return tests.factories.geo_frame(
        {column: [record.get(column) for record in records] for column in columns},
        list(geometries),
    )
