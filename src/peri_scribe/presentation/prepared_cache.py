"""Validate persistent fire facts independently from rendering and current scores.

Design notes:
[Product caching](../../../docs/algorithms/product-caching.md).
"""

from __future__ import annotations

import dataclasses
import functools

import pint
import pydantic

import peri_scribe.areas
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
    """Borrow scalar leaves while synchronous encoding reads caller-owned evidence.

    The codec consumes this temporary tree without retaining or mutating its leaves.
    Callers must keep the completed evidence unchanged until encoding finishes.

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


def read_history(payload: bytes) -> peri_scribe.areas.PreparedHistory:
    """Reject incomplete or coerced evidence rather than alter a cached publication.

    Args:
        payload: Previously serialized deterministic fire evidence.

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
