"""Read source-declared polygon versions without loading or comparing coordinates."""

from __future__ import annotations

import collections.abc
import contextlib
import dataclasses
import datetime
import json
import pathlib
import sqlite3

import peri_scribe.geo.parsing
import peri_scribe.models
import peri_scribe.show_latencies.runs
import peri_scribe.sources.feed_types
import peri_scribe.sources.feeds
import peri_scribe.sources.snapshots
from measurement_units import units


GEOPACKAGE_HEADER_LENGTH = 4


@dataclasses.dataclass(frozen=True, kw_only=True)
class Publication:
    """A source polygon version's first estimated availability for its fire."""

    identifier: str
    source_file: str
    published: datetime.datetime


@dataclasses.dataclass(frozen=True, kw_only=True)
class Version:
    """Source records and polygon dates distinguish mapping from incident edits."""

    object_id: int | str
    surveyed: datetime.datetime | None
    created: datetime.datetime | None


@dataclasses.dataclass(frozen=True, kw_only=True)
class FireIdentities:
    """Distinct index entries keep same-named fires separate without spatial work."""

    aliases: dict[str, str] = dataclasses.field(default_factory=dict)
    names_by_path: dict[str, dict[str, str | None]] = dataclasses.field(
        default_factory=dict,
    )


def quoted_identifier(name: str) -> str:
    """Quote metadata column names without treating them as SQL expressions.

    Args:
        name: A table or column name from feed configuration or GeoPackage metadata.

    Returns:
        An escaped SQLite identifier.
    """
    return '"' + name.replace('"', '""') + '"'


def fire_identities(directory: pathlib.Path) -> FireIdentities:
    """Reuse canonical fire grouping while allowing newly collected unmatched fires.

    Args:
        directory: The year's retained sources directory.

    Returns:
        Source aliases and unambiguous path/name associations for canonical fires.
    """
    path = directory / "fires.json"
    result = FireIdentities()
    if not path.is_file():
        return result
    for index, entry in enumerate(json.loads(path.read_text())["fires"]):
        name = peri_scribe.models.normalize_fire_name(entry["name"])
        identifier = (
            peri_scribe.geo.parsing.normalize_identifier(
                entry.get("identifier"),
            )
            or f"indexed:{index}:{name}"
        )
        for value in (*entry.get("aliases", []), identifier):
            if (
                alias := peri_scribe.geo.parsing.normalize_identifier(value)
            ) is not None:
                result.aliases[alias] = identifier
        for relative in entry.get("paths", []):
            names = result.names_by_path.setdefault(relative, {})
            if name not in names:
                names[name] = identifier
            elif names[name] != identifier:
                names[name] = None
    return result


def fire_identifier(
    row: sqlite3.Row,
    aliases: dict[str, str],
    feed_name: str,
    indexed_names: dict[str, str | None],
) -> str:
    """Keep raw source identities when a new fire has not reached the derived index.

    Args:
        row: Source identity and name metadata for one polygon record.
        aliases: Canonical fire identities from the retained source index.
        feed_name: The source namespace for otherwise unidentified polygon records.
        indexed_names: Path-scoped name associations; None marks an ambiguous match.

    Returns:
        A canonical identifier, normalized name, or stable source-record fallback.
    """
    identifiers = tuple(
        identifier
        for column in ("identifier", "alternate_identifier")
        if (identifier := peri_scribe.geo.parsing.normalize_identifier(row[column]))
        is not None
    )
    for identifier in identifiers:
        if identifier in aliases:
            return aliases[identifier]
    canonical = peri_scribe.models.canonical_fire_identifier(identifiers)
    if canonical is not None:
        return canonical
    name = peri_scribe.geo.parsing.fire_name_from(row["name"])
    if name is None:
        mission = peri_scribe.geo.parsing.mission_name_from(row["mission"])
        name = mission.name if mission is not None else None
    if name is not None:
        normalized = peri_scribe.models.normalize_fire_name(name)
        if normalized not in indexed_names:
            return "name:" + normalized
        if (indexed := indexed_names[normalized]) is not None:
            return indexed
    return f"record:{feed_name}#{row['object_id']}"


def selected_columns(
    columns: set[str],
    feed: peri_scribe.sources.feed_types.Feed,
) -> str:
    """Read only fields that establish a fire identity or a declared polygon version.

    Args:
        columns: Attribute names present in the authoritative snapshot.
        feed: The perimeter source's configured identity columns.

    Returns:
        The SQL projection, with absent optional metadata represented by NULL.
    """
    identities = (*feed.fire_identifier_columns, None, None)
    requested = {
        "object_id": peri_scribe.models.OBJECT_ID_COLUMN_NAME,
        "identifier": identities[0],
        "alternate_identifier": identities[1],
        "name": feed.fire_name_column,
        "mission": feed.mission_column,
        "surveyed": feed.observation_time_column,
        "created": "poly_CreateDate",
    }
    return ", ".join(
        f"{quoted_identifier(column) if column in columns else 'NULL'} "
        f"AS {quoted_identifier(alias)}"
        for alias, column in requested.items()
    )


def snapshot_versions(
    path: pathlib.Path,
    feed: peri_scribe.sources.feed_types.Feed,
    aliases: dict[str, str],
    indexed_names: dict[str, str | None] | None = None,
) -> collections.abc.Iterator[tuple[Version, str]]:
    """Use polygon-layer metadata and four header bytes without reading coordinates.

    Args:
        path: The authoritative GeoPackage snapshot.
        feed: The perimeter source defining the layer and metadata columns.
        aliases: Canonical fire identities from the retained source index.
        indexed_names: Name associations restricted to this exact source snapshot.

    Yields:
        Each nonempty polygon's source-declared version and fire identifier.
    """
    with contextlib.closing(
        sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True),
    ) as connection:
        connection.row_factory = sqlite3.Row
        geometry = connection.execute(
            "SELECT column_name, geometry_type_name FROM gpkg_geometry_columns "
            "WHERE table_name = ?",
            (feed.name,),
        ).fetchone()
        if geometry is None or geometry["geometry_type_name"] not in {
            "POLYGON",
            "MULTIPOLYGON",
        }:
            return
        table = quoted_identifier(feed.name)
        columns = {
            row["name"] for row in connection.execute(f"PRAGMA table_info({table})")
        }
        geometry_column = quoted_identifier(geometry["column_name"])
        query = (
            f"SELECT {selected_columns(columns, feed)}, "
            f"rowid AS source_rowid FROM {table} "
            f"WHERE {geometry_column} IS NOT NULL"
        )
        for row in connection.execute(query):
            with connection.blobopen(
                feed.name,
                geometry["column_name"],
                row["source_rowid"],
                readonly=True,
            ) as blob:
                header = blob.read(GEOPACKAGE_HEADER_LENGTH)
            if (
                len(header) < GEOPACKAGE_HEADER_LENGTH
                or header[:2] != b"GP"
                or header[3] & 0x10
            ):
                continue
            identifier = fire_identifier(row, aliases, feed.name, indexed_names or {})
            yield (
                Version(
                    object_id=row["object_id"]
                    if row["object_id"] is not None
                    else identifier,
                    surveyed=peri_scribe.geo.parsing.observation_time_from(
                        row["surveyed"],
                    ),
                    created=peri_scribe.geo.parsing.observation_time_from(
                        row["created"],
                    ),
                ),
                identifier,
            )


def read_versions(
    year_directory: pathlib.Path,
    window: peri_scribe.show_latencies.runs.Window,
) -> tuple[Publication, ...]:
    """Find each new polygon version's earliest retained source publication.

    Earlier snapshots establish a metadata baseline. Polygon survey and creation dates
    identify changes to existing source objects; incident-only fields never advance a
    version. An object with no polygon dates counts once when it first appears.

    Args:
        year_directory: The pipeline's retained year directory.
        window: Inclusive bounds for estimated source publication.

    Returns:
        New polygon versions whose first source publication is in the window.
    """
    directory = year_directory / "sources"
    identities = fire_identities(directory)
    result = []
    for feed in (
        peri_scribe.sources.feeds.CA_PERIMETERS_FEED,
        peri_scribe.sources.feeds.WFIGS_PERIMETERS_FEED,
    ):
        seen: set[Version] = set()
        snapshots = sorted(
            peri_scribe.sources.snapshots.existing_source_files(directory / feed.name),
            key=lambda source: (source.last_edit_timestamp, source.serial_number),
        )
        for source in snapshots:
            published = datetime.datetime.fromtimestamp(
                (source.last_edit_timestamp * units.milliseconds).m_as("seconds"),
                tz=datetime.UTC,
            )
            if published > window.end:
                break
            path = directory / feed.name / source.relative_path
            relative = str(path.relative_to(directory))
            for version, identifier in snapshot_versions(
                path,
                feed,
                identities.aliases,
                identities.names_by_path.get(relative),
            ):
                if version in seen:
                    continue
                seen.add(version)
                if published >= window.start:
                    result.append(
                        Publication(
                            identifier=identifier,
                            source_file=relative,
                            published=published,
                        ),
                    )
    return tuple(result)
