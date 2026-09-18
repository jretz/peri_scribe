"""Inspect main behavior with shared test utilities."""

from __future__ import annotations

import asyncio
import collections.abc
import json
import pathlib
import sys


CLICK_USAGE_ERROR_EXIT_CODE = 2

MONITOR_IMPORTS = """
import json
import sys
import unittest.mock

import peri_scribe.main

with unittest.mock.patch('peri_scribe.monitor.app.MonitorApp.run'):
    peri_scribe.main.cli.main(args=['monitor', sys.argv[1]], standalone_mode=False)
print(json.dumps(sorted(sys.modules)))
"""


async def monitor_imports(year_directory: pathlib.Path) -> set[str]:
    """Isolate startup from pipeline imports already loaded by other tests.

    Args:
        year_directory: The test's isolated monitor directory.

    Returns:
        Modules loaded by the real monitoring command before terminal startup.
    """
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        MONITOR_IMPORTS,
        str(year_directory),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    output, errors = await process.communicate()
    assert process.returncode == 0, errors.decode()
    return set(json.loads(output))


def boundary_payload(entry: collections.abc.Mapping[str, object]) -> dict[str, object]:
    """Keep timing assertions focused on execution boundaries.

    Args:
        entry: A captured boundary with independently tested correlation metadata.

    Returns:
        The boundary's operation and timing fields.
    """
    return {
        key: value
        for key, value in entry.items()
        if key not in {"run_id", "process_id", "phase_segments", "exception"}
    }
