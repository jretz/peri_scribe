"""Run every registered TLC configuration with explicit success expectations."""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import os
import pathlib
import shutil
import tempfile
import tomllib

import tests.formal.helpers.corpus
import tests.formal.helpers.process
import tests.formal.helpers.session


DIRECTORY = pathlib.Path(__file__).resolve().parent / "tla"
INVARIANT_VIOLATION = 12


@dataclasses.dataclass(frozen=True, kw_only=True)
class Model:
    """Keep a known counterexample distinguishable from a proved finite model."""

    name: str
    module: str
    config: str
    expected_invariant: str | None = None
    conformance: bool = False


def models() -> tuple[Model, ...]:
    """Reject unregistered configurations so a new model cannot silently go unchecked.

    Returns:
        The complete checked configuration inventory.

    Raises:
        ValueError: If configuration registration is incomplete or ambiguous.
    """
    with (DIRECTORY / "models.toml").open("rb") as stream:
        document = tomllib.load(stream)
    registered = tuple(Model(**item) for item in document["models"])
    names = {model.name for model in registered}
    configurations = {model.config for model in registered}
    available = {path.stem for path in DIRECTORY.glob("*.cfg")}
    if (
        not registered
        or len(names) != len(registered)
        or len(configurations) != len(registered)
        or configurations != available
    ):
        message = "Register each TLC configuration exactly once in models.toml"
        raise ValueError(message)
    for model in registered:
        if not (DIRECTORY / f"{model.module}.tla").is_file():
            message = f"Missing TLA+ module for {model.name}: {model.module}"
            raise ValueError(message)
    return registered


async def run_model(
    model: Model,
    java: str,
    jar: pathlib.Path,
    corpus_directory: pathlib.Path | None = None,
) -> bool:
    """Preserve counterexample diagnostics while rejecting unrelated tool failures.

    Args:
        model: The finite model and its expected verification outcome.
        java: The executable installed by mise.
        jar: The pinned TLA+ tools archive installed by mise.
        corpus_directory: Optional storage shared with later conformance checks.

    Returns:
        Whether TLC produced the exact registered outcome.
    """
    if corpus_directory is not None and model.conformance:
        try:
            checked = await tests.formal.helpers.corpus.checked_graph(
                model.module,
                model.config,
                corpus_directory,
            )
        except AssertionError as error:
            print(f"FAILED: {model.name}: {error}", flush=True)
            return False
        result = tests.formal.helpers.process.Result(
            returncode=0,
            stdout=checked.output,
            stderr="",
        )
    else:
        with tempfile.TemporaryDirectory(prefix="peri-scribe-tlc-") as directory:
            java_directory = pathlib.Path(directory) / "java"
            java_directory.mkdir()
            result = await tests.formal.helpers.process.execute(
                [
                    java,
                    "-XX:+UseParallelGC",
                    "-Xmx1g",
                    f"-Djava.io.tmpdir={java_directory}",
                    "-cp",
                    str(jar),
                    "tlc2.TLC",
                    "-workers",
                    "1",
                    "-seed",
                    "1",
                    "-metadir",
                    directory,
                    "-config",
                    f"{model.config}.cfg",
                    f"{model.module}.tla",
                ],
                standard_input="",
                cwd=DIRECTORY,
                maximum_seconds=180,
            )
    output = result.stdout + result.stderr
    if model.expected_invariant is not None:
        expected = f"Invariant {model.expected_invariant} is violated."
        passed = result.returncode == INVARIANT_VIOLATION and expected in output
        label = "CONFIRMED KNOWN COUNTEREXAMPLE" if passed else "FAILED"
    else:
        passed = (
            result.returncode == 0
            and "Model checking completed. No error has been found." in output
        )
        label = "CHECKED" if passed else "FAILED"
    print(f"{label}: {model.name}", flush=True)
    if not passed or model.expected_invariant is not None:
        print(output, flush=True)
    else:
        for line in output.splitlines():
            if "distinct states found" in line or "Finished in" in line:
                print(f"  {line}", flush=True)
    return passed


async def run_limited_model(
    model: Model,
    java: str,
    jar: pathlib.Path,
    semaphore: asyncio.Semaphore,
    corpus_directory: pathlib.Path | None = None,
) -> bool:
    """Apply the process limit without letting a failed model skip later checks.

    Args:
        model: One selected configuration and its exact expected outcome.
        java: The executable installed by mise.
        jar: The pinned TLA+ tools archive installed by mise.
        corpus_directory: Optional storage shared with later conformance checks.
        semaphore: Shared admission limit for active TLC processes.

    Returns:
        Whether the admitted model completed with its registered outcome.
    """
    async with semaphore:
        try:
            return await run_model(model, java, jar, corpus_directory)
        except TimeoutError:
            print(f"FAILED: {model.name} exceeded 180 seconds", flush=True)
        except OSError as error:
            print(f"FAILED: {model.name}: {error}", flush=True)
        return False


async def run_models(
    selected: tuple[Model, ...],
    java: str,
    jar: pathlib.Path,
    *,
    parallelism: int,
    corpus_directory: pathlib.Path | None = None,
) -> bool:
    """Keep every outcome and cancel active processes if the runner is interrupted.

    Args:
        selected: Every configuration that must complete for this suite.
        java: The executable installed by mise.
        jar: The pinned TLA+ tools archive installed by mise.
        corpus_directory: Optional storage shared with later conformance checks.
        parallelism: Positive maximum number of simultaneous TLC processes.

    Returns:
        Whether every selected configuration produced its registered outcome.
    """
    semaphore = asyncio.Semaphore(parallelism)
    async with asyncio.TaskGroup() as group:
        tasks = [
            group.create_task(
                run_limited_model(model, java, jar, semaphore, corpus_directory),
            )
            for model in selected
        ]
    return all(task.result() for task in tasks)


def main(arguments: list[str] | None = None) -> int:
    """Keep proof checks and documented failures separately runnable.

    Args:
        arguments: Explicit phase arguments, or the command line for standalone runs.

    Returns:
        A nonzero status if any selected model or tool fails.

    Raises:
        RuntimeError: If the required mise toolchain is unavailable.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("suite", choices=("tla", "counterexamples"))
    parser.add_argument(
        "--jobs",
        type=int,
        default=os.environ.get("PERI_SCRIBE_TLC_JOBS", "4"),
        help="maximum simultaneous TLC processes (default: %(default)s)",
    )
    options = parser.parse_args(arguments)
    if options.jobs < 1:
        parser.error("--jobs must be at least 1")
    java = shutil.which("java")
    jar = pathlib.Path(os.environ.get("PERI_SCRIBE_TLA_JAR", ""))
    if java is None or not jar.is_file():
        message = "Run through mise formal-tla or mise formal-counterexamples"
        raise RuntimeError(message)
    selected = tuple(
        model
        for model in models()
        if (model.expected_invariant is not None)
        == (options.suite == "counterexamples")
    )
    if not selected:
        parser.error("The requested suite contains no registered models")
    passed = asyncio.run(
        run_models(
            selected,
            java,
            jar,
            parallelism=options.jobs,
            corpus_directory=tests.formal.helpers.session.directory(),
        ),
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
