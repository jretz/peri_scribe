"""Retain source-group identities independently of names and external identifiers.

[Grouping and ownership](../../../docs/algorithms/fire-grouping-and-ownership.md)
"""

from __future__ import annotations

import collections
import hashlib
import json
import pathlib
import typing

import peri_scribe.geo.package
import peri_scribe.geo.parsing
import peri_scribe.sources.snapshots


type Anchor = tuple[str, int, str, str, int]


def row_token(row: peri_scribe.geo.package.FireRowRecord) -> str:
    """Recognize immutable source rows even when the feed supplies no object ID.

    Args:
        row: A decoded row from a retained source snapshot.

    Returns:
        Canonical structured identity within its source file.
    """
    if row.object_id is not None:
        value: object = ("object", row.object_id)
    else:
        record = row.record
        value = (
            "record",
            record.name,
            record.status.value,
            sorted(record.identifiers),
            sorted(record.names),
            record.geometry.wkb_hex if record.geometry is not None else None,
            record.observed_at.isoformat() if record.observed_at is not None else None,
            record.mission,
            record.point_of_origin_state,
            record.point_of_origin_fips,
            {
                key: peri_scribe.geo.parsing.json_native_value(value)
                for key, value in row.attributes.items()
            },
        )
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def anchors(
    rows: typing.Sequence[peri_scribe.geo.package.FireRowRecord],
    paths: typing.Sequence[pathlib.Path],
) -> tuple[Anchor, ...]:
    """Identify source row occurrences without depending on the data directory's path.

    An object ID is unique within a validated feed snapshot, so the feed name and
    immutable snapshot filename establish where it belongs. Serial numbers are compared
    numerically to preserve chronology regardless of filename padding.

    Exact duplicate rows without geometry can remain separate components. Occurrence
    numbers keep their keys distinct and preserve the set of keys, without assigning
    meaning to otherwise indistinguishable copies.

    Args:
        rows: Source rows aligned with their retained snapshot files.
        paths: Paths whose filenames encode immutable snapshot serials and timestamps.

    Returns:
        Ordered structured row occurrences, before hashing their selected minima.
    """
    counts: collections.Counter[tuple[str, int, str, str]] = collections.Counter()
    result: list[Anchor] = []
    for row, path in zip(rows, paths, strict=True):
        try:
            serial = peri_scribe.sources.snapshots.SourceFile.from_path(
                path,
            ).serial_number
        except ValueError:
            serial = -1
        key = row.source_name, serial, path.name, row_token(row)
        result.append((*key, counts[key]))
        counts[key] += 1
    return tuple(result)


def component_id(rows: typing.Iterable[Anchor]) -> str:
    """Use a component's least source anchor to determine its internal key.

    A merge retains the least anchor. After a split, only the part containing that
    anchor keeps the key. New snapshots in the same source sort after earlier serials,
    but acquiring an earlier source anchor can change the key. For that reason, durable
    history inheritance relies on separately retained identifiers and mapping evidence.

    Args:
        rows: The nonempty component's immutable source-row occurrences.

    Returns:
        An opaque internal digest, separate from source-issued identifiers.
    """
    return hashlib.sha256(json.dumps(min(rows)).encode()).hexdigest()
