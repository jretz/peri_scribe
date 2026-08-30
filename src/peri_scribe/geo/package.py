"""Reading fire records and complex memberships from GeoPackage files.

Interprets each configured feed's layer into fire records, full source rows, and complex
memberships, and provides the attribute-value helpers the rest of the project uses to
read those rows.
"""

from __future__ import annotations

import dataclasses
import json
import pathlib
import sqlite3
import typing

import geopandas
import shapely
import structlog

import peri_scribe.exceptions
import peri_scribe.geo.parsing
import peri_scribe.models
import peri_scribe.sources.feed_types
import peri_scribe.sources.feeds


logger = structlog.get_logger()


def layers_by_feed(
    path: pathlib.Path,
) -> typing.Iterator[
    tuple[peri_scribe.sources.feed_types.Feed, geopandas.GeoDataFrame]
]:
    """Yield each layer of the GeoPackage at *path* with its configured feed.

    Args:
        path: The GeoPackage file to read.

    Yields:
        Each ``(feed, dataframe)`` pair, one per layer, in the order encountered.

    Raises:
        UnknownLayerError: If a layer does not correspond to a configured feed.
    """
    feeds_by_name = {feed.name: feed for feed in peri_scribe.sources.feeds.FEEDS}
    for layer_name in geopandas.list_layers(path)["name"]:
        feed = feeds_by_name.get(layer_name)
        if feed is None:
            raise peri_scribe.exceptions.UnknownLayerError(layer_name, path)
        yield feed, geopandas.read_file(path, layer=feed.name)


@dataclasses.dataclass(frozen=True, kw_only=True)
class FireRowRecord:
    """One fire source row with its identifying record and full attributes.

    The record carries the fire's identifying fields; the attributes carry every
    non-geometry column so downstream consumers can bring the row's own fields along.
    """

    record: peri_scribe.models.FireRecord
    object_id: int | None
    source_name: str
    attributes: dict[str, object]

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> FireRowRecord:
        """Return the row described by one record cache database row.

        The record's fixed fields come from typed columns and the attribute bag comes
        from a JSON column, mirroring how the row was stored by ``to_row``. The identity
        and name sets are rebuilt as frozensets and timestamps are parsed by the same
        normalization helpers the rest of the project uses.

        Args:
            row: One ``rows`` table row, keyed by column name.

        Returns:
            The fire row.
        """
        return cls(
            record=peri_scribe.models.FireRecord(
                name=row["name"],
                status=peri_scribe.models.FireStatus(row["status"]),
                identifiers=frozenset(json.loads(row["identifiers"])),
                names=frozenset(json.loads(row["names"])),
                geometry=(
                    shapely.from_wkb(row["geometry_wkb"])
                    if row["geometry_wkb"] is not None
                    else None
                ),
                observed_at=peri_scribe.geo.parsing.observation_time_from(
                    row["observed_at"],
                ),
                mission=row["mission"],
                point_of_origin_state=row["point_of_origin_state"],
                point_of_origin_fips=row["point_of_origin_fips"],
            ),
            object_id=row["object_id"],
            source_name=row["source_name"],
            attributes=json.loads(row["attributes_json"]),
        )

    def to_row(self, serial: int) -> tuple[object, ...]:
        """Return this row's record cache database columns, keyed by *serial*.

        Timestamps are stored as ISO-8601 text and the attribute bag as a JSON-safe
        object, so the database is inspectable with standard SQLite tools.

        Args:
            serial: The serial number of the snapshot the row came from.

        Returns:
            The ``rows`` table columns, in schema order.
        """
        record = self.record
        return (
            serial,
            self.object_id,
            self.source_name,
            record.name,
            record.status.value,
            json.dumps(sorted(record.identifiers)),
            json.dumps(sorted(record.names)),
            record.geometry.wkb if record.geometry is not None else None,
            (
                record.observed_at.isoformat()
                if record.observed_at is not None
                else None
            ),
            record.mission,
            record.point_of_origin_state,
            record.point_of_origin_fips,
            json.dumps(
                {
                    key: peri_scribe.geo.parsing.json_cache_value(value)
                    for key, value in self.attributes.items()
                },
            ),
        )


@dataclasses.dataclass(frozen=True, kw_only=True)
class GeopackageContents:
    """Every fire row and complex membership in one GeoPackage file."""

    rows: tuple[FireRowRecord, ...]
    memberships: tuple[peri_scribe.models.ComplexMembership, ...]


def read_geopackage(path: pathlib.Path) -> GeopackageContents:
    """Read the fire rows and complex memberships of the GeoPackage at *path*.

    Each layer is read once and each of its rows is walked once, so a row that both
    names a fire and records a complex membership contributes to both results. The file
    is only read, never written.

    Args:
        path: The GeoPackage file to read.

    Returns:
        The fire rows and complex memberships, each in row order.
    """
    rows: list[FireRowRecord] = []
    memberships: list[peri_scribe.models.ComplexMembership] = []
    for feed, dataframe in layers_by_feed(path):
        geometry_name = str(dataframe.geometry.name)
        membership_columns = peri_scribe.geo.parsing.complex_membership_columns(feed)
        for index in range(len(dataframe)):
            row = dataframe.iloc[index]
            record = peri_scribe.geo.parsing.fire_record_from_row(
                row,
                feed,
                row[geometry_name],
            )
            if record is not None:
                rows.append(
                    FireRowRecord(
                        record=record,
                        object_id=peri_scribe.geo.parsing.object_id_from(row),
                        source_name=feed.name,
                        attributes=peri_scribe.geo.parsing.row_attributes(
                            row,
                            geometry_name,
                        ),
                    ),
                )
            if membership_columns is not None:
                membership = peri_scribe.geo.parsing.complex_membership_from_row(
                    row,
                    membership_columns,
                )
                if membership is not None:
                    memberships.append(membership)
    return GeopackageContents(rows=tuple(rows), memberships=tuple(memberships))
