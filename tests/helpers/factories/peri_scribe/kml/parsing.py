"""Build inputs for parsing tests."""

from __future__ import annotations

import datetime
import typing

import geopandas

import peri_scribe.models
import peri_scribe.presentation.perimeters


if typing.TYPE_CHECKING:
    import shapely.geometry


def perimeter_with_time(
    geometry: shapely.Geometry,
    observation_time: datetime.datetime | None = None,
) -> peri_scribe.presentation.perimeters.Perimeter:
    """Build a perimeter with *geometry* and *observation_time*.

    Args:
        geometry: The perimeter geometry.
        observation_time: The perimeter's observation time, or None.

    Returns:
        The perimeter.
    """
    return peri_scribe.presentation.perimeters.Perimeter(
        geometry=geometry,
        observation_time=observation_time,
    )


def geometry_frame(
    rows: list[tuple[str | None, str, shapely.geometry.base.BaseGeometry]],
    observation_times: list[datetime.datetime | None] | None = None,
    area_acres: list[float | None] | None = None,
) -> geopandas.GeoDataFrame:
    """Build a history GeoDataFrame from (identifier, name, geometry) rows.

    Args:
        rows: The identifier, name, and geometry of each row.
        observation_times: The observation time of each row, or None for every row when
            omitted.
        area_acres: The computed area of each row, or None to omit the column.

    Returns:
        The rows as a GeoDataFrame.
    """
    data: dict[str, object] = {
        "fire_identifier": [identifier for identifier, _name, _geometry in rows],
        "fire_name": [name for _identifier, name, _geometry in rows],
        "observation_time": (
            [None] * len(rows) if observation_times is None else observation_times
        ),
    }
    if area_acres is not None:
        data["area_acres"] = area_acres
    return geopandas.GeoDataFrame(
        data,
        geometry=[geometry for _identifier, _name, geometry in rows],
        crs="EPSG:4326",
    )


def fire_index_entry(
    name: str,
    status: typing.Literal["active", "inactive"],
    *,
    identifier: str | None = None,
    aliases: list[str] | None = None,
) -> peri_scribe.models.FireIndexEntry:
    """Build a fire index entry with empty paths.

    Args:
        name: The fire name.
        status: The fire status.
        identifier: The canonical identifier.
        aliases: Every alias identifier.

    Returns:
        The fire index entry.
    """
    return peri_scribe.models.FireIndexEntry(
        name=name,
        status=status,
        identifier=identifier,
        aliases=[] if aliases is None else aliases,
        paths=[],
    )


def fire_index(
    entries: list[peri_scribe.models.FireIndexEntry],
) -> peri_scribe.models.FireIndex:
    """Build a fire index from *entries*.

    Args:
        entries: The fire index entries.

    Returns:
        The fire index.
    """
    return peri_scribe.models.FireIndex(version="2026-08-18", fires=entries)
