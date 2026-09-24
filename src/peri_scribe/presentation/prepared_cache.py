"""Validate persistent fire facts independently from rendering and current scores."""

from __future__ import annotations

import dataclasses

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


def history_bytes(history: peri_scribe.areas.PreparedHistory) -> bytes:
    """Preserve source units, reconciled updates, and exact area-selection times.

    Args:
        history: Completed deterministic evidence for one fire.

    Returns:
        A typed cache payload.
    """
    return spatial_data.cache_values.dumps(dataclasses.asdict(history))


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
    return spatial_data.cache_values.dumps(dataclasses.asdict(description))


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
