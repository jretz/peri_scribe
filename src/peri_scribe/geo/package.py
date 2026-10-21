"""Read fire records and complex memberships from GeoPackage files.

Each configured feed supplies identifying fire fields, full source attributes, and
complex memberships. Keeping those results together lets callers use the fire identity
without losing the evidence carried by its original row.

Design notes:
[Authenticated parsed source cache](../../../docs/algorithms/parsed-source-cache.md).
"""

from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
import pathlib
import sqlite3
import typing

import geopandas
import shapely
import structlog

import peri_scribe.exceptions
import peri_scribe.geo.fingerprints
import peri_scribe.geo.parsing
import peri_scribe.models
import peri_scribe.sources.feed_types
import peri_scribe.sources.feeds


if typing.TYPE_CHECKING:
    import spatial_data.geometry_pool


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
    """One source row with its fire identity and full attributes.

    The record holds the fire's identifying fields. The attributes retain every
    non-geometry column so later stages can use evidence beyond those identifying
    fields.
    """

    record: peri_scribe.models.FireRecord
    object_id: int | None
    source_name: str
    attributes: dict[str, object]
    evidence_fingerprint: str | None = dataclasses.field(default=None, compare=False)
    evidence_basis: peri_scribe.geo.fingerprints.FingerprintBasis | None = (
        dataclasses.field(default=None, compare=False)
    )

    @classmethod
    def from_row(
        cls,
        row: sqlite3.Row,
        *,
        geometry_pool: spatial_data.geometry_pool.GeometryPool,
    ) -> FireRowRecord:
        """Return the row described by one record cache database row.

        The record's fixed fields come from typed columns and the attribute bag comes
        from a JSON column, mirroring how the row was stored by ``to_row``. The identity
        and name sets are rebuilt as frozensets and timestamps are parsed by the same
        normalization helpers the rest of the project uses.

        Args:
            row: One ``rows`` table row, keyed by column name.
            geometry_pool: The source read's shared snapshot geometries.

        Returns:
            The fire row.
        """
        geometry = (
            geometry_pool.from_wkb(row["geometry_wkb"])
            if row["geometry_wkb"] is not None
            else None
        )
        attributes = json.loads(row["attributes_json"])
        return cls.from_cached_row(
            row,
            geometry,
            attributes,
            None
            if row["geometry_wkb"] is None
            else hashlib.sha256(row["geometry_wkb"]).hexdigest(),
            hashlib.sha256(row["attributes_json"].encode()).hexdigest(),
        )

    @classmethod
    def from_values(
        cls,
        row: sqlite3.Row,
        geometry: shapely.Geometry | None,
        attributes: dict[str, object],
    ) -> FireRowRecord:
        """Decode fixed fields while callers retain the chosen payload ownership.

        Args:
            row: Typed metadata read in source occurrence order.
            geometry: The immutable geometry already decoded for this payload.
            attributes: This row's independently owned attribute bag.

        Returns:
            The complete source observation.
        """
        return cls(
            record=peri_scribe.models.FireRecord(
                name=row["name"],
                status=peri_scribe.models.FireStatus(row["status"]),
                identifiers=frozenset(json.loads(row["identifiers"])),
                names=frozenset(json.loads(row["names"])),
                geometry=geometry,
                observed_at=peri_scribe.geo.parsing.observation_time_from(
                    row["observed_at"],
                ),
                mission=row["mission"],
                point_of_origin_state=row["point_of_origin_state"],
                point_of_origin_fips=row["point_of_origin_fips"],
            ),
            object_id=row["object_id"],
            source_name=row["source_name"],
            attributes=attributes,
        )

    @classmethod
    def from_cached_row(
        cls,
        row: sqlite3.Row,
        geometry: shapely.Geometry | None,
        attributes: dict[str, object],
        geometry_fingerprint: str | None,
        attributes_fingerprint: str,
    ) -> FireRowRecord:
        """Validate persisted evidence against exact dictionary payloads and metadata.

        Args:
            row: The cache's ordered typed metadata and expected fingerprint.
            geometry: The dictionary's shared immutable decoded geometry.
            attributes: A reader-owned template never exposed as a mutable row bag.
            geometry_fingerprint: Digest of the exact encoded geometry, if present.
            attributes_fingerprint: Digest of canonical encoded attributes.

        Returns:
            An independently mutable row with reusable complete evidence identity.

        Raises:
            ValueError: If the stored row identity disagrees with its current payloads.
        """
        decoded = cls.from_values(row, geometry, copy.deepcopy(attributes))
        expected = peri_scribe.geo.fingerprints.fingerprint_from_payloads(
            decoded,
            geometry_fingerprint,
            attributes_fingerprint,
        )
        if row["evidence_fingerprint"] != expected:
            message = "Parsed row fingerprint does not match its dictionary payloads"
            raise ValueError(message)
        return dataclasses.replace(
            decoded,
            evidence_fingerprint=expected,
            evidence_basis=peri_scribe.geo.fingerprints.FingerprintBasis(
                record=decoded.record,
                object_id=decoded.object_id,
                source_name=decoded.source_name,
                attributes=attributes,
            ),
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
            shapely.to_wkb(record.geometry, include_srid=True)
            if record.geometry is not None
            else None,
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
                    key: peri_scribe.geo.parsing.json_native_value(value)
                    for key, value in self.attributes.items()
                },
                sort_keys=True,
            ),
        )


@dataclasses.dataclass(frozen=True, kw_only=True)
class GeopackageContents:
    """Every fire row and complex membership in one GeoPackage file."""

    rows: tuple[FireRowRecord, ...]
    memberships: tuple[peri_scribe.models.ComplexMembership, ...]


def read_geopackage(path: pathlib.Path) -> GeopackageContents:
    """Read the fire rows and complex memberships of the GeoPackage at *path*.

    Read each layer once and visit each row once. A row can contribute both a fire and a
    complex membership, so collecting them together preserves that relationship without
    a second pass. Reading does not modify the file.

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
                memberships.extend(
                    peri_scribe.geo.parsing.complex_memberships_from_row(
                        row,
                        membership_columns,
                    ),
                )
    return GeopackageContents(rows=tuple(rows), memberships=tuple(memberships))
