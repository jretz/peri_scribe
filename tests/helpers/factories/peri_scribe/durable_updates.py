"""Concrete durable input encodings for corruption and whole-batch validation."""

import datetime
import json
import pathlib

import peri_scribe.fire_updates


NOW = datetime.datetime(2026, 9, 26, 12, tzinfo=datetime.UTC)
IDENTITY = json.dumps(("id", "fire"))


def record() -> dict[str, object]:
    """Provide one complete payload independently of pending-journal validation.

    Returns:
        A valid raw update payload without completion metadata.
    """
    return {
        "identifier": "fire",
        "name": "Fire",
        "location": None,
        "mapped_area": {"value": 100, "units": "acre"},
        "log_identity": ["id", "fire"],
    }


def state(generation: int = 1) -> peri_scribe.fire_updates.State:
    """Keep generations distinguishable without depending on identity resolution.

    Args:
        generation: The checkpoint's abstract mapped-observation generation.

    Returns:
        A valid self-owned history with a unique acknowledgment payload.
    """
    return peri_scribe.fire_updates.State(
        perimeters={IDENTITY: frozenset({f"generation-{generation}"})},
        owners={IDENTITY: IDENTITY},
    )


def pending() -> dict[str, object]:
    """Expose raw JSON fields so tests can corrupt inputs before schema validation.

    Returns:
        A valid pending publication with its original timestamp and batch identity.
    """
    return {
        "records": [record()],
        "state": state().model_dump(mode="json"),
        "timestamp": NOW.isoformat(),
        "batch_id": "retained-batch",
    }


def write(path: pathlib.Path, content: object) -> None:
    """Seed retained evidence without accidentally validating it during setup.

    Args:
        path: An isolated checkpoint or journal path.
        content: JSON-serializable raw data or intentionally damaged bytes.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        content if isinstance(content, bytes) else json.dumps(content).encode(),
    )


def contents(directory: pathlib.Path) -> dict[pathlib.Path, bytes]:
    """Capture both retained evidence and newly created files at the rejection boundary.

    Args:
        directory: An isolated year containing all observed publication artifacts.

    Returns:
        Every file's exact bytes, including lock files if any exist.
    """
    return {
        path.relative_to(directory): path.read_bytes()
        for path in directory.rglob("*")
        if path.is_file()
    }
