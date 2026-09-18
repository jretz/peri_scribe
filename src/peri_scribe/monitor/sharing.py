"""Bounded pools share immutable log metadata without aliasing mutable records."""

import collections.abc
import dataclasses
import functools
import json
import types
import typing


if typing.TYPE_CHECKING:
    import peri_scribe.phases

MAXIMUM_TEXT_LENGTH = 128
MAXIMUM_PHASE_TEXT_LENGTH = 4096


@functools.lru_cache(maxsize=4096)
def text(value: str) -> str:
    """Reuse frequently repeated field names and short values.

    Args:
        value: One small piece of log metadata.

    Returns:
        An equal string shared with other recently decoded records.
    """
    return value


def compact(value: object) -> object:
    """Keep mutable JSON containers independent while sharing their text.

    Args:
        value: A decoded JSON value.

    Returns:
        The same JSON value with repeated strings pooled.
    """
    if isinstance(value, str) and len(value) < MAXIMUM_TEXT_LENGTH:
        return text(value)
    if isinstance(value, list):
        return [compact(item) for item in value]
    return value


def fields(value: dict[str, object]) -> dict[str, object]:
    """Compact every JSON object as it is decoded, including nested metadata.

    Args:
        value: A decoded object's fields.

    Returns:
        An independent dictionary with shared immutable text.
    """
    return {text(key): compact(item) for key, item in value.items()}


@functools.lru_cache(maxsize=512)
def path(value: peri_scribe.phases.Path) -> peri_scribe.phases.Path:
    """Reuse immutable paths for repeated observations of the same phase instance.

    Args:
        value: A fully resolved execution scope.

    Returns:
        An equal path from a bounded pool of recent scopes.
    """
    return value


@dataclasses.dataclass(frozen=True, kw_only=True, slots=True, eq=False)
class Record(collections.abc.Mapping[str, object]):
    """Repeated phase metadata stays compact until raw fields are inspected."""

    encoded_fields: collections.abc.Mapping[str, object]

    def __getitem__(self, key: str) -> object:
        """Return independent JSON containers when raw phase metadata is requested.

        Args:
            key: The original field name.

        Returns:
            Its original JSON value.
        """
        value = self.encoded_fields[key]
        return (
            json.loads(typing.cast("str", value)) if key == "phase_segments" else value
        )

    def __iter__(self) -> collections.abc.Iterator[str]:
        """Preserve original field order for detailed record inspection.

        Returns:
            An iterator over the recorded field names.
        """
        return iter(self.encoded_fields)

    def __len__(self) -> int:
        """Preserve the complete record's field count.

        Returns:
            The number of original fields.
        """
        return len(self.encoded_fields)


@functools.lru_cache(maxsize=512)
def encoded(value: str) -> str:
    """Share bounded serialized phase metadata without mutable container aliasing.

    Args:
        value: A short JSON representation of raw phase metadata.

    Returns:
        An equal shared string.
    """
    return value


def record(value: dict[str, object]) -> collections.abc.Mapping[str, object]:
    """Retain complete fields while compacting repeated raw phase segments.

    Args:
        value: The original structured record.

    Returns:
        Read-only fields with raw phase containers materialized on demand.
    """
    if not isinstance(value.get("phase_segments"), list):
        return types.MappingProxyType(value)
    try:
        segments = json.dumps(value["phase_segments"], sort_keys=True)
    except TypeError, ValueError:
        return types.MappingProxyType(value)
    return Record(
        encoded_fields=types.MappingProxyType({
            **value,
            "phase_segments": encoded(segments)
            if len(segments) <= MAXIMUM_PHASE_TEXT_LENGTH
            else segments,
        }),
    )
