"""Join ordinary checks and proofs before starting the complete formal worker pool.

Design notes:
[Verification evidence and execution](../../../docs/algorithms/verification-tooling.md).
"""

from __future__ import annotations

import asyncio
import collections.abc
import dataclasses
import hashlib
import json
import os
import pathlib
import shutil
import sys
import time
import types

import tests.formal.check
import tests.formal.helpers.defect_checks
import tests.formal.helpers.fixtures.defects
import tests.formal.helpers.process
import tests.formal.helpers.session
import tests.helpers.ordinary_lanes


DIRECTORY = pathlib.Path(__file__).resolve().parents[3]
WORKERS = 5


class PhaseError(Exception):
    """A failed native phase cannot authorize dependent work or whole-suite success."""


def require_success(status: int, phase: str) -> None:
    """Propagate a native failure through the owning task group's cleanup.

    Args:
        status: The actual phase exit status.
        phase: The phase whose diagnostics have already been retained.

    Raises:
        PhaseError: If the actual phase failed.
    """
    if status:
        message = f"The {phase} phase exited {status}"
        raise PhaseError(message)


def diagnostics(result: tests.formal.helpers.process.Result) -> None:
    """Retain the original tool output and its native verdicts.

    Args:
        result: The completed native command's diagnostic streams.
    """
    print(result.stdout, end="", flush=True)
    print(result.stderr, end="", file=sys.stderr, flush=True)


def source_inventory() -> dict[pathlib.Path, tests.helpers.ordinary_lanes.Generation]:
    """Include source, checks, configuration and locks in one current-run identity.

    Returns:
        Current file generations, including membership in the source and test trees.
    """
    inputs, _ = tests.helpers.ordinary_lanes.input_paths()
    paths = {DIRECTORY / name for name in inputs}
    paths.update(
        DIRECTORY / name
        for name in (
            "uv.lock",
            ".mise/mise.lock",
            ".mise/config.toml",
            ".mise/tasks/qa.toml",
            ".mise/tasks/formal.toml",
            "package.json",
            "package-lock.json",
        )
    )
    return {
        path: tests.helpers.ordinary_lanes.generation(path) for path in sorted(paths)
    }


@dataclasses.dataclass(frozen=True, kw_only=True)
class SourceSeal:
    """Share immutable input generations while phases consume the same source tree."""

    generations: types.MappingProxyType[
        pathlib.Path,
        tests.helpers.ordinary_lanes.Generation,
    ]
    identity: str

    def verify(self) -> None:
        """Reject changed source membership or generations before dependent admission.

        Raises:
            PhaseError: If source or configuration changed during this invocation.
        """
        if source_inventory() != self.generations:
            message = "Source or configuration changed during full verification"
            raise PhaseError(message)


def source_seal(directory: pathlib.Path) -> SourceSeal:
    """Read source bytes once, before any native lane begins.

    Args:
        directory: Private audit and admission storage for this invocation.

    Returns:
        A source identity and immutable generations checked at phase boundaries.
    """
    generations = source_inventory()
    entries = {
        str(path): {
            "generation": generation,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for path, generation in generations.items()
    }
    identity = hashlib.sha256(tests.helpers.ordinary_lanes.encoded(entries)).hexdigest()
    tests.helpers.ordinary_lanes.publish(
        directory / "source-inputs.json",
        entries,
    )
    return SourceSeal(
        generations=types.MappingProxyType(generations),
        identity=identity,
    )


@dataclasses.dataclass(kw_only=True)
class Coordinator:
    """Keep phase ownership and cancellation on one event loop until native cleanup."""

    directory: pathlib.Path
    seal: SourceSeal
    coverage_directory: pathlib.Path | None = None
    aborted: bool = False
    events: list[tuple[str, int]] = dataclasses.field(default_factory=list)
    initial_workers: int | None = None

    def record(self, event: str) -> None:
        """Keep observed boundaries for diagnosis without reusing successful verdicts.

        Args:
            event: The actual boundary just reached by an owned phase.
        """
        self.events.append((event, time.monotonic_ns()))

    def abort(self, reason: str) -> None:
        """Record failure before the owning task group joins native cleanup.

        Args:
            reason: The failed or cancelled operation.
        """
        if not self.aborted:
            self.aborted = True
            self.record("aborted_" + reason)

    async def native(
        self,
        command: list[str],
        phase: str,
    ) -> tests.formal.helpers.process.Result:
        """Require the actual independent command group to exit before releasing space.

        Args:
            command: The native command with its ordinary task or pytest configuration.
            phase: The owner recorded in diagnostics and completion evidence.

        Returns:
            The successful native command's unchanged diagnostic streams.
        """
        result = await tests.formal.helpers.process.execute(
            command,
            standard_input="",
            cwd=DIRECTORY,
            maximum_seconds=1200,
            can_start_nested_tools=False,
            interrupt_grace_seconds=10,
            wait_for_group_exit=True,
        )
        self.record(phase + "_graph_closed")
        diagnostics(result)
        require_success(result.returncode, phase)
        return result

    async def regular(self) -> None:
        """Require complete ordinary and QA success before any formal worker starts."""
        result = await self.native(
            [
                "env",
                "PERI_SCRIBE_TEST_WORKERS=4",
                "PERI_SCRIBE_ORDINARY_LANES=1",
                "mise",
                "test",
            ],
            "regular",
        )
        self.seal.verify()
        self.coverage_directory = coverage_directory(result.stdout)

    async def proofs(self) -> None:
        """Check all models, build Lean and execute every genuine pristine target.

        Raises:
            PhaseError: If the model inventory or Lean toolchain is unavailable.
        """
        java, jar = tests.formal.check.toolchain()
        models = tests.formal.check.selected_models()
        if not models:
            message = "Combined verification requires the positive model inventory"
            raise PhaseError(message)
        passed = await tests.formal.check.run_models(
            models,
            java,
            jar,
            semaphore=asyncio.Semaphore(1),
            corpus_directory=tests.formal.helpers.session.directory(),
        )
        require_success(int(not passed), "models")
        self.record("models_graph_closed")
        self.seal.verify()
        lake = shutil.which("lake")
        if lake is None:
            message = "Run through mise to provide the Lean toolchain"
            raise PhaseError(message)
        result = await tests.formal.helpers.process.execute(
            [lake, "build"],
            cwd=DIRECTORY / "tests/formal/lean",
            standard_input="",
            maximum_seconds=3600,
        )
        diagnostics(result)
        require_success(result.returncode, "Lean")
        self.record("lean_graph_closed")
        self.seal.verify()
        result = await tests.formal.helpers.process.execute(
            [sys.executable, "-m", "tests.formal.helpers.fixtures.defects"],
            cwd=DIRECTORY,
            standard_input="",
            maximum_seconds=210,
        )
        diagnostics(result)
        require_success(result.returncode, "pristine")
        directory = tests.formal.helpers.session.directory()
        assert directory is not None
        tests.formal.helpers.fixtures.defects.require_pristine_targets(directory)
        self.record("pristine_graph_closed")
        self.seal.verify()

    async def formal(self) -> None:
        """Start one complete stock pytest pool after both prerequisite owners exit."""
        self.seal.verify()
        self.initial_workers = WORKERS
        self.record(f"formal_admitted_{WORKERS}")
        await self.native(
            [
                sys.executable,
                "-m",
                "tests.formal.helpers.conformance",
                "--directory",
                str(self.directory),
                "--source",
                self.seal.identity,
                "--workers",
                str(WORKERS),
            ],
            "formal",
        )

    async def guarded(
        self,
        operation: collections.abc.Coroutine[None, None, object],
    ) -> None:
        """Publish failure before the task group cancels other phase owners.

        Args:
            operation: One owned phase whose failure aborts the combined invocation.
        """
        try:
            await operation
        except BaseException as error:
            self.abort(type(error).__name__)
            raise

    async def run(self) -> None:
        """Join every positive native graph before the independent counterexample."""
        passed = False
        try:
            async with asyncio.TaskGroup() as group:
                group.create_task(self.guarded(self.regular()))
                group.create_task(self.guarded(self.proofs()))
            await self.guarded(self.formal())
            self.seal.verify()
        except BaseException as error:
            self.abort(type(error).__name__)
            raise
        else:
            self.record("all_positive_graphs_closed")
            passed = True
        finally:
            tests.helpers.ordinary_lanes.publish(
                self.directory / "coordinator.json",
                {
                    "status": int(not passed),
                    "source": self.seal.identity,
                    "events": self.events,
                    "initial_formal_workers": self.initial_workers,
                },
            )


def coverage_directory(output: str) -> pathlib.Path:
    """Use the completed ordinary command's explicit artifact location.

    Args:
        output: Standard output from the successfully joined ordinary command.

    Returns:
        Its complete coverage session directory.

    Raises:
        PhaseError: The command did not identify one matching coverage session.
    """
    prefix = "Test artifacts: "
    destinations = [
        line.removeprefix(prefix)
        for line in output.splitlines()
        if line.startswith(prefix)
    ]
    if len(destinations) != 1:
        message = "Regular checks did not identify one coverage session"
        raise PhaseError(message)
    directory = pathlib.Path(destinations[0]).resolve(strict=True)
    marker = json.loads((directory / "session.json").read_bytes())
    if marker.get("directory") != str(directory) or not marker.get("runId"):
        message = "Regular coverage session does not match its reported directory"
        raise PhaseError(message)
    return directory


def preserve_reports(coordinator: Coordinator) -> None:
    """Keep closed formal receipts beside the completed ordinary coverage artifacts.

    Args:
        coordinator: The successful owner of all positive verification phases.
    """
    destination = coordinator.coverage_directory
    assert destination is not None
    corpus = tests.formal.helpers.session.directory()
    assert corpus is not None
    baseline = tests.formal.helpers.fixtures.defects.baseline_name(
        tests.formal.helpers.defect_checks.DEFECTS,
    )
    for source, target in (
        (coordinator.directory / "formal.json", "formal-protocols.json"),
        (coordinator.directory / "formal.xml", "formal-results.xml"),
        (coordinator.directory / "coordinator.json", "verification-phases.json"),
        (coordinator.directory / "source-inputs.json", "verification-inputs.json"),
        (corpus / f"{baseline}.json", "mutation-protocols.json"),
    ):
        staging = destination / (target + ".tmp")
        shutil.copyfile(source, staging)
        staging.replace(destination / target)


def enabled() -> bool:
    """Apply the qualified overlapping plan to the standard full-suite budget.

    Returns:
        Whether this invocation requests the reviewed native worker configuration.
    """
    return (
        os.environ.get("PERI_SCRIBE_TEST_WORKERS") == str(WORKERS)
        and os.cpu_count() == 1
        and all(
            os.environ.get(name) == "1"
            for name in (
                "OMP_NUM_THREADS",
                "OPENBLAS_NUM_THREADS",
                "VECLIB_MAXIMUM_THREADS",
                "RAYON_NUM_THREADS",
            )
        )
    )


def run() -> int:
    """Retain the fresh corpus owner until all positive and negative checks finish.

    Returns:
        The independent counterexample check's status after all positive phases pass.

    Raises:
        PhaseError: If the invocation lacks an independent process or corpus owner.
    """
    if tests.formal.helpers.process.inherited_group() is not None:
        message = "Combined verification requires independent process ownership"
        raise PhaseError(message)
    corpus = tests.formal.helpers.session.directory()
    if corpus is None:
        message = "Combined verification requires a live fresh evidence session"
        raise PhaseError(message)
    directory = corpus / "admission"
    directory.mkdir(mode=0o700)
    seal = source_seal(directory)
    coordinator = Coordinator(directory=directory, seal=seal)
    asyncio.run(coordinator.run())
    status = tests.formal.check.main(["counterexamples"])
    seal.verify()
    preserve_reports(coordinator)
    return status
