"""Retain complete source-row identities without normalizing unchanged attributes.

Design notes:
[Authenticated parsed source cache](../../../docs/algorithms/parsed-source-cache.md).
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import typing

import shapely

import peri_scribe.geo.parsing
import peri_scribe.models


FINGERPRINT_VERSION = 1
NATIVE_JSON_SCALAR_TYPES = frozenset({str, int, float, bool, type(None)})


@dataclasses.dataclass(frozen=True, kw_only=True)
class FingerprintBasis:
    """Keep the attested inputs independent of each caller's mutable attributes.

    The source reader owns the template and never returns it as a row's attribute bag.
    Callers may mutate their own attributes; this basis is read-only retained evidence.
    """

    record: peri_scribe.models.FireRecord
    object_id: int | None
    source_name: str
    attributes: dict[str, object]


class SourceRow(typing.Protocol):
    """Describe complete row evidence without coupling the codec to this helper."""

    @property
    def record(self) -> peri_scribe.models.FireRecord:
        """Immutable identifying record fields."""
        ...

    @property
    def object_id(self) -> int | None:
        """The source object's identity when supplied."""
        ...

    @property
    def source_name(self) -> str:
        """The source feed's complete name."""
        ...

    @property
    def attributes(self) -> dict[str, object]:
        """Caller-owned mutable source attributes."""
        ...

    @property
    def evidence_fingerprint(self) -> str | None:
        """Validated cached evidence when available."""
        ...

    @property
    def evidence_basis(self) -> FingerprintBasis | None:
        """The independent attested input basis."""
        ...


def same_json_value(left: object, right: object) -> bool:
    """Compare native JSON values without conflating distinct scalar encodings.

    Python equality merges bools, integers, floats, and signed zeros. Their serialized
    evidence differs, so only equal types and equal float encodings can reuse a digest.

    Args:
        left: The row's current attribute value.
        right: Its independently owned decoded template value.

    Returns:
        Whether native JSON serialization distinguishes no part of these values.
    """
    value_type = type(left)
    if value_type is not type(right):
        return False
    if (
        left is right
        and type(value_type) is type
        and value_type in NATIVE_JSON_SCALAR_TYPES
    ):
        return True
    if isinstance(left, float) and isinstance(right, float):
        return left.hex() == right.hex()
    if isinstance(left, dict) and isinstance(right, dict):
        return same_json_mapping(left, right)
    if isinstance(left, list) and isinstance(right, list):
        return same_json_sequence(left, right)
    return isinstance(left, (str, bool, int, type(None))) and left == right


def same_json_mapping(left: dict[object, object], right: dict[object, object]) -> bool:
    """Visit current mapping contents while bypassing identical immutable children.

    Args:
        left: Current attributes with potentially invalid source keys.
        right: Independently retained mapping evidence of the same concrete type.

    Returns:
        Whether all keys and recursively compared values retain their evidence.
    """
    if not all(isinstance(key, str) for key in left) or left.keys() != right.keys():
        return False
    for key, value in left.items():
        other = right[key]
        value_type = type(value)
        if (
            value is other
            and type(value_type) is type
            and value_type in NATIVE_JSON_SCALAR_TYPES
        ):
            continue
        if not same_json_value(value, other):
            return False
    return True


def same_json_sequence(left: list[object], right: list[object]) -> bool:
    """Retain sequence ordering and strict custom iteration while comparing children.

    Args:
        left: Current mutable sequence.
        right: Independently retained sequence evidence of the same concrete type.

    Returns:
        Whether every ordered child retains its complete typed evidence.
    """
    if len(left) != len(right):
        return False
    if type(left) is not list:
        return all(map(same_json_value, left, right, strict=True))
    for value, other in zip(left, right, strict=True):
        value_type = type(value)
        if (
            value is other
            and type(value_type) is type
            and value_type in NATIVE_JSON_SCALAR_TYPES
        ):
            continue
        if not same_json_value(value, other):
            return False
    return True


def fingerprint_from_payloads(
    row: SourceRow,
    geometry_fingerprint: str | None,
    attributes_fingerprint: str,
) -> str:
    """Combine complete typed row metadata with authenticated payload identities.

    Args:
        row: Complete source evidence, including attributes reconciliation can discard.
        geometry_fingerprint: Exact geometry encoding identity, or None when absent.
        attributes_fingerprint: Canonical normalized attribute document identity.

    Returns:
        A versioned canonical row identity. Provenance paths are combined by consumers.
    """
    record = row.record
    fields = {
        field.name: getattr(record, field.name)
        for field in dataclasses.fields(record)
        if field.name not in {"geometry", "identifiers", "names"}
    }
    fields["observed_at"] = peri_scribe.geo.parsing.observation_time_from(
        record.observed_at,
    )
    document = {
        "version": FINGERPRINT_VERSION,
        "record": fields,
        "identifiers": sorted(record.identifiers),
        "names": sorted(record.names),
        "geometry": geometry_fingerprint,
        "attributes": attributes_fingerprint,
        "object_id": row.object_id,
        "source": row.source_name,
    }
    return hashlib.sha256(
        json.dumps(document, sort_keys=True, default=str).encode(),
    ).hexdigest()


def complete_row_fingerprint(row: SourceRow) -> str:
    """Compute complete row identity without relying on retained cache evidence.

    Args:
        row: Current source evidence with caller-owned mutable attributes.

    Returns:
        The versioned path-independent fingerprint of every current field.
    """
    attributes = {
        key: peri_scribe.geo.parsing.json_native_value(value)
        for key, value in row.attributes.items()
    }
    return fingerprint_from_payloads(
        row,
        None
        if row.record.geometry is None
        else hashlib.sha256(
            shapely.to_wkb(row.record.geometry, include_srid=True),
        ).hexdigest(),
        hashlib.sha256(json.dumps(attributes, sort_keys=True).encode()).hexdigest(),
    )


def row_evidence_fingerprint(row: SourceRow) -> str:
    """Reuse an attested row identity only while every borrowed input still matches.

    Args:
        row: A source row, possibly reconstructed from the normalized parsed cache.

    Returns:
        Its complete current fingerprint, recomputed after any changed borrowed input.
    """
    basis = row.evidence_basis
    if row.evidence_fingerprint is None or basis is None:
        return complete_row_fingerprint(row)
    if (
        row.record is basis.record
        and type(row.object_id) is type(basis.object_id)
        and row.object_id == basis.object_id
        and row.source_name == basis.source_name
        and same_json_value(row.attributes, basis.attributes)
    ):
        return row.evidence_fingerprint
    return complete_row_fingerprint(row)
