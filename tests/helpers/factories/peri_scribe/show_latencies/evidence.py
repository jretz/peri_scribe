"""Synthetic records make window boundaries independent of production data."""

import compression.zstd
import datetime
import json
import pathlib

import peri_scribe.show_latencies.runs
import peri_scribe.show_latencies.sources
from measurement_units import units


NOW = datetime.datetime(2026, 9, 1, 12, tzinfo=datetime.UTC)
WINDOW = peri_scribe.show_latencies.runs.Window(
    start=NOW,
    end=NOW + datetime.timedelta(hours=1),
)


def record(event: str, seconds: float = 0, **fields: object) -> dict[str, object]:
    """Give a structural event a shared clock and overridable production fields.

    Args:
        event: The logged event name.
        seconds: Seconds after the scenario's reference clock.
        **fields: Other structured fields or clock overrides.

    Returns:
        A serializable diagnostic record.
    """
    return {
        "event": event,
        "timestamp": (NOW + datetime.timedelta(seconds=seconds)).isoformat(),
        "run_id": "one",
        "command": "run",
        **fields,
    }


def write_log(path: pathlib.Path, records: list[dict[str, object]]) -> None:
    """Build either rotation format in a test's isolated directory.

    Args:
        path: The desired monthly log filename.
        records: Chronologically ordered synthetic records.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    contents = "".join(json.dumps(item) + "\n" for item in records).encode()
    path.write_bytes(
        compression.zstd.compress(contents) if path.suffix == ".zst" else contents,
    )


def run(
    seconds: float = 300,
    *,
    produced: bool = True,
    geography: float | None = 120,
) -> peri_scribe.show_latencies.runs.Run:
    """Construct a finished run with an independently chosen input cutoff.

    Args:
        seconds: Its completion offset.
        produced: Whether it wrote a KMZ.
        geography: The source-input cutoff, if known.

    Returns:
        A completed run for replay tests.
    """
    return peri_scribe.show_latencies.runs.Run(
        identifier=str(seconds),
        started=NOW,
        finished=NOW + datetime.timedelta(seconds=seconds),
        duration=seconds * units.seconds,
        geography=NOW + datetime.timedelta(seconds=geography)
        if geography is not None
        else None,
        produced_kmz=produced,
    )


def publication(
    seconds: float = 30,
    *,
    identifier: str = "fire",
    source_file: str = "feed/snapshot.gpkg",
) -> peri_scribe.show_latencies.sources.Publication:
    """Keep polygon publication independent of collection and command completion.

    Args:
        seconds: The polygon version's source publication offset.
        identifier: The fire receiving the new polygon version.
        source_file: The relative source snapshot path used for collection evidence.

    Returns:
        One new polygon version's source publication.
    """
    return peri_scribe.show_latencies.sources.Publication(
        identifier=identifier,
        source_file=source_file,
        published=NOW + datetime.timedelta(seconds=seconds),
    )


def evidence(
    *,
    runs: tuple[peri_scribe.show_latencies.runs.Run, ...],
    snapshots: dict[str, datetime.datetime],
) -> peri_scribe.show_latencies.runs.Evidence:
    """Supply write and endpoint evidence for synthetic completed-run scenarios.

    Args:
        runs: Completed commands whose output status is known.
        snapshots: Independent source-collection times.

    Returns:
        Complete evidence with successful writes dated at the synthetic run endpoints.
    """
    return peri_scribe.show_latencies.runs.Evidence(
        runs=runs,
        snapshots=snapshots,
        kmz_writes=tuple(
            peri_scribe.show_latencies.runs.KmzWrite(
                written=run.finished,
                geography=run.geography,
                finished=run.finished,
            )
            for run in runs
            if run.produced_kmz
        ),
    )
