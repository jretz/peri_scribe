"""Preserve real rotation persistence across independent interpreter lifetimes."""

import compression.zstd
import dataclasses
import fcntl
import json
import pathlib

import pytest

import peri_scribe.logging
import tests.formal.helpers.crash_worker
import tests.formal.helpers.log_rotation


@dataclasses.dataclass(kw_only=True)
class Rotation(tests.formal.helpers.log_rotation.Scenario):
    """Keep receipt authentication evidence across separate worker lifetimes."""

    request: tests.formal.helpers.crash_worker.Request

    def inspect(self) -> None:
        """Capture real contents before Python can run any exception cleanup."""
        self.request.record("observe", self.snapshot())
        (pathlib.Path(self.request.root) / "rotation.json").write_text(
            json.dumps(self.contents),
        )


def run(request: tests.formal.helpers.crash_worker.Request) -> None:
    """Exercise interrupted receipt publication and retirement with a previous archive.

    Args:
        request: The selected crash window or fresh recovery invocation.
    """
    request.directory.mkdir(parents=True, exist_ok=True)
    scenario = Rotation(
        path=request.directory / "2026-01.jsonl",
        checked=None,
        request=request,
    )
    metadata = pathlib.Path(request.root) / "rotation.json"
    if metadata.exists():
        scenario.contents = {
            key: tuple(value) for key, value in json.loads(metadata.read_text()).items()
        }
    if request.phase == "seed":
        scenario.archive.write_bytes(
            compression.zstd.compress(tests.formal.helpers.log_rotation.LINES[2]),
        )
        scenario.path.write_bytes(tests.formal.helpers.log_rotation.LINES[1] * 2)
        scenario.inspect()
        return
    with pytest.MonkeyPatch.context() as patch:
        scenario.install(patch)
        if request.phase == "crash":
            tests.formal.helpers.crash_worker.interruption(
                patch,
                request,
                {
                    "receipt": scenario.receipt,
                    "archive": scenario.archive,
                    "source": scenario.path,
                    "retire": scenario.receipt,
                }[request.boundary],
                deletion=request.boundary in {"source", "retire"},
            )
        with (request.directory / ".rotation.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if scenario.path.exists() or scenario.receipt.exists():
                peri_scribe.logging.compress_log(scenario.path)
            scenario.inspect()
    request.record("complete", request.phase)
