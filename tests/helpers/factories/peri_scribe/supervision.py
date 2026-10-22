"""Build private requests and inspect actual child-process observations."""

import asyncio
import json
import os
import pathlib
import sys
import typing

import peri_scribe.supervision


class Event(typing.TypedDict):
    """Describe independently observed child identity and stage options."""

    stage: str
    process: int
    run_context: dict[str, object]
    options: dict[str, object]


def request(year: pathlib.Path) -> peri_scribe.supervision.Request:
    """Select all derived stages without any network dependency.

    Args:
        year: Isolated year owning lock and recovery files.

    Returns:
        A complete forced derived-stage request with deterministic log identity.
    """
    return peri_scribe.supervision.Request(
        year_directory=year,
        start=1,
        end=4,
        unconditional=True,
        logging_levels=("critical", "critical"),
        run_context={"run_id": "supervision-test", "process_id": os.getpid()},
    )


def events(year: pathlib.Path) -> list[Event]:
    """Read complete append-only stage observations without inventing missing records.

    Args:
        year: Isolated year whose children write event records.

    Returns:
        Every completed JSON event in actual append order.
    """
    path = year / "events.jsonl"
    return (
        [json.loads(line) for line in path.read_text().splitlines()]
        if path.exists()
        else []
    )


async def wait_for_stage(year: pathlib.Path, name: str) -> Event:
    """Wait for an actual child event before injecting a process-level interruption.

    Args:
        year: Isolated year receiving child observations.
        name: The stage whose active process is needed.

    Returns:
        The child's actual entry record.
    """
    async with asyncio.timeout(15):
        while True:
            for entry in events(year):
                if entry["stage"] == name:
                    return entry
            await asyncio.sleep(0.01)


async def parent(year: pathlib.Path) -> asyncio.subprocess.Process:
    """Launch the real public CLI and capture its complete exit and diagnostics.

    Args:
        year: Isolated year shared with the child fixtures.

    Returns:
        The running parent process, whose cleanup belongs to the caller.
    """
    return await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "tests.helpers.doubles.peri_scribe.stage_parent",
        "--stderr-log-level",
        "warning",
        "run",
        str(year),
        "--from",
        "geography",
        "--unconditional",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
