"""Concrete monitoring records for independent behavioral scenarios."""

import json
import pathlib

import peri_scribe.monitor.model
import peri_scribe.phases


BRANCHES = peri_scribe.phases.Branches(
    feeds=("alpha", "beta"),
    sources=("evacuations", "buildings"),
    evacuations="evacuations",
)


def record(
    message: str,
    *,
    path: peri_scribe.phases.Path = (),
    run_id: str = "run-1",
    **fields: object,
) -> dict[str, object]:
    """Construct log evidence without calling the production logging implementation.

    Args:
        message: The recorded event description.
        path: Explicit phase and source identities.
        run_id: The command invocation that owns the event.
        fields: Additional evidence for the scenario.

    Returns:
        A JSON-serializable event with a stable timestamp.
    """
    result: dict[str, object] = {
        "event": message,
        "run_id": run_id,
        "level": "info",
        "timestamp": "2026-09-16T08:00:00+00:00",
        "phase_segments": [
            {"phase": segment.phase, "branch": segment.branch} for segment in path
        ],
        **fields,
    }
    if path and message in {"Starting phase", "Finished phase"}:
        result["phase"] = path[-1].phase
    return result


def run(*records: dict[str, object]) -> peri_scribe.monitor.model.Run:
    """Build a command state from independently specified event records.

    Args:
        records: The scenario's ordered log evidence.

    Returns:
        Its first run after domain ingestion.
    """
    return peri_scribe.monitor.model.append_records(
        peri_scribe.monitor.model.State(),
        records,
    ).runs[0]


def write_log(directory: pathlib.Path, *records: dict[str, object]) -> pathlib.Path:
    """Publish complete test records only inside the caller's isolated directory.

    Args:
        directory: A temporary year directory.
        records: The complete records to append.

    Returns:
        The monthly log path.
    """
    path = directory / "logs" / "2026-09.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        for item in records:
            stream.write(json.dumps(item) + "\n")
    return path
