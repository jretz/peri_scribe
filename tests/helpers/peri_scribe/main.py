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


YEAR_COMMAND_HELP = """
import datetime
import sys

import time_machine

with time_machine.travel(
    datetime.datetime(int(sys.argv[2]), 7, 1, tzinfo=datetime.UTC), tick=False,
):
    import peri_scribe.main

    peri_scribe.main.cli.main(args=[sys.argv[1], '--help'], standalone_mode=False)
"""


async def cli_script_output(script: str, *arguments: str) -> str:
    """Keep CLI import state independent of the parent test process.

    Args:
        script: Python code to run in a fresh interpreter.
        arguments: Values supplied to that script through its command line.

    Returns:
        Standard output from the successful script.
    """
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        script,
        *arguments,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    output, errors = await process.communicate()
    assert process.returncode == 0, errors.decode()
    return output.decode()


async def monitor_imports(year_directory: pathlib.Path) -> set[str]:
    """Isolate startup from pipeline imports already loaded by other tests.

    Args:
        year_directory: The test's isolated monitor directory.

    Returns:
        Modules loaded by the real monitoring command before terminal startup.
    """
    return set(
        json.loads(await cli_script_output(MONITOR_IMPORTS, str(year_directory))),
    )


async def year_command_help(command: str, year: int) -> str:
    """Freeze the year before CLI imports construct their default-path help.

    Args:
        command: CLI command whose help is being checked.
        year: The year shared by command construction and invocation.

    Returns:
        The command's help text from the isolated interpreter.
    """
    return await cli_script_output(YEAR_COMMAND_HELP, command, str(year))


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
