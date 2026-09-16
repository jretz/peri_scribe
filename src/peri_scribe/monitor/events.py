"""Normalize structured records without coupling their consumers to a presentation."""

import collections.abc
import dataclasses
import datetime
import json
import types

import peri_scribe.phases


@dataclasses.dataclass(frozen=True, kw_only=True)
class Event:
    """Retained records preserve their original fields and resolved execution scope."""

    sequence: int
    fields: collections.abc.Mapping[str, object]
    path: peri_scribe.phases.Path
    timestamp: datetime.datetime | None

    @property
    def message(self) -> str:
        """Expose a displayable event even when a third-party record is incomplete."""
        return str(self.fields.get("event", ""))

    @property
    def level(self) -> str:
        """Normalize severity for consistent filtering across log writers."""
        return str(self.fields.get("level", "info")).lower()


def parse_record(line: str) -> dict[str, object]:
    """Keep damaged records inspectable without stopping the rest of the stream.

    Args:
        line: A complete newline-delimited record.

    Returns:
        JSON fields or a warning containing the original text.
    """
    try:
        value = json.loads(line)
        if isinstance(value, dict):
            return value
    except ValueError:
        pass
    return {"event": line.rstrip(), "level": "warning", "malformed": True}


def timestamp(value: object) -> datetime.datetime | None:
    """Normalize timestamps so mixed timezone records can share a run timeline.

    Args:
        value: A possibly absent or damaged timestamp field.

    Returns:
        An aware timestamp, or None when no reliable timestamp is available.
    """
    try:
        parsed = datetime.datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed.replace(tzinfo=datetime.UTC) if parsed.tzinfo is None else parsed


def event_path(
    fields: collections.abc.Mapping[str, object],
    parent: peri_scribe.phases.Path,
) -> peri_scribe.phases.Path:
    """Prefer explicit instances and otherwise retain the observed nesting context.

    Args:
        fields: The incoming record's structured fields.
        parent: The most recently opened phase in this run.

    Returns:
        The best available phase instance path, including unknown phase names.
    """
    segments = fields.get("phase_segments")
    if isinstance(segments, list) and all(
        isinstance(segment, dict) and isinstance(segment.get("phase"), str)
        for segment in segments
    ):
        return tuple(
            peri_scribe.phases.Segment(
                phase=segment["phase"],
                branch=str(segment.get("branch", "")),
            )
            for segment in segments
        )
    path = fields.get("phase_path")
    if isinstance(path, str) and path:
        return tuple(
            parent[index]
            if index < len(parent) and parent[index].phase == phase
            else peri_scribe.phases.Segment(
                phase=phase,
                branch=peri_scribe.phases.branch_name(phase, fields),
            )
            for index, phase in enumerate(path.split("."))
        )
    phase = fields.get("phase")
    if isinstance(phase, str):
        if fields.get("event") == "Finished phase" and parent:
            return parent
        return (
            *parent,
            peri_scribe.phases.Segment(
                phase=phase,
                branch=peri_scribe.phases.branch_name(phase, fields),
            ),
        )
    return parent


def make_event(
    fields: dict[str, object],
    sequence: int,
    parent: peri_scribe.phases.Path,
) -> Event:
    """Preserve raw records alongside normalized fields for interchangeable consumers.

    Args:
        fields: The incoming structured record.
        sequence: Its stable position in the monitor's retained stream.
        parent: The run's currently open phase.

    Returns:
        An immutable event ready for a reducer or a presentation adapter.
    """
    return Event(
        sequence=sequence,
        fields=types.MappingProxyType(fields),
        path=event_path(fields, parent),
        timestamp=timestamp(fields.get("timestamp")),
    )
