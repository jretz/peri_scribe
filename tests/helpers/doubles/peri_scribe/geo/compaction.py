"""Real-process lock and termination probes for parsed-cache replacement."""

import pathlib
import sys

import tests.formal.helpers.process


CRASH_STATUS = 91

LOCK_PROBE = """
import fcntl
import pathlib
import sys
with pathlib.Path(sys.argv[1]).open("a+b") as stream:
    try:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("blocked")
    else:
        print("acquired")
"""

CRASH_PROBE = """
import os
import pathlib
import sys
import peri_scribe.geo.compaction
import peri_scribe.geo.database

path = pathlib.Path(sys.argv[1])
phase = sys.argv[2]
peri_scribe.geo.compaction.MINIMUM_FREE_BYTES = 1
copy_table = peri_scribe.geo.compaction.copy_table
prepare = peri_scribe.geo.compaction.prepare
replace = pathlib.Path.replace

def copy(source, target, table):
    copy_table(source, target, table)
    if phase == "copy" and table == "memberships":
        os._exit(91)

def prepared(source, target, schema):
    result = prepare(source, target, schema)
    if phase == "closed":
        os._exit(91)
    return result

def published(source, target):
    result = replace(source, target)
    if phase == "published":
        os._exit(91)
    return result

peri_scribe.geo.compaction.copy_table = copy
peri_scribe.geo.compaction.prepare = prepared
pathlib.Path.replace = published
with peri_scribe.geo.compaction.writer_lock(path):
    peri_scribe.geo.compaction.compact(
        path, peri_scribe.geo.database.RECORD_CACHE_SCHEMA,
    )
"""


def lock_status(path: pathlib.Path) -> str:
    """Ask an independent process whether the persistent writer lock is available.

    Args:
        path: Database whose neighboring lock is probed.

    Returns:
        Whether the second process acquired or was blocked by the lock.
    """
    result = tests.formal.helpers.process.run(
        [
            sys.executable,
            "-c",
            LOCK_PROBE,
            str(path.with_suffix(path.suffix + ".lock")),
        ],
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def crash(path: pathlib.Path, phase: str) -> int:
    """Terminate a real compactor without running its Python cleanup.

    Args:
        path: Private test database to compact.
        phase: Actual independently durable boundary where the process exits.

    Returns:
        The child's actual termination status.
    """
    return tests.formal.helpers.process.run(
        [sys.executable, "-c", CRASH_PROBE, str(path), phase],
        timeout=30,
    ).returncode
