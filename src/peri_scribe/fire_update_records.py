"""Shared identity and payload schemas for durable journals and public snapshots.

Algorithm reasoning and contracts:
[Update journal](../../docs/algorithms/update-journal.md)
"""

import collections.abc
import functools
import importlib
import json
import typing

import pydantic


if typing.TYPE_CHECKING:
    import pint


type HistoryIdentity = tuple[typing.Literal["id", "name", "local", "component"], str]
IDENTITY = pydantic.TypeAdapter(HistoryIdentity)
MAXIMUM_CACHED_IDENTITY_LENGTH = 512
type Preview = typing.Annotated[
    str,
    pydantic.StringConstraints(
        pattern=r"^data:image/webp;base64,[A-Za-z0-9+/]+={0,2}$",
    ),
]


def validate_identity_encoding(value: str) -> None:
    """Require a single JSON spelling so each identity names one durable history.

    Args:
        value: A persisted identity key or target in a durable checkpoint.

    Raises:
        ValueError: The kind, payload, or exact JSON representation is invalid.
    """
    identity = IDENTITY.validate_json(value)
    if json.dumps(identity) != value:
        message = "History identity must use canonical JSON encoding"
        raise ValueError(message)


def identity_encoding_validator() -> collections.abc.Callable[[str], str]:
    """Keep the cache behind the size check that bounds retained text.

    Returns:
        A checkpoint identity validator with its own bounded cache.
    """
    validate = validate_identity_encoding
    cached = functools.lru_cache(maxsize=4096)(validate)

    def canonical_identity(value: str) -> str:
        """Reuse validation for short keys repeated across checkpoint fields.

        Invalid encodings propagate the validator's error.

        Args:
            value: A persisted identity key or target in a durable checkpoint.

        Returns:
            The unchanged canonical JSON identity pair.
        """
        if type(value) is str and len(value) <= MAXIMUM_CACHED_IDENTITY_LENGTH:
            cached(value)
        else:
            validate(value)
        return value

    return canonical_identity


canonical_identity = identity_encoding_validator()


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
        units = importlib.import_module("measurement_units").units
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
    preview: Preview | None = None


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
