"""Dated log records exercise published acreage independently of fire geometry."""

import collections.abc
import compression.zstd
import datetime
import pathlib
import typing

import peri_scribe.updates
from measurement_units import units


if typing.TYPE_CHECKING:
    import pint


def entry(
    timestamp: datetime.datetime,
    area: pint.Quantity,
    *,
    identifier: str | None = "2026-calpf-002271",
    name: str = "Timber",
    location: str | None = "21 mi SW of Soledad, CA",
) -> peri_scribe.updates.LogEntry:
    """Provide log records without running geography or KMZ generation.

    Args:
        timestamp: The successful publication time.
        area: The measured mapping size.
        identifier: The identity joining a fire's successive updates.
        name: The displayed fire name.
        location: The location text shared with the report.

    Returns:
        A validated record in the fire-update log format.
    """
    return peri_scribe.updates.LogEntry(
        timestamp=timestamp,
        identifier=identifier,
        name=name,
        location=location,
        mapped_area=peri_scribe.updates.Acreage(value=area.m_as(units.acres)),
    )


def write_log(
    path: pathlib.Path,
    entries: collections.abc.Iterable[peri_scribe.updates.LogEntry],
) -> None:
    """Create plain or rotated log fixtures in an isolated test directory.

    Args:
        path: The plain JSONL or compressed archive path.
        entries: Records to serialize in the supplied order.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    opener = compression.zstd.open if path.suffix == ".zst" else open
    with opener(path, "wt", encoding="utf-8") as stream:
        stream.writelines(entry.model_dump_json() + "\n" for entry in entries)
