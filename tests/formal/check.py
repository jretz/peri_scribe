"""Run every registered TLC configuration with explicit success expectations.

Design notes:
[Verification evidence and execution](../../docs/algorithms/verification-tooling.md).
"""

from __future__ import annotations

import argparse
import asyncio
import collections.abc
import contextlib
import dataclasses
import os
import pathlib
import shutil
import tempfile

import tests.formal.helpers.corpus
import tests.formal.helpers.model_registry
import tests.formal.helpers.process
import tests.formal.helpers.session
import tests.formal.helpers.tlc
import tests.formal.helpers.tlc_frames
import tests.formal.helpers.tlc_worker


DIRECTORY = tests.formal.helpers.model_registry.DIRECTORY
INVARIANT_VIOLATION = 12
Model = tests.formal.helpers.model_registry.Model


@dataclasses.dataclass(frozen=True, kw_only=True)
class ModelWorkers:
    """Keep one active request per JVM while reusing idle JVMs between models."""

    java: str
    jar: pathlib.Path
    classes: pathlib.Path
    resources: contextlib.AsyncExitStack
    idle: list[tests.formal.helpers.tlc_worker.Worker] = dataclasses.field(
        default_factory=list,
    )

    @contextlib.contextmanager
    def lease(
        self,
    ) -> collections.abc.Generator[tests.formal.helpers.tlc_worker.Worker]:
        """Only an admitted model may take a worker from this pool.

        Yields:
            A worker reserved until the request and its cleanup finish.
        """
        if self.idle:
            worker = self.idle.pop()
        else:
            worker = tests.formal.helpers.tlc_worker.Worker(
                self.java,
                self.jar,
                self.classes,
                DIRECTORY,
            )
            self.resources.push_async_callback(worker.close)
        try:
            yield worker
        finally:
            self.idle.append(worker)


def models() -> tuple[Model, ...]:
    """Reject unregistered configurations so a new model cannot silently go unchecked.

    Returns:
        The complete checked configuration inventory.

    Raises:
        ValueError: If configuration registration is incomplete or ambiguous.
    """
    registered = tests.formal.helpers.model_registry.declarations(DIRECTORY)
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
    *,
    worker: tests.formal.helpers.tlc_worker.Worker | None = None,
) -> bool:
    """Preserve counterexample diagnostics while rejecting unrelated tool failures.

    Args:
        model: The finite model and its expected verification outcome.
        java: The executable installed by mise.
        jar: The pinned TLA+ tools archive installed by mise.
        corpus_directory: Optional storage shared with later conformance checks.
        worker: A leased JVM with no other active model.

    Returns:
        Whether TLC produced the exact registered outcome.
    """
    try:
        result = await check_model(
            model,
            java,
            jar,
            corpus_directory,
            worker=worker,
        )
    except (AssertionError, ValueError) as error:
        print(f"FAILED: {model.name}: {error}", flush=True)
        return False
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
            if (
                "distinct states found" in line
                or "Finished in" in line
                or line == tests.formal.helpers.tlc_frames.METHOD
            ):
                print(f"  {line}", flush=True)
    return passed


async def check_model(
    model: Model,
    java: str,
    jar: pathlib.Path,
    corpus_directory: pathlib.Path | None,
    *,
    worker: tests.formal.helpers.tlc_worker.Worker | None,
) -> tests.formal.helpers.process.Result:
    """Select the frame path only for its reviewed positive evidence mode.

    Returns:
        Current-run diagnostics for the completed finite check.
    """
    mode = model.conformance.name if model.conformance is not None else "COUNTS"
    qualified = (
        model.expected_invariant is None
        and tests.formal.helpers.tlc_frames.EXPORTS.get(
            (model.module, model.config),
        )
        == mode
    )
    if corpus_directory is not None and model.conformance is not None:
        return await run_exported_model(
            model,
            corpus_directory,
            worker,
            framed=qualified,
        )
    with tempfile.TemporaryDirectory(prefix="peri-scribe-tlc-") as temporary:
        directory = pathlib.Path(temporary)
        source_directory = DIRECTORY
        if qualified and mode == "COUNTS" and worker is not None and worker.framed:
            output = await tests.formal.helpers.tlc_frames.check(
                model.module,
                model.config,
                directory,
                worker,
            )
            if output is not None:
                return tests.formal.helpers.process.Result(
                    returncode=0,
                    stdout=output,
                    stderr="",
                )
            # Standalone TLC owns the terminal status of a temporal counterexample.
            source_directory = worker.cwd
            worker = None
        return await run_stock_model(
            model,
            java,
            jar,
            directory,
            worker=worker,
            source_directory=source_directory,
        )


async def run_exported_model(
    model: Model,
    directory: pathlib.Path,
    worker: tests.formal.helpers.tlc_worker.Worker | None,
    *,
    framed: bool,
) -> tests.formal.helpers.process.Result:
    """Check and publish the exact graph or state inventory registered for a model.

    Returns:
        Current-run diagnostics from the complete model check.
    """
    output = (
        await tests.formal.helpers.tlc_frames.check(
            model.module,
            model.config,
            directory,
            worker,
        )
        if framed
        else None
    )
    if output is None:
        source_directory = None
        if (
            framed
            and worker is not None
            and worker.framed
            and (
                model.config == "BuildingsConstruction"
                or (model.module, model.config)
                in tests.formal.helpers.tlc_frames.SAFETY_EXPORTS
            )
        ):
            # Standalone TLC owns the terminal status of a declined proof request.
            source_directory = worker.cwd
            worker = None
        check = (
            tests.formal.helpers.corpus.checked_states
            if model.conformance is tests.formal.helpers.model_registry.Export.STATES
            else tests.formal.helpers.corpus.checked_graph
        )
        checked = await check(
            model.module,
            model.config,
            directory,
            worker=worker,
            source_directory=source_directory,
        )
        output = checked.output
    return tests.formal.helpers.process.Result(returncode=0, stdout=output, stderr="")


async def run_stock_model(
    model: Model,
    java: str,
    jar: pathlib.Path,
    directory: pathlib.Path,
    *,
    worker: tests.formal.helpers.tlc_worker.Worker | None,
    source_directory: pathlib.Path,
) -> tests.formal.helpers.process.Result:
    """Keep the locked checker's original counterexample and failure diagnostics.

    Returns:
        The exact result and diagnostics from the locked TLC process.
    """
    java_directory = directory / "java"
    java_directory.mkdir()
    arguments = [
        "-workers",
        "1",
        "-lncheck",
        "final",
        "-seed",
        "1",
        "-metadir",
        str(directory),
        "-config",
        f"{model.config}.cfg",
        f"{model.module}.tla",
    ]
    if worker is not None:
        return await worker.execute(arguments, java_directory, maximum_seconds=180)
    return await tests.formal.helpers.process.execute(
        [
            java,
            *tests.formal.helpers.tlc.JAVA_OPTIONS,
            f"-Djava.io.tmpdir={java_directory}",
            "-cp",
            str(jar),
            "tlc2.TLC",
            *arguments,
        ],
        standard_input="",
        cwd=source_directory,
        maximum_seconds=180,
    )


async def run_limited_model(
    model: Model,
    java: str,
    jar: pathlib.Path,
    semaphore: asyncio.Semaphore,
    corpus_directory: pathlib.Path | None = None,
    *,
    workers: ModelWorkers | None = None,
) -> bool:
    """Apply the process limit without letting a failed model skip later checks.

    Args:
        model: One selected configuration and its exact expected outcome.
        java: The executable installed by mise.
        jar: The pinned TLA+ tools archive installed by mise.
        corpus_directory: Optional storage shared with later conformance checks.
        semaphore: Shared admission limit for active TLC processes.
        workers: Optional reusable workers owned by this invocation.

    Returns:
        Whether the admitted model completed with its registered outcome.
    """
    async with semaphore:
        try:
            with (
                workers.lease() if workers is not None else contextlib.nullcontext()
            ) as worker:
                return await run_model(
                    model,
                    java,
                    jar,
                    corpus_directory,
                    worker=worker,
                )
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
    semaphore: asyncio.Semaphore,
    corpus_directory: pathlib.Path | None = None,
) -> bool:
    """Keep every outcome and cancel active processes if the runner is interrupted.

    Args:
        selected: Every configuration that must complete for this suite.
        java: The executable installed by mise.
        jar: The pinned TLA+ tools archive installed by mise.
        corpus_directory: Optional storage shared with later conformance checks.
        semaphore: Admission limit shared by all selected configurations.

    Returns:
        Whether every selected configuration produced its registered outcome.
    """
    async with contextlib.AsyncExitStack() as resources:
        workers = None
        if (
            corpus_directory is not None
            and len(selected) > 1
            and selected[0].expected_invariant is None
            and tests.formal.helpers.process.inherited_group() is None
        ):
            classes = await tests.formal.helpers.tlc_worker.compile_worker(
                java,
                corpus_directory,
                jar=jar,
            )
            workers = ModelWorkers(
                java=java,
                jar=jar,
                classes=classes,
                resources=resources,
            )
        async with asyncio.TaskGroup() as group:
            tasks = [
                group.create_task(
                    run_limited_model(
                        model,
                        java,
                        jar,
                        semaphore,
                        corpus_directory,
                        workers=workers,
                    ),
                )
                for model in selected
            ]
        return all(task.result() for task in tasks)


def toolchain() -> tuple[str, pathlib.Path]:
    """Resolve the same mise toolchain for standalone and combined model checks.

    Returns:
        The Java executable and TLA+ tools archive.

    Raises:
        RuntimeError: If either tool is unavailable.
    """
    java = shutil.which("java")
    jar = pathlib.Path(os.environ.get("PERI_SCRIBE_TLA_JAR", ""))
    if java is None or not jar.is_file():
        message = "Run through mise formal-tla or mise formal-counterexamples"
        raise RuntimeError(message)
    return java, jar


def selected_models(*, counterexamples: bool = False) -> tuple[Model, ...]:
    """Keep successful models separate from expected failures.

    Args:
        counterexamples: Select the configurations expected to violate an invariant.

    Returns:
        Every registered configuration for the requested outcome.
    """
    return tuple(
        model
        for model in models()
        if (model.expected_invariant is not None) == counterexamples
    )


def main(arguments: list[str] | None = None) -> int:
    """Keep proof checks and documented failures separately runnable.

    Args:
        arguments: Explicit phase arguments, or the command line for standalone runs.

    Returns:
        A nonzero status if any selected model or tool fails.
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
    java, jar = toolchain()
    selected = selected_models(counterexamples=options.suite == "counterexamples")
    if not selected:
        parser.error("The requested suite contains no registered models")
    passed = asyncio.run(
        run_models(
            selected,
            java,
            jar,
            semaphore=asyncio.Semaphore(options.jobs),
            corpus_directory=tests.formal.helpers.session.directory(),
        ),
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
