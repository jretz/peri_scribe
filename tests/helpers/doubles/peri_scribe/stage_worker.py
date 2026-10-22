"""Execute real supervised stage loops over deterministic local stage effects."""

import contextlib
import json
import os
import pathlib
import signal
import sys
import time
import typing
import unittest.mock

import peri_scribe.logging
import peri_scribe.pipeline
import peri_scribe.pipeline_state
import peri_scribe.publication
import peri_scribe.supervision


FAILURE_EXIT = 7


def stage_effect(name: str) -> typing.Callable[..., bool]:
    """Keep process, file and recovery effects real while replacing domain workloads.

    Args:
        name: The stage whose independent local effect is being substituted.

    Returns:
        A stage operation controlled by the test year's explicit mode file.
    """

    def execute(year: pathlib.Path, **options: object) -> bool:
        """Record the actual process and lease, then obey the selected failure case.

        Args:
            year: The isolated test year shared by parent and children.
            options: Actual flags and frozen inputs forwarded by the pipeline.

        Returns:
            Whether an unchanged-fetch scenario permits continuation.

        Raises:
            SystemExit: If the selected stage fails with a controlled numeric status.
        """
        mode_path = year / "mode.json"
        mode = json.loads(mode_path.read_text()) if mode_path.exists() else {}
        with (
            peri_scribe.pipeline_state.read_lock(year) as nested,
            peri_scribe.pipeline_state.file_lock(year, shared=False) as competing,
        ):
            if not nested or competing:
                raise SystemExit(9)
        entry = {
            "stage": name,
            "process": os.getpid(),
            "run_context": peri_scribe.logging.RUN_CONTEXT.get(),
            "options": peri_scribe.logging.log_value({
                key: value.model_dump(mode="json")
                if isinstance(value, peri_scribe.publication.Collection)
                else value
                for key, value in options.items()
            }),
        }
        with (year / "events.jsonl").open("a") as stream:
            stream.write(json.dumps(entry) + "\n")
        if mode.get("failure") == name:
            raise SystemExit(FAILURE_EXIT)
        if mode.get("wait") == name:
            if mode.get("ignore_termination"):
                signal.signal(signal.SIGTERM, signal.SIG_IGN)
            while True:
                time.sleep(0.01)
        return not (name == "fetch" and mode.get("skip"))

    return execute


def main() -> None:
    """Run the production worker entrypoint with only local stage computations."""
    with contextlib.ExitStack() as stack:
        for name in ("fetch", "geography", "score", "kmz", "reports"):
            stack.enter_context(
                unittest.mock.patch.object(
                    peri_scribe.pipeline,
                    f"run_{name}_stage",
                    stage_effect(name),
                ),
            )
        stack.enter_context(
            unittest.mock.patch.object(
                peri_scribe.publication,
                "collect",
                return_value=peri_scribe.publication.Collection(cities="frozen cities"),
            ),
        )
        peri_scribe.supervision.worker_main(sys.argv[1:])


if __name__ == "__main__":
    main()
