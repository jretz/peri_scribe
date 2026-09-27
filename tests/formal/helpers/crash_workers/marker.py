"""Preserve real marker persistence across independent interpreter lifetimes."""

import pathlib

import pytest

import peri_scribe.pipeline
import peri_scribe.pipeline_state
import tests.formal.helpers.crash_worker
import tests.formal.helpers.pipeline_state
import tests.helpers.doubles.peri_scribe.pipeline_fetch_recovery


def run(request: tests.formal.helpers.crash_worker.Request) -> None:
    """Run the actual fetch coordinator around independently persisted source changes.

    Args:
        request: A marker replacement or an independently durable source-write fault.
    """
    directory = request.directory
    mutation = tests.helpers.doubles.peri_scribe.pipeline_fetch_recovery.Mutation
    scenario = tests.helpers.doubles.peri_scribe.pipeline_fetch_recovery.Scenario(
        directory=directory,
        changes=frozenset(mutation),
    )

    def inspect() -> None:
        """Keep source effects and their recovery obligation in one observation."""
        pending = peri_scribe.pipeline_state.read_state(directory)
        request.record(
            "observe",
            (
                tests.formal.helpers.pipeline_state.mask(pending.remaining),
                pending.unconditional,
                scenario.path(mutation.FIRE).exists(),
                scenario.path(mutation.EVACUATIONS).exists(),
            ),
        )

    if request.phase == "seed":
        peri_scribe.pipeline_state.write_state(
            directory,
            peri_scribe.pipeline_state.PendingRun(
                remaining=(peri_scribe.pipeline_state.DERIVED_STAGES[-1],),
                unconditional=True,
            ),
        )
        inspect()
        return
    original_write = pathlib.Path.write_text
    original_replace = pathlib.Path.replace

    def replace(path: pathlib.Path, destination: pathlib.Path) -> pathlib.Path:
        """Marking and acknowledgment remain separate from actual source mutation.

        Args:
            path: Private marker contents.
            destination: The canonical marker.

        Returns:
            The unchanged real replacement result.
        """
        inspect()
        result = original_replace(path, destination)
        inspect()
        return result

    def write(
        path: pathlib.Path,
        data: str,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ) -> int:
        """A source revision survives even though its caller never receives success.

        Args:
            path: Actual isolated source path.
            data: Source revision supplied by the controlled external adapter.
            encoding: The caller's text encoding.
            errors: The caller's encoding failure policy.
            newline: The caller's newline policy.

        Returns:
            The number of characters stored.
        """
        source = path in {scenario.path(value) for value in mutation}
        if source:
            inspect()
        count = original_write(path, data, encoding, errors, newline)
        if source:
            inspect()
        if (
            request.phase == "crash"
            and path == directory / "sources" / request.boundary
        ):
            request.terminate()
        return count

    with pytest.MonkeyPatch.context() as patch:
        tests.helpers.doubles.peri_scribe.pipeline_fetch_recovery.install(
            patch,
            scenario,
        )
        patch.setattr(pathlib.Path, "replace", replace)
        patch.setattr(pathlib.Path, "write_text", write)
        if request.phase == "crash" and request.boundary == "marker":
            tests.formal.helpers.crash_worker.interruption(
                patch,
                request,
                peri_scribe.pipeline_state.state_path(directory),
            )
        with peri_scribe.pipeline_state.run_lock(directory) as acquired:
            assert acquired, "dead fetch process retained its year lock"
            assert peri_scribe.pipeline.run_fetch_stage(
                directory,
                full_fetch_interval=None,
                unconditional=False,
            )
    inspect()
    request.record(
        "complete",
        peri_scribe.pipeline_state.read_state(directory).model_dump(mode="json"),
    )
