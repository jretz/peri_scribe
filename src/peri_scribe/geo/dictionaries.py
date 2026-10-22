"""Decode exact parsed-cache payloads once for each authenticated feed transaction.

Design notes:
[Authenticated parsed source cache](../../../docs/algorithms/parsed-source-cache.md).
"""

from __future__ import annotations

import collections.abc
import dataclasses
import hashlib
import json
import sqlite3
import typing

import peri_scribe.geo.attribute_strings
import peri_scribe.geo.database
import peri_scribe.geo.payload_storage


if typing.TYPE_CHECKING:
    import shapely

    import spatial_data.geometry_pool


PAYLOAD_BATCH_SIZE = 500


@dataclasses.dataclass(frozen=True, kw_only=True)
class DecodedPayloads:
    """Keep shared immutable geometry and reader-owned attribute templates together."""

    geometries: dict[int, shapely.Geometry]
    geometry_fingerprints: dict[int, str]
    attributes: dict[int, dict[str, object]]
    attribute_fingerprints: dict[int, str]


def payload_values(
    conn: sqlite3.Connection,
    kind: peri_scribe.geo.database.PayloadKind,
    identifiers: set[int],
) -> collections.abc.Iterator[tuple[int, bytes | str]]:
    """Read requested encodings in bounded queries without retaining duplicate BLOBs.

    Args:
        conn: The same read transaction that authenticated rows and receipts.
        kind: The exact payload dictionary being consumed.
        identifiers: Dictionary-local references required by accepted row occurrences.

    Yields:
        Each complete encoding once, after checking its stored digest candidate.

    Raises:
        ValueError: If a referenced encoding is absent or has damaged content metadata.
    """
    dictionaries = peri_scribe.geo.payload_storage.dictionaries(conn)
    dictionary_column = (
        "dictionary_id"
        if kind is peri_scribe.geo.database.PayloadKind.ATTRIBUTES
        else "NULL AS dictionary_id"
    )
    found: set[int] = set()
    ordered = sorted(identifiers)
    for position in range(0, len(ordered), PAYLOAD_BATCH_SIZE):
        batch = ordered[position : position + PAYLOAD_BATCH_SIZE]
        placeholders = ",".join("?" for _ in batch)
        for row in conn.execute(
            f"SELECT id, digest, value, encoding, original_size, {dictionary_column} "
            f"FROM {kind.value} "
            f"WHERE id IN ({placeholders}) ORDER BY id",
            batch,
        ):
            value = peri_scribe.geo.payload_storage.decode(
                row["value"],
                row["encoding"],
                row["original_size"],
                dictionary=dictionaries.get(row["dictionary_id"]),
                text=kind is peri_scribe.geo.database.PayloadKind.ATTRIBUTES,
            )
            if peri_scribe.geo.database.payload_digest(value) != row["digest"]:
                message = "Parsed dictionary payload does not match its stored digest"
                raise ValueError(message)
            found.add(row["id"])
            yield row["id"], value
    if found != identifiers:
        message = "Parsed rows reference missing dictionary payloads"
        raise ValueError(message)


def decoded_payloads(
    conn: sqlite3.Connection,
    rows: collections.abc.Sequence[sqlite3.Row],
    geometry_pool: spatial_data.geometry_pool.GeometryPool,
) -> DecodedPayloads:
    """Decode each referenced geometry and attribute document once for this feed read.

    Args:
        conn: The authenticated snapshot transaction owning every dictionary lookup.
        rows: Accepted typed row occurrences without their large payloads.
        geometry_pool: Shared geometries across feeds in the complete source read.

    Returns:
        Exact decoded payloads and their reusable canonical fingerprints.

    Raises:
        ValueError: If an attribute encoding is not a complete JSON object.
    """
    geometry_identifiers = {
        row["geometry_id"] for row in rows if row["geometry_id"] is not None
    }
    attribute_identifiers = {row["attributes_id"] for row in rows}
    geometries: dict[int, shapely.Geometry] = {}
    geometry_fingerprints: dict[int, str] = {}
    for identifier, value in payload_values(
        conn,
        peri_scribe.geo.database.PayloadKind.GEOMETRY,
        geometry_identifiers,
    ):
        encoded = typing.cast("bytes", value)
        geometries[identifier] = geometry_pool.from_wkb(encoded)
        geometry_fingerprints[identifier] = hashlib.sha256(encoded).hexdigest()
    attributes: dict[int, dict[str, object]] = {}
    attribute_fingerprints: dict[int, str] = {}
    strings = peri_scribe.geo.attribute_strings.AttributeStrings()
    for identifier, value in payload_values(
        conn,
        peri_scribe.geo.database.PayloadKind.ATTRIBUTES,
        attribute_identifiers,
    ):
        encoded = typing.cast("str", value)
        if encoded.lstrip()[:1] != "{":
            message = "Parsed attributes must be a complete JSON object"
            raise ValueError(message)
        document = json.loads(encoded, object_pairs_hook=strings.mapping)
        attributes[identifier] = document
        attribute_fingerprints[identifier] = hashlib.sha256(
            encoded.encode(),
        ).hexdigest()
    return DecodedPayloads(
        geometries=geometries,
        geometry_fingerprints=geometry_fingerprints,
        attributes=attributes,
        attribute_fingerprints=attribute_fingerprints,
    )
