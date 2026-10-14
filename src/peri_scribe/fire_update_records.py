"""Shared identity and payload schemas for durable journals and public snapshots.

Algorithm reasoning and contracts:
[Update journal](../../docs/algorithms/update-journal.md)
"""

import json
import typing

import pydantic

from measurement_units import units


if typing.TYPE_CHECKING:
    import pint


type HistoryIdentity = tuple[typing.Literal["id", "name", "local", "component"], str]
IDENTITY = pydantic.TypeAdapter(HistoryIdentity)


def canonical_identity(value: str) -> str:
    """Require one JSON spelling for each history identity.

    Equivalent identities with different encoded strings would become different keys,
    allowing the same history to be assigned to conflicting owners.

    Args:
        value: A persisted identity key or target in a durable checkpoint.

    Returns:
        The unchanged canonical JSON identity pair.

    Raises:
        ValueError: The kind, payload, or exact JSON representation is invalid.
    """
    identity = IDENTITY.validate_json(value)
    if json.dumps(identity) != value:
        message = "History identity must use canonical JSON encoding"
        raise ValueError(message)
    return value


type EncodedIdentity = typing.Annotated[
    str,
    pydantic.AfterValidator(canonical_identity),
]


class Acreage(pydantic.BaseModel):
    """Require finite, nonnegative acres before a journal update can be acknowledged."""

    model_config = pydantic.ConfigDict(
        frozen=True,
        extra="forbid",
        revalidate_instances="always",
    )
    value: float = pydantic.Field(ge=0, allow_inf_nan=False)
    units: typing.Literal["acre"] = "acre"

    def quantity(self) -> pint.Quantity:
        """Keep comparisons with previous mapping unit-aware.

        Returns:
            The measured acreage as a quantity.
        """
        return self.value * units.acres


class Record(pydantic.BaseModel):
    """Use the same validated fields for pending journal entries and published logs."""

    model_config = pydantic.ConfigDict(
        frozen=True,
        extra="forbid",
        revalidate_instances="always",
    )
    identifier: str | None
    name: str
    location: str | None
    mapped_area: Acreage
    log_identity: HistoryIdentity | None = None


def validated_records(
    records: tuple[dict[str, object], ...],
) -> tuple[dict[str, object], ...]:
    """Validate every record before any part of the batch can be appended to the log.

    Args:
        records: Raw journal payloads without the journal's shared completion metadata.

    Returns:
        Validated JSON-compatible payloads in their original occurrence order.
    """
    return tuple(
        Record.model_validate(record).model_dump(mode="json", exclude_unset=True)
        for record in records
    )


type Records = typing.Annotated[
    tuple[dict[str, object], ...],
    pydantic.AfterValidator(validated_records),
]
