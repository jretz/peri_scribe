"""Factories for building fire records and feeds in tests."""

from __future__ import annotations

import datetime
import pathlib
import typing

import geopandas
import pyproj
import shapely
import shapely.geometry

import peri_scribe.feed_types
import peri_scribe.models


ACTIVE = peri_scribe.models.FireStatus.ACTIVE


INACTIVE = peri_scribe.models.FireStatus.INACTIVE


class StubFireReader(typing.Protocol):
    """A function that installs in-memory fire and membership stand-ins."""

    def __call__(
        self,
        records_by_path: dict[pathlib.Path, list[peri_scribe.models.FireRecord]],
        memberships_by_path: dict[
            pathlib.Path,
            list[peri_scribe.models.ComplexMembership],
        ]
        | None = None,
    ) -> None: ...


def fire_record(
    name: str,
    status: peri_scribe.models.FireStatus,
    identifiers: typing.Iterable[str] = (),
    *,
    names: typing.Iterable[str] | None = None,
    geometry: shapely.Geometry | None = None,
    observed_at: datetime.datetime | None = None,
) -> peri_scribe.models.FireRecord:
    """Build a fire record for a test.

    Args:
        name: The record's display name.
        status: The record's status.
        identifiers: The record's normalized identifiers.
        names: The record's normalized name keys; defaults to the display name's
            normalization.
        geometry: The record's geometry.
        observed_at: The record's observation time.

    Returns:
        The record.
    """
    name_keys = (
        frozenset(names)
        if names is not None
        else frozenset({peri_scribe.models.normalize_fire_name(name)})
    )
    return peri_scribe.models.FireRecord(
        name=name,
        status=status,
        identifiers=frozenset(identifiers),
        names=name_keys,
        geometry=geometry,
        observed_at=observed_at,
    )


def change_feed(
    modified_column: str | None = "ModifiedOnDateTime_dt",
) -> peri_scribe.feed_types.Feed:
    """Return a feed with a known modified column.

    Args:
        modified_column: The modified timestamp column, or None.

    Returns:
        The feed.
    """
    return peri_scribe.feed_types.ArcGISFeed(
        url="https://example.test/ArcGIS/rest/services/Fires/FeatureServer/0",
        fire_name_column="name",
        status_column="status",
        modified_column=modified_column,
    )


def change_dataframe(
    rows: list[tuple[int, str, tuple[float, float]]],
) -> geopandas.GeoDataFrame:
    """Return a GeoDataFrame of point features for the given rows.

    Args:
        rows: The OBJECTID, name, and coordinates of each feature.

    Returns:
        The GeoDataFrame.
    """
    return geopandas.GeoDataFrame(
        {
            "OBJECTID": [row[0] for row in rows],
            "name": [row[1] for row in rows],
        },
        geometry=[shapely.geometry.Point(row[2]) for row in rows],
        crs=pyproj.CRS.from_epsg(4326),
    )
