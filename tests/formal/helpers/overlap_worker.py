"""Expose native process ownership without starting another test or proof suite."""

import asyncio
import contextlib
import fcntl
import json
import os
import pathlib
import signal
import sys
import time

import tests.formal.helpers.process


DIRECTORY = pathlib.Path(__file__).resolve().parents[3]


def publish(directory: pathlib.Path, name: str, value: object) -> None:
    """Expose only completed JSON handshakes to the observing parent.

    Args:
        directory: The control's private resource directory.
        name: The observation to publish.
        value: Complete JSON-compatible native observations.
    """
    temporary = directory / f"{name}.tmp"
    temporary.write_text(json.dumps(value))
    temporary.replace(directory / f"{name}.json")


def ready(directory: pathlib.Path, name: str) -> None:
    """Publish actual identifiers only after the worker owns its resource lock.

    Args:
        directory: The control's private resource directory.
        name: The worker's role.
    """
    publish(
        directory,
        f"{name}-ready",
        {
            "pid": os.getpid(),
            "group": os.getpgrp(),
            "session": os.getsid(0),
        },
    )


def command(directory: pathlib.Path) -> list[str]:
    """Keep the leaf in a fresh lightweight interpreter.

    Args:
        directory: The parent's private observation directory.

    Returns:
        The native leaf's direct arguments.
    """
    return [
        sys.executable,
        "-m",
        "tests.formal.helpers.overlap_worker",
        "leaf",
        str(directory),
    ]


async def controller(directory: pathlib.Path) -> None:
    """Finish nested cleanup before acknowledging cooperative cancellation.

    Args:
        directory: Private leaf and controller observations.
    """
    ready(directory, "controller")
    try:
        await tests.formal.helpers.process.execute(
            command(directory),
            standard_input="",
            cwd=DIRECTORY,
            maximum_seconds=30,
            can_start_nested_tools=False,
            wait_for_group_exit=True,
        )
    except BaseException as error:
        publish(
            directory,
            "cooperative-cleanup",
            {
                "reason": type(error).__name__,
                "nested_execute_returned": True,
            },
        )
        raise


def main() -> None:
    """Hold real locks until the parent exercises cancellation or group cleanup."""
    mode, raw_directory = sys.argv[1:]
    directory = pathlib.Path(raw_directory)
    with contextlib.ExitStack() as stack:
        name = "leaf" if mode == "leaf" else "controller"
        resource = stack.enter_context((directory / f"{name}.lock").open("ab"))
        fcntl.flock(resource, fcntl.LOCK_EX)
        if mode == "leaf":
            ready(directory, name)
            while True:
                signal.pause()
        elif mode == "exited-parent":
            ready(directory, name)
            child = os.posix_spawn(
                sys.executable,
                command(directory),
                os.environ,
                file_actions=[
                    (os.POSIX_SPAWN_OPEN, number, os.devnull, os.O_WRONLY, 0)
                    for number in (1, 2)
                ],
            )
            while not (directory / "leaf-ready.json").exists():
                assert os.waitpid(child, os.WNOHANG) == (0, 0)
                time.sleep(0.01)
            print("native stdout", flush=True)
            print("native stderr", file=sys.stderr, flush=True)
            os._exit(7)
        else:
            assert mode == "controller"
            asyncio.run(controller(directory))


if __name__ == "__main__":
    main()
