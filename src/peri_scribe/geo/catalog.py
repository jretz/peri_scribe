"""Pin compact source metadata while detailed evidence has bounded lifetimes.

[Bounded source work](../../../docs/algorithms/bounded-source-work.md).
"""

from __future__ import annotations

import collections
import collections.abc
import contextlib
import dataclasses
import json
import pathlib
import sqlite3
import threading
import typing

import shapely

import peri_scribe.fires.complexes
import peri_scribe.fires.sources
import peri_scribe.geo.database
import peri_scribe.geo.dictionaries
import peri_scribe.geo.fingerprints
import peri_scribe.geo.package
import peri_scribe.geo.parsing
import peri_scribe.models
import peri_scribe.sources.provenance
import peri_scribe.sources.snapshots
import spatial_data.geometry_pool


class UnavailableError(ValueError):
    """A disposable catalog cannot serve complete authenticated evidence."""


@dataclasses.dataclass(frozen=True, kw_only=True)
class Entry:
    """Retain a pinned row reference without its coordinate or attribute payloads."""

    row: sqlite3.Row
    connection: int


@dataclasses.dataclass(frozen=True, kw_only=True)
class Catalog:
    """Keep metadata resident and serialize reads from pinned feed transactions."""

    directory: pathlib.Path
    connections: tuple[sqlite3.Connection, ...]
    entries: tuple[Entry, ...]
    read: peri_scribe.fires.sources.ReadFireSources
    lock: threading.Lock = dataclasses.field(default_factory=threading.Lock)

    def verify(self) -> None:
        """Reject source edits before completed work leaves its pinned scope.

        Raises:
            OSError: If the authoritative inventory changed during this preparation.
        """
        files = tuple(path for path, _checksum in self.read.source_checksums)
        if tuple(
            peri_scribe.sources.snapshots.geo_package_files(self.directory),
        ) != files or (
            peri_scribe.fires.sources.snapshot_checksums(files)
            != self.read.source_checksums
        ):
            message = "Sources changed during bounded preparation"
            raise OSError(message)

    def weight(self, positions: collections.abc.Sequence[int]) -> int:
        """Count distinct uncompressed payload bytes admitted with one source group.

        Args:
            positions: Global source occurrences required together by the consumer.

        Returns:
            Encoded input bytes; native geometry and output memory are additional.
        """
        seen: set[tuple[int, str, int]] = set()
        total = 0
        for position in positions:
            entry = self.entries[position]
            for kind in ("geometry", "attributes"):
                identifier = entry.row[kind + "_id"]
                key = entry.connection, kind, identifier
                if identifier is not None and key not in seen:
                    seen.add(key)
                    total += entry.row[kind + "_size"]
        return total

    def hydrate(
        self,
        positions: collections.abc.Sequence[int],
    ) -> peri_scribe.fires.sources.ReadFireSources:
        """Decode only selected occurrences with independent mutable attributes.

        Args:
            positions: Source occurrences in the caller's required order.

        Returns:
            Complete rows with a geometry registry owned by this hydration only.

        Raises:
            UnavailableError: If a selected cache payload or row fails authentication.
        """
        pool = spatial_data.geometry_pool.GeometryPool()
        decoded: dict[int, peri_scribe.geo.package.FireRowRecord] = {}
        by_connection: dict[int, list[int]] = collections.defaultdict(list)
        for position in positions:
            by_connection[self.entries[position].connection].append(position)
        try:
            with self.lock:
                for connection, indices in by_connection.items():
                    decoded.update(self.decode_rows(connection, indices, pool))
        except (ValueError, sqlite3.Error, shapely.errors.GEOSException) as error:
            message = "Bounded source hydration failed"
            raise UnavailableError(message) from error
        return peri_scribe.fires.sources.ReadFireSources(
            rows=tuple(decoded[index] for index in positions),
            paths=tuple(self.read.paths[index] for index in positions),
            memberships=(),
            source_paths=self.read.source_paths,
            geometry_keys=pool.geometry_keys,
        )

    def decode_rows(
        self,
        connection: int,
        indices: list[int],
        pool: spatial_data.geometry_pool.GeometryPool,
    ) -> dict[int, peri_scribe.geo.package.FireRowRecord]:
        """Resolve selected rows while the caller owns the catalog read lock.

        Args:
            connection: Pinned feed connection position.
            indices: Global source positions belonging to that connection.
            pool: Geometry sharing restricted to this detailed work item.

        Returns:
            Independently mutable complete rows by global source position.
        """
        rows = [self.entries[index].row for index in indices]
        payloads = peri_scribe.geo.dictionaries.decoded_payloads(
            self.connections[connection],
            rows,
            pool,
        )
        result = {}
        for index, row in zip(indices, rows, strict=True):
            geometry = row["geometry_id"]
            attributes = row["attributes_id"]
            result[index] = peri_scribe.geo.package.FireRowRecord.from_cached_row(
                row,
                None if geometry is None else payloads.geometries[geometry],
                payloads.attributes[attributes],
                None if geometry is None else payloads.geometry_fingerprints[geometry],
                payloads.attribute_fingerprints[attributes],
            )
        return result

    def records(
        self,
        positions: collections.abc.Sequence[int],
    ) -> list[peri_scribe.models.FireRecord]:
        """Hydrate geometry alone for exact within-block grouping.

        Args:
            positions: Source occurrences in their original order within a block.

        Returns:
            Record values with exact geometry and no full attribute documents.

        Raises:
            UnavailableError: If a geometry dictionary is damaged or incomplete.
        """
        result = {}
        pool = spatial_data.geometry_pool.GeometryPool()
        by_connection: dict[int, list[int]] = collections.defaultdict(list)
        for position in positions:
            by_connection[self.entries[position].connection].append(position)
        try:
            with self.lock:
                for connection, indices in by_connection.items():
                    identifiers = {
                        self.entries[index].row["geometry_id"] for index in indices
                    } - {None}
                    geometries = decode_geometries(
                        self.connections[connection],
                        identifiers,
                        pool,
                    )
                    for index in indices:
                        identifier = self.entries[index].row["geometry_id"]
                        result[index] = dataclasses.replace(
                            self.read.rows[index].record,
                            geometry=None
                            if identifier is None
                            else geometries[identifier],
                        )
        except (ValueError, sqlite3.Error, shapely.errors.GEOSException) as error:
            message = "Bounded grouping geometry failed"
            raise UnavailableError(message) from error
        return [result[index] for index in positions]

    def observations(self) -> list[peri_scribe.fires.complexes.MembershipObservation]:
        """Project ownership declarations while attribute documents remain transient.

        Returns:
            Complete row declarations and independent membership fallbacks.

        Raises:
            UnavailableError: If an attribute dictionary cannot be decoded.
        """
        declarations = {}
        references: dict[int, dict[int, list[int]]] = collections.defaultdict(
            lambda: collections.defaultdict(list),
        )
        for index, entry in enumerate(self.entries):
            references[entry.connection][entry.row["attributes_id"]].append(index)
        try:
            for connection, identifiers in references.items():
                declarations.update(self.row_declarations(connection, identifiers))
        except (ValueError, sqlite3.Error) as error:
            message = "Bounded ownership attributes failed"
            raise UnavailableError(message) from error
        return peri_scribe.fires.complexes.complete_observations(
            (declarations[index] for index in sorted(declarations)),
            self.read.memberships,
            self.read.membership_paths,
        )

    def row_declarations(
        self,
        connection: int,
        references: dict[int, list[int]],
    ) -> dict[
        int,
        tuple[
            peri_scribe.fires.complexes.MembershipObservation,
            frozenset[str],
            pathlib.Path,
        ],
    ]:
        """Retain only ownership evidence from each transient attribute document.

        Args:
            connection: Pinned feed reader position.
            references: Attribute IDs and their original source row positions.

        Returns:
            Normalized declarations indexed by original source occurrence.

        Raises:
            UnavailableError: If source attributes are not a JSON object.
        """
        result = {}
        for identifier, value in peri_scribe.geo.dictionaries.payload_values(
            self.connections[connection],
            peri_scribe.geo.database.PayloadKind.ATTRIBUTES,
            set(references),
        ):
            attributes = json.loads(value)
            if not isinstance(attributes, dict):
                message = "Source attributes require an object"
                raise UnavailableError(message)
            for index in references[identifier]:
                row = dataclasses.replace(self.read.rows[index], attributes=attributes)
                path = self.read.paths[index]
                observation = peri_scribe.fires.complexes.row_observation(row, path)
                if observation is not None:
                    result[index] = observation, row.record.identifiers, path
        return result


def decode_geometries(
    connection: sqlite3.Connection,
    identifiers: set[int],
    pool: spatial_data.geometry_pool.GeometryPool,
) -> dict[int, shapely.Geometry]:
    """Resolve exact geometry payloads while the caller retains its read lease.

    Args:
        connection: Pinned source feed transaction.
        identifiers: Required dictionary-local geometry references.
        pool: Geometry owner restricted to the current dependency block.

    Returns:
        Shared immutable geometries within this block only.
    """
    return {
        identifier: pool.from_wkb(typing.cast("bytes", value))
        for identifier, value in peri_scribe.geo.dictionaries.payload_values(
            connection,
            peri_scribe.geo.database.PayloadKind.GEOMETRY,
            identifiers,
        )
    }


def metadata_row(row: sqlite3.Row) -> peri_scribe.geo.package.FireRowRecord:
    """Authenticate compact fixed fields against their exact payload identities.

    Args:
        row: Pinned typed metadata and logical geometry/attribute digest references.

    Returns:
        A metadata-only row retaining no coordinate or attribute document.

    Raises:
        UnavailableError: If an anchor or payload identity cannot be authenticated.
    """
    if row["object_id"] is None:
        message = "Anonymous source anchors require complete preparation"
        raise UnavailableError(
            message,
        )
    for kind in ("geometry", "attributes"):
        if row[kind + "_id"] is not None:
            size = row[kind + "_size"]
            if type(size) is not int or size < 0:
                message = "Source payload size is invalid"
                raise UnavailableError(message)
    record = peri_scribe.geo.package.FireRowRecord.from_values(row, None, {})
    geometry = row["geometry_digest"]
    attributes = row["attributes_digest"]
    if not isinstance(attributes, bytes) or (
        row["geometry_id"] is not None and not isinstance(geometry, bytes)
    ):
        message = "Source metadata references missing payloads"
        raise UnavailableError(message)
    expected = peri_scribe.geo.fingerprints.fingerprint_from_payloads(
        record,
        None if geometry is None else geometry.hex(),
        attributes.hex(),
    )
    if expected != row["evidence_fingerprint"]:
        message = "Source metadata fingerprint does not match its payloads"
        raise UnavailableError(
            message,
        )
    return record


def load_metadata(
    connections: tuple[sqlite3.Connection, ...],
    files: list[pathlib.Path],
    checksums: tuple[tuple[pathlib.Path, str], ...],
    directory: pathlib.Path,
) -> Catalog:
    """Authenticate compact metadata and keep canonical occurrence order.

    Args:
        connections: Pinned feed readers in first-feed encounter order.
        files: Authoritative source paths in their original inventory order.
        checksums: Fresh complete source byte identities aligned with those paths.
        directory: Provenance root for all source occurrences.

    Returns:
        The complete compact catalog without decoded coordinate payloads.

    Raises:
        UnavailableError: If receipts or supported source identities disagree.
    """
    feeds = list(dict.fromkeys(path.parent.parent for path in files))
    source_rows = {}
    source_memberships = {}
    for connection, feed in zip(connections, feeds, strict=True):
        receipts = dict(connection.execute("SELECT serial, checksum FROM snapshots"))
        for path, checksum in checksums:
            if path.parent.parent == feed:
                serial = peri_scribe.sources.snapshots.SourceFile.from_path(
                    path,
                ).serial_number
                if receipts.get(serial) != checksum:
                    message = "Source receipt does not match authoritative bytes"
                    raise UnavailableError(
                        message,
                    )
        for row in connection.execute(
            "SELECT rows.*, geometry_payloads.digest AS geometry_digest, "
            "attribute_payloads.digest AS attributes_digest, "
            "geometry_payloads.original_size AS geometry_size, "
            "attribute_payloads.original_size AS attributes_size FROM rows "
            "LEFT JOIN geometry_payloads ON geometry_payloads.id = rows.geometry_id "
            "LEFT JOIN attribute_payloads "
            "ON attribute_payloads.id = rows.attributes_id "
            "ORDER BY rows.rowid",
        ):
            source_rows.setdefault((feed, row["serial"]), []).append(row)
        for row in connection.execute("SELECT * FROM memberships ORDER BY rowid"):
            source_memberships.setdefault((feed, row["serial"]), []).append(
                peri_scribe.models.ComplexMembership(
                    fire_identifier=row["fire_identifier"],
                    complex_identifier=row["complex_identifier"],
                    complex_name=row["complex_name"],
                    observation_time=peri_scribe.geo.parsing.observation_time_from(
                        row["observation_time"],
                    ),
                ),
            )
    entries = []
    rows = []
    paths = []
    memberships = []
    membership_paths = []
    for path in files:
        feed = path.parent.parent
        serial = peri_scribe.sources.snapshots.SourceFile.from_path(path).serial_number
        for row in source_rows.get((feed, serial), ()):
            record = metadata_row(row)
            entries.append(Entry(row=row, connection=feeds.index(feed)))
            rows.append(record)
            paths.append(path)
        selected = source_memberships.get((feed, serial), ())
        memberships.extend(selected)
        membership_paths.extend([path] * len(selected))
    return Catalog(
        directory=directory,
        connections=connections,
        entries=tuple(entries),
        read=peri_scribe.fires.sources.ReadFireSources(
            rows=tuple(rows),
            paths=tuple(paths),
            memberships=tuple(memberships),
            membership_paths=tuple(membership_paths),
            source_checksums=checksums,
            source_paths=peri_scribe.sources.provenance.SourcePaths(
                directory=directory,
            ),
        ),
    )


def pin_connections(
    stack: contextlib.ExitStack,
    files: list[pathlib.Path],
) -> tuple[sqlite3.Connection, ...]:
    """Synchronize and pin each feed before resolving metadata or payloads.

    Args:
        stack: Owner retaining every connection until workers settle.
        files: Valid retained snapshot paths in authoritative inventory order.

    Returns:
        Feed transactions ordered by their first source occurrence.
    """
    for path in files:
        peri_scribe.sources.snapshots.SourceFile.from_path(path)
    connections = []
    for feed in dict.fromkeys(path.parent.parent for path in files):
        database = peri_scribe.sources.snapshots.record_cache_database_path(
            feed,
        )
        with peri_scribe.geo.database.RECORD_CACHE_LOCK:
            peri_scribe.geo.database.ensure_database_current(database, feed)
        connection = sqlite3.connect(
            database.resolve().as_uri() + "?mode=ro",
            uri=True,
            check_same_thread=False,
        )
        stack.callback(connection.close)
        connection.row_factory = sqlite3.Row
        connection.execute("BEGIN")
        connections.append(connection)
    return tuple(connections)


@contextlib.contextmanager
def open_catalog(directory: pathlib.Path) -> collections.abc.Generator[Catalog]:
    """Pin feed snapshots until every worker has settled and source checks complete.

    Args:
        directory: The authoritative source root containing retained feed snapshots.

    Yields:
        A compact source catalog whose detailed reads have independent lifetimes.

    Raises:
        UnavailableError: If a complete supported cache catalog cannot be pinned.
    """
    files = peri_scribe.sources.snapshots.geo_package_files(directory)
    if not files:
        message = "No source snapshots for bounded preparation"
        raise UnavailableError(message)
    checksums = peri_scribe.fires.sources.snapshot_checksums(files)
    with contextlib.ExitStack() as stack:
        try:
            connections = pin_connections(stack, files)
            catalog = load_metadata(tuple(connections), files, checksums, directory)
        except (OSError, ValueError, sqlite3.Error) as error:
            message = "Bounded source catalog is unavailable"
            raise UnavailableError(message) from error
        try:
            yield catalog
            catalog.verify()
        finally:
            stack.close()
