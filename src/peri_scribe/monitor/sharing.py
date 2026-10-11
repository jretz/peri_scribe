"""Bounded pools share immutable log metadata without aliasing mutable records.

Algorithm reasoning and contracts:
[Monitor evidence](../../../docs/algorithms/monitor-evidence.md)
"""

import collections.abc
import dataclasses
import functools
import json
import types
import typing

import peri_scribe.phases


MAXIMUM_TEXT_LENGTH = 128
MAXIMUM_PHASE_TEXT_LENGTH = 4096
JSON_CONTAINER_TYPES = (list, dict)
MISSING = object()


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
    """Nested JSON stays immutable until independent raw fields are inspected."""

    encoded_fields: collections.abc.Mapping[str, object]

    @typing.override
    def get(self, key: object, default: object = None) -> object:
        """Read common scalar fields without decoding unrelated nested metadata.

        Args:
            key: The requested original field name.
            default: The result when the field is absent.

        Returns:
            The original value, with independently decoded JSON containers.
        """
        value = self.encoded_fields.get(key, MISSING)
        if value is MISSING:
            return default
        return json.loads(value.text) if isinstance(value, SerializedValue) else value

    def __getitem__(self, key: str) -> object:
        """Return independent containers when nested JSON metadata is requested.

        Args:
            key: The original field name.

        Returns:
            Its original JSON value.
        """
        value = self.encoded_fields[key]
        return json.loads(value.text) if isinstance(value, SerializedValue) else value

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


@dataclasses.dataclass(frozen=True, kw_only=True, slots=True)
class SerializedValue:
    """An immutable JSON representation preserves container shape and field order."""

    text: str


@dataclasses.dataclass(frozen=True, kw_only=True, slots=True)
class PhaseMetadata:
    """Repeated raw fields and normalized paths contain only immutable values."""

    encoded: str
    path: peri_scribe.phases.Path
    serialized: SerializedValue


type PhaseKey = tuple[tuple[str, str | None], ...]


def phase_key(value: object) -> PhaseKey | None:
    """Recognize small ordinary segments without dropping unfamiliar fields.

    Args:
        value: The raw phase_segments field, including malformed metadata.

    Returns:
        A bounded immutable key, or None when the general representation is needed.
    """
    if type(value) is not list:
        return None
    result = []
    maximum_encoded_length = 2
    for segment in value:
        if type(segment) is not dict or len(segment) not in {1, 2}:
            return None
        fields = typing.cast("dict[str, object]", segment)
        phase = fields.get("phase")
        if type(phase) is not str:
            return None
        if len(fields) == 1:
            branch = None
        elif "branch" in fields and type(fields["branch"]) is str:
            branch = fields["branch"]
        else:
            return None
        # One Unicode code point can become two six-character JSON surrogate escapes.
        maximum_encoded_length += 40 + 12 * (len(phase) + len(branch or ""))
        if maximum_encoded_length > MAXIMUM_PHASE_TEXT_LENGTH:
            return None
        result.append((phase, branch))
    return tuple(result)


@functools.lru_cache(maxsize=512)
def metadata_for_key(key: PhaseKey) -> PhaseMetadata:
    """Reuse complete ordinary metadata without sharing mutable containers.

    Args:
        key: Bounded phase names and optional branch names.

    Returns:
        Shared raw JSON and its normalized immutable path.
    """
    segments = [
        {"phase": phase} if branch is None else {"phase": phase, "branch": branch}
        for phase, branch in key
    ]
    representation = encoded(json.dumps(segments, sort_keys=True))
    return PhaseMetadata(
        encoded=representation,
        serialized=SerializedValue(text=representation),
        path=path(
            tuple(
                peri_scribe.phases.Segment(phase=phase, branch=branch or "")
                for phase, branch in key
            ),
        ),
    )


def phase_metadata(value: object) -> PhaseMetadata | None:
    """Select the shared ordinary representation without weakening the fallback.

    Args:
        value: The complete original phase_segments field.

    Returns:
        Immutable metadata when its shape and size permit bounded sharing.
    """
    key = phase_key(value)
    return None if key is None else metadata_for_key(key)


def record(
    value: dict[str, object],
    *,
    metadata: PhaseMetadata | None = None,
) -> collections.abc.Mapping[str, object]:
    """Retain complete fields while compacting repeated raw phase segments.

    Args:
        value: The original structured record.
        metadata: Already normalized ordinary phase metadata, when available.

    Returns:
        Independent JSON fields with nested containers materialized on demand.
        Non-JSON diagnostic objects retain their original fallback representation.
    """
    stored = value.copy()
    for key, item in value.items():
        if key == "phase_segments" and metadata is not None:
            stored[key] = metadata.serialized
        elif isinstance(item, JSON_CONTAINER_TYPES):
            try:
                representation = json.dumps(item, sort_keys=key == "phase_segments")
            except TypeError, ValueError:
                continue
            stored[key] = SerializedValue(
                text=encoded(representation)
                if key == "phase_segments"
                and len(representation) <= MAXIMUM_PHASE_TEXT_LENGTH
                else representation,
            )
    return Record(encoded_fields=types.MappingProxyType(stored))
