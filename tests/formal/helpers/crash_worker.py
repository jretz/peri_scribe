"""Terminate isolated production writers without running Python cleanup handlers."""

from __future__ import annotations

import atexit
import dataclasses
import importlib
import json
import os
import pathlib
import signal
import sys
import typing


if typing.TYPE_CHECKING:
    import pytest


EXIT_STATUS = 91


@dataclasses.dataclass(frozen=True, kw_only=True)
class Request:
    """A private test invocation selects one precise durable interruption boundary."""

    root: str
    family: str
    phase: str
    boundary: str
    after: bool
    method: str

    @property
    def directory(self) -> pathlib.Path:
        """Keep real application paths separate from harness evidence.

        Returns:
            The isolated application year directory.
        """
        return pathlib.Path(self.root) / "2026"

    def record(self, kind: str, value: object) -> None:
        """Close evidence before termination so the parent can check the full prefix.

        Args:
            kind: The observation or control-event category.
            value: JSON-safe evidence from the actual writer.
        """
        with (pathlib.Path(self.root) / "trace.jsonl").open("a") as stream:
            stream.write(
                json.dumps({"kind": kind, "value": value}, default=list) + "\n",
            )

    def terminate(self) -> typing.Never:
        """Leave database transactions, temporary files, and locks to process teardown.

        Raises:
            AssertionError: If the operating system does not terminate the worker.
        """
        self.record("crash", {"method": self.method, "process": os.getpid()})
        if self.method == "exit":
            os._exit(EXIT_STATUS)
        os.kill(os.getpid(), signal.SIGKILL)
        message = "SIGKILL did not terminate the worker"
        raise AssertionError(message)


def interruption(
    patch: pytest.MonkeyPatch,
    request: Request,
    target: pathlib.Path,
    *,
    deletion: bool = False,
) -> None:
    """Preserve the actual operation, killing immediately on the selected side.

    Args:
        patch: Private worker overrides; no production process is patched.
        request: The selected fault and termination method.
        target: The canonical file boundary whose observation is under test.
        deletion: Whether the boundary removes rather than replaces a file.
    """
    original_replace = pathlib.Path.replace
    original_unlink = pathlib.Path.unlink

    def replace(path: pathlib.Path, destination: pathlib.Path) -> pathlib.Path:
        """A staged write cannot become public unless the real replacement completes.

        Args:
            path: Staged artifact.
            destination: Public file.

        Returns:
            The actual replacement's destination.
        """
        selected = destination == target and not deletion
        if selected and not request.after:
            request.terminate()
        result = original_replace(path, destination)
        if selected:
            request.terminate()
        return result

    def unlink(path: pathlib.Path, *, missing_ok: bool = False) -> None:
        """Source and journal retirement retain their independent crash windows.

        Args:
            path: File being retired.
            missing_ok: The production caller's missing-file policy.
        """
        selected = path == target and deletion
        if selected and not request.after:
            request.terminate()
        original_unlink(path, missing_ok=missing_ok)
        if selected:
            request.terminate()

    patch.setattr(pathlib.Path, "replace", replace)
    patch.setattr(pathlib.Path, "unlink", unlink)


def main() -> None:
    """A selected crash must terminate without returning through Python cleanup."""
    request = Request(**json.loads(sys.stdin.read()))
    pathlib.Path(request.root).mkdir(parents=True, exist_ok=True)
    request.record("process", os.getpid())
    if request.phase == "crash":
        atexit.register((pathlib.Path(request.root) / "atexit-ran").touch)
    try:
        worker = importlib.import_module(
            f"tests.formal.helpers.crash_workers.{request.family}",
        )
        worker.run(request)
    finally:
        if request.phase == "crash":
            (pathlib.Path(request.root) / "finally-ran").touch()
    assert request.phase != "crash", "selected durable crash boundary was not reached"


if __name__ == "__main__":
    main()
