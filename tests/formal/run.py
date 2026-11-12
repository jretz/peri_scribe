"""Run formal phases with fresh evidence and optional overlap with regular checks."""

import argparse
import asyncio
import os
import pathlib
import shutil
import sys

import pytest

import tests.formal.check
import tests.formal.helpers.defect_baselines
import tests.formal.helpers.overlap
import tests.formal.helpers.process
import tests.formal.helpers.session


DIRECTORY = pathlib.Path(__file__).resolve().parents[2]


async def regular_checks(semaphore: asyncio.Semaphore, model_jobs: int) -> int:
    """Keep one model slot open until the ordinary test process tree finishes.

    Args:
        semaphore: The shared admission limit for TLC jobs.
        model_jobs: The model concurrency available once regular checks finish.

    Returns:
        The regular checks' exit status.
    """
    result = await tests.formal.helpers.process.execute(
        [
            "env",
            "PERI_SCRIBE_TEST_WORKERS=4",
            "PERI_SCRIBE_ORDINARY_LANES=1",
            "mise",
            "test",
        ],
        standard_input="",
        cwd=DIRECTORY,
        maximum_seconds=1200,
        can_start_nested_tools=False,
        # Playwright stops its separately launched Chromium through its SIGINT handler.
        interrupt_grace_seconds=10,
    )
    print(result.stdout, end="", flush=True)
    print(result.stderr, end="", file=sys.stderr, flush=True)
    for _ in range(model_jobs - 1):
        semaphore.release()
    return result.returncode


async def prepare_pristine(ordinary: asyncio.Task[int]) -> int:
    """Use an idle proof slot after TLC completes when Lean is already current.

    Args:
        ordinary: The ordinary gate whose remaining work can overlap preparation.

    Returns:
        The early pristine check's exit status, or zero if it was left to conformance.
    """
    lake = shutil.which("lake")
    if lake is None or ordinary.done():
        return 0
    try:
        current = await tests.formal.helpers.process.execute(
            [lake, "--no-build", "build"],
            cwd=DIRECTORY / "tests" / "formal" / "lean",
            standard_input="",
            maximum_seconds=20,
        )
    except TimeoutError:
        return 0
    if current.returncode or ordinary.done():
        return 0
    result = await tests.formal.helpers.process.execute(
        [sys.executable, "-m", "tests.formal.helpers.fixtures.defects"],
        cwd=DIRECTORY,
        standard_input="",
        maximum_seconds=210,
    )
    print(result.stdout, end="", flush=True)
    print(result.stderr, end="", file=sys.stderr, flush=True)
    return result.returncode


async def initial_phases() -> int:
    """Join ordinary checks and successful models before starting dependent phases.

    Returns:
        The first failure status from ordinary checks, models, or pristine preparation.

    Raises:
        ValueError: If the model inventory is empty or its job limit is invalid.
    """
    model_jobs = int(os.environ.get("PERI_SCRIBE_TLC_JOBS", "3"))
    selected = tests.formal.check.selected_models()
    if model_jobs < 1 or not selected:
        message = (
            "Combined verification requires a positive job limit and model inventory"
        )
        raise ValueError(message)
    java, jar = tests.formal.check.toolchain()
    semaphore = asyncio.Semaphore(1)
    directory = tests.formal.helpers.session.directory()
    async with asyncio.TaskGroup() as group:
        regular = group.create_task(regular_checks(semaphore, model_jobs))
        models = group.create_task(
            tests.formal.check.run_models(
                selected,
                java,
                jar,
                semaphore=semaphore,
                corpus_directory=directory,
            ),
        )
        models_passed = await models
        pristine = (
            await prepare_pristine(regular)
            if models_passed and directory is not None
            else 0
        )
    return regular.result() or int(not models_passed) or pristine


def phases(*, with_regular: bool = False) -> int:
    """Each independent proof job retains its own cancellation and cleanup boundary.

    Args:
        with_regular: Run the ordinary checks alongside the initial model phase.

    Returns:
        The first unsuccessful phase's exit status, or zero after all phases pass.

    Raises:
        RuntimeError: If the registered Lean toolchain is unavailable.
    """
    if with_regular and tests.formal.helpers.overlap.enabled():
        return tests.formal.helpers.overlap.run()
    status = (
        asyncio.run(initial_phases())
        if with_regular
        else tests.formal.check.main(["tla"])
    )
    if status:
        return status
    lake = shutil.which("lake")
    if lake is None:
        message = "Run through mise formal to provide the Lean toolchain"
        raise RuntimeError(message)
    result = tests.formal.helpers.process.run(
        [lake, "build"],
        cwd=DIRECTORY / "tests" / "formal" / "lean",
        timeout=3600,
    )
    print(result.stdout, end="", flush=True)
    print(result.stderr, end="", file=sys.stderr, flush=True)
    if result.returncode:
        return result.returncode
    arguments = [
        "-c",
        str(DIRECTORY / "tests" / "formal" / "pytest.ini"),
        tests.formal.helpers.defect_baselines.USE_PRISTINE_TARGETS,
        str(DIRECTORY / "tests" / "formal" / "conformance"),
    ]
    if (directory := tests.formal.helpers.session.directory()) is not None:
        arguments.extend((
            "--basetemp",
            str(directory / "pytest-temp"),
            "-o",
            "tmp_path_retention_policy=failed",
        ))
    if (workers := os.environ.get("PERI_SCRIBE_TEST_WORKERS")) is not None:
        arguments.extend(("-n", workers))
    status = pytest.main(arguments)
    if status:
        return int(status)
    return tests.formal.check.main(["counterexamples"])


def main(*, with_regular: bool = False) -> int:
    """A temporary session prevents successful evidence from outliving this invocation.

    Args:
        with_regular: Include the ordinary checks in this invocation.

    Returns:
        The complete suite's success or first failing phase's exit status.
    """
    with tests.formal.helpers.session.temporary():
        return phases(with_regular=with_regular)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--with-regular", action="store_true")
    raise SystemExit(main(with_regular=parser.parse_args().with_regular))
