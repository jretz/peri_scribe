"""Validate persistent fire facts independently from rendering and current scores.

Design notes:
[Product caching](../../../docs/algorithms/product-caching.md).
"""

from __future__ import annotations

import dataclasses
import functools
import hashlib

import pint
import pydantic

import peri_scribe.areas
import peri_scribe.execution
import peri_scribe.presentation.descriptions
import spatial_data.cache_values


class HistoryDocument(pydantic.BaseModel):
    """Validate every field before stored evidence reenters the publication pipeline."""

    model_config = pydantic.ConfigDict(arbitrary_types_allowed=True, extra="forbid")
    history: peri_scribe.areas.PreparedHistory


class DescriptionDocument(pydantic.BaseModel):
    """Constrain stored descriptions to the application's declared facts."""

    model_config = pydantic.ConfigDict(arbitrary_types_allowed=True, extra="forbid")
    description: peri_scribe.presentation.descriptions.FireDescription


HistoryDocument.model_rebuild(_types_namespace={"pint": pint})
DescriptionDocument.model_rebuild(_types_namespace={"pint": pint})


@dataclasses.dataclass(frozen=True, kw_only=True)
class RecordReference:
    """Check every record field before reusing its completed evidence identity."""

    record: object
    values: tuple[object, ...]


@dataclasses.dataclass(frozen=True, kw_only=True)
class EncodedValue:
    """Keep mutable and foreign scalar evidence detached from the current value."""

    value: object
    payload: bytes


type HistoryGuard = RecordReference | EncodedValue


@dataclasses.dataclass(frozen=True, kw_only=True)
class HistoryIdentity:
    """Bind a complete payload digest to its current history and mutation guards."""

    history: peri_scribe.areas.PreparedHistory
    digest: bytes
    guards: tuple[HistoryGuard, ...]


def document_digest(document: pydantic.BaseModel) -> bytes:
    """Keep exact current model identity compact in an execution-cache key.

    Serializing the current fields on every lookup detects changes in nested mutable
    lists and mappings. Only the digest remains retained for the execution's lifetime.

    Args:
        document: The current complete index or score document.

    Returns:
        Its SHA-256 identity under the application's collision-resistance assumption.
    """
    return hashlib.sha256(document.model_dump_json().encode()).digest()


@functools.cache
def record_field_names(record_type: type) -> tuple[str, ...]:
    """Keep every declared field, including fields inherited or added by subclasses.

    Args:
        record_type: A dataclass type used in completed fire evidence.

    Returns:
        Its fields in declaration order.

    Raises:
        TypeError: When the type does not declare dataclass fields.
    """
    if not dataclasses.is_dataclass(record_type):
        message = "Completed fire evidence requires dataclass fields"
        raise TypeError(message)
    return tuple(field.name for field in dataclasses.fields(record_type))


def record_values(value: object) -> object:
    """Share scalar values while encoding the caller's completed evidence.

    The codec reads this temporary tree synchronously and neither retains nor changes
    its scalar values. Callers must keep the evidence unchanged until encoding finishes.

    Args:
        value: A dataclass, supported container, or scalar in completed fire evidence.

    Returns:
        Ordered dictionaries for records, independent containers, and borrowed scalars.
    """
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            name: record_values(getattr(value, name))
            for name in record_field_names(type(value))
        }
    if isinstance(value, tuple):
        return tuple(record_values(item) for item in value)
    if isinstance(value, list):
        return [record_values(item) for item in value]
    if isinstance(value, dict):
        return {record_values(key): record_values(item) for key, item in value.items()}
    return value


def history_bytes(history: peri_scribe.areas.PreparedHistory) -> bytes:
    """Preserve source units, reconciled updates, and exact area-selection times.

    Args:
        history: Completed deterministic evidence for one fire.

    Returns:
        A typed cache payload.
    """
    return spatial_data.cache_values.dumps(record_values(history))


def history_guards(value: object) -> tuple[HistoryGuard, ...]:
    """Check record references and batch children that can change in place.

    Builtin scalar values cannot mutate, and exact tuples retain their children.
    Record fields are checked by identity even for frozen dataclasses so replacing a
    child invalidates the retained digest. Mutable containers and foreign scalars form
    one ordered tuple under the existing codec, preserving types, bits and units.

    Args:
        value: Current prepared evidence, including possible dataclass extensions.

    Returns:
        Reference checks and one encoding covering all mutable or foreign children.
    """
    records: list[HistoryGuard] = []
    children: list[object] = []
    collect_history_guards(value, records, children)
    if children:
        values = tuple(children)
        records.append(
            EncodedValue(
                value=values,
                payload=spatial_data.cache_values.dumps(record_values(values)),
            ),
        )
    return tuple(records)


def collect_history_guards(
    value: object,
    records: list[HistoryGuard],
    children: list[object],
) -> None:
    """Collect field references and ordered leaves for one history identity.

    Args:
        value: One child in the complete current evidence.
        records: Field-reference guards accumulated in traversal order.
        children: Mutable containers and foreign scalars accumulated in the same order.
    """
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        values = tuple(getattr(value, name) for name in record_field_names(type(value)))
        records.append(RecordReference(record=value, values=values))
        for child in values:
            collect_history_guards(child, records, children)
    elif type(value) is tuple:
        for child in value:
            collect_history_guards(child, records, children)
    elif not any(
        type(value) is scalar for scalar in (type(None), bool, int, float, str, bytes)
    ):
        children.append(value)


def remember_history(
    history: peri_scribe.areas.PreparedHistory,
    payload: bytes,
) -> bytes:
    """Retain a current canonical payload identity within the owning execution.

    Callers supply bytes just produced from the same unchanged history, or accepted by
    canonical decoding and domain validation. The execution retains the exact history
    object to prevent object-identifier reuse; detached guards detect later mutations.

    Args:
        history: The completed evidence represented by the payload.
        payload: Its complete current canonical typed representation.

    Returns:
        The payload's SHA-256 identity.
    """
    digest = hashlib.sha256(payload).digest()
    if peri_scribe.execution.active():
        peri_scribe.execution.put(
            peri_scribe.execution.Group.HISTORIES,
            ("prepared_history_identity", id(history)),
            HistoryIdentity(
                history=history,
                digest=digest,
                guards=history_guards(history),
            ),
        )
    return digest


def history_digest(history: peri_scribe.areas.PreparedHistory) -> bytes:
    """Reuse complete history identity only while all retained evidence still matches.

    Args:
        history: Current prepared evidence, whether computed or decoded from storage.

    Returns:
        The same digest as hashing its complete current canonical history payload.
    """
    identity = peri_scribe.execution.get(
        peri_scribe.execution.Group.HISTORIES,
        ("prepared_history_identity", id(history)),
    )
    if (
        isinstance(identity, HistoryIdentity)
        and identity.history is history
        and all(history_guard_matches(guard) for guard in identity.guards)
    ):
        return identity.digest
    return remember_history(history, history_bytes(history))


def history_guard_matches(guard: HistoryGuard) -> bool:
    """Require reference preservation or exact current encoded child bytes.

    Args:
        guard: An independent check captured with a complete history payload.

    Returns:
        Whether that part of the history retains its original serialization.
    """
    if isinstance(guard, RecordReference):
        return all(
            getattr(guard.record, name) is value
            for name, value in zip(
                record_field_names(type(guard.record)),
                guard.values,
                strict=True,
            )
        )
    return spatial_data.cache_values.dumps(record_values(guard.value)) == guard.payload


def read_history(
    payload: bytes,
    *,
    remember_identity: bool = True,
) -> peri_scribe.areas.PreparedHistory:
    """Reject incomplete or coerced evidence rather than alter a cached publication.

    Args:
        payload: Previously serialized deterministic fire evidence.
        remember_identity: Retain mutation guards for subsequent digest lookups.
            Callers can defer this memory cost until the history is actually used.

    Returns:
        The fully validated history.

    Raises:
        ValueError: When the stored evidence is malformed or changes during validation.
    """
    value = spatial_data.cache_values.loads(
        payload,
        enums=(peri_scribe.areas.AreaSource,),
    )
    history = HistoryDocument.model_validate({"history": value}).history
    if history_bytes(history) != payload:
        message = "Stored history fields changed during validation"
        raise ValueError(message)
    if remember_identity:
        remember_history(history, payload)
    return history


def description_bytes(
    description: peri_scribe.presentation.descriptions.FireDescription,
) -> bytes:
    """Keep stable descriptive facts independent from the current score explanation.

    Args:
        description: A fire description with no score-dependent note.

    Returns:
        A typed cache payload.
    """
    return spatial_data.cache_values.dumps(record_values(description))


def read_description(
    payload: bytes,
) -> peri_scribe.presentation.descriptions.FireDescription:
    """Validate stored facts without accepting missing or coerced fields.

    Args:
        payload: Previously serialized stable descriptive facts.

    Returns:
        The fully validated fire description.

    Raises:
        ValueError: When stored facts are malformed or change during validation.
    """
    value = spatial_data.cache_values.loads(payload)
    description = DescriptionDocument.model_validate({"description": value}).description
    if description_bytes(description) != payload:
        message = "Stored description fields changed during validation"
        raise ValueError(message)
    return description
