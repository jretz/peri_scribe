"""Native admission waits for prerequisites and failed owners retire their children."""

import asyncio
import json
import pathlib
import sys
import unittest.mock

import pytest

import tests.formal.helpers.defect_checks
import tests.formal.helpers.fixtures.defects
import tests.formal.helpers.overlap
import tests.formal.helpers.overlap_checks
import tests.formal.helpers.process


@pytest.mark.asyncio
@pytest.mark.parametrize("regular_first", [False, True])
async def test_coordinator_run_requires_complete_proofs_and_regular_graph(
    tmp_path: pathlib.Path,
    *,
    regular_first: bool,
) -> None:
    with tests.formal.helpers.overlap_checks.controlled(tmp_path) as control:
        events = control.events
        if regular_first:
            events.regular.set()
        async with tests.formal.helpers.overlap_checks.running(
            control.coordinator,
        ) as task:
            await tests.formal.helpers.overlap_checks.observe(events.models_started)
            assert not events.formal_started.is_set()
            events.models.set()
            await tests.formal.helpers.overlap_checks.observe(events.lean_started)
            assert not events.formal_started.is_set()
            events.lean.set()
            await tests.formal.helpers.overlap_checks.observe(events.pristine_started)
            assert not events.formal_started.is_set()
            events.pristine.set()
            await tests.formal.helpers.overlap_checks.condition(
                lambda: any(
                    name == "pristine_graph_closed"
                    for name, _ in control.coordinator.events
                ),
            )
            if not regular_first:
                assert not events.formal_started.is_set()
                events.regular.set()
            await tests.formal.helpers.overlap_checks.observe(events.formal_started)
            assert control.coordinator.initial_workers == (
                tests.formal.helpers.overlap_checks.EXPECTED_FULL_WORKERS
            )
            assert events.formal_arguments == [
                sys.executable,
                "-m",
                "tests.formal.helpers.conformance",
                "--directory",
                str(tmp_path),
                "--source",
                control.coordinator.seal.identity,
                "--workers",
                "5",
            ]
            events.formal.set()
            await asyncio.wait_for(
                task,
                tests.formal.helpers.overlap_checks.GUARD_SECONDS,
            )
            assert not control.coordinator.aborted


@pytest.mark.asyncio
@pytest.mark.parametrize("admitted", [False, True])
@pytest.mark.parametrize("cancel", [False, True])
async def test_coordinator_run_rejects_failures_and_joins_cancellation(
    tmp_path: pathlib.Path,
    *,
    admitted: bool,
    cancel: bool,
) -> None:
    with tests.formal.helpers.overlap_checks.controlled(tmp_path) as control:
        events = control.events
        if admitted:
            events.ready()
            events.regular.set()
        async with tests.formal.helpers.overlap_checks.running(
            control.coordinator,
        ) as task:
            await tests.formal.helpers.overlap_checks.observe(events.regular_started)
            await tests.formal.helpers.overlap_checks.observe(
                events.formal_started if admitted else events.models_started,
            )
            if cancel:
                task.cancel()
            elif admitted:
                events.formal_status = 7
                events.formal.set()
            else:
                events.regular_status = 7
                events.regular.set()
            reasons = await tests.formal.helpers.overlap_checks.failure(task)
            phase = "formal" if admitted else "regular"
            assert any(
                "CancelledError" in reason
                if cancel
                else f"{phase} phase exited 7" in reason
                for reason in reasons
            )
            assert control.coordinator.aborted
            assert events.formal_started.is_set() == admitted
            assert events.formal_cancelled.is_set() == (admitted and cancel)
            assert not any(
                name == "all_positive_graphs_closed"
                for name, _ in control.coordinator.events
            )


@pytest.mark.asyncio
@pytest.mark.parametrize("admitted", [False, True])
async def test_coordinator_run_rejects_changed_source_at_phase_boundaries(
    tmp_path: pathlib.Path,
    *,
    admitted: bool,
) -> None:
    with tests.formal.helpers.overlap_checks.controlled(tmp_path) as control:
        events = control.events
        events.models.set()
        events.lean.set()
        if admitted:
            events.pristine.set()
            events.regular.set()
        async with tests.formal.helpers.overlap_checks.running(
            control.coordinator,
        ) as task:
            await tests.formal.helpers.overlap_checks.observe(
                events.formal_started if admitted else events.pristine_started,
            )
            control.source.write_text("value = 'changed source generation'\n")
            (events.formal if admitted else events.pristine).set()
            reasons = await tests.formal.helpers.overlap_checks.failure(task)
            assert any(
                "Source or configuration changed" in reason for reason in reasons
            )
            assert control.coordinator.aborted
            assert events.formal_started.is_set() == admitted


def test_run_rejects_inherited_process_ownership_before_creating_control_storage(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tests.formal.helpers.process, "inherited_group", lambda: 123)
    directory = unittest.mock.Mock(return_value=tmp_path)
    monkeypatch.setattr(
        tests.formal.helpers.overlap.tests.formal.helpers.session,
        "directory",
        directory,
    )
    with pytest.raises(
        tests.formal.helpers.overlap.PhaseError,
        match="independent process ownership",
    ):
        tests.formal.helpers.overlap.run()
    directory.assert_not_called()
    assert not list(tmp_path.iterdir())


def test_preserve_reports_copies_exact_current_invocation_bytes(
    tmp_path: pathlib.Path,
) -> None:
    directory = tmp_path / "control"
    directory.mkdir()
    with tests.formal.helpers.overlap_checks.controlled(directory) as control:
        destination = directory / "coverage"
        control.coordinator.coverage_directory = destination
        (directory / "formal.json").write_text('{"status":0,"reports":["actual"]}\n')
        (directory / "formal.xml").write_bytes(
            b'<testsuites><testcase name="actual" time="0.125"/></testsuites>\n',
        )
        (directory / "coordinator.json").write_text('{"status":0,"events":[]}\n')
        corpus = directory / "corpus"
        corpus.mkdir()
        baseline = tests.formal.helpers.fixtures.defects.baseline_name(
            tests.formal.helpers.defect_checks.DEFECTS,
        )
        (corpus / f"{baseline}.json").write_bytes(b'{ "current": "pristine" }\n')
        tests.formal.helpers.overlap.preserve_reports(control.coordinator)
        for source, target in (
            ("formal.json", "formal-protocols.json"),
            ("formal.xml", "formal-results.xml"),
            ("coordinator.json", "verification-phases.json"),
            ("source-inputs.json", "verification-inputs.json"),
            (f"corpus/{baseline}.json", "mutation-protocols.json"),
        ):
            assert (destination / target).read_bytes() == (
                directory / source
            ).read_bytes()
            assert not (destination / (target + ".tmp")).exists()


@pytest.mark.parametrize("output", ["", "Test artifacts: one\nTest artifacts: two\n"])
def test_coverage_directory_rejects_missing_or_ambiguous_artifact_location(
    output: str,
) -> None:
    with pytest.raises(tests.formal.helpers.overlap.PhaseError, match="one coverage"):
        tests.formal.helpers.overlap.coverage_directory(output)


def test_coverage_directory_rejects_a_mismatched_session(
    tmp_path: pathlib.Path,
) -> None:
    (tmp_path / "session.json").write_text('{"directory":"elsewhere","runId":"x"}')
    with pytest.raises(tests.formal.helpers.overlap.PhaseError, match="does not match"):
        tests.formal.helpers.overlap.coverage_directory(f"Test artifacts: {tmp_path}\n")


@pytest.mark.asyncio
async def test_coordinator_native_waits_for_real_nested_cooperative_cleanup(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = tests.formal.helpers.overlap_checks.native_owner(tmp_path, monkeypatch)
    task = asyncio.create_task(
        owner.guarded(
            owner.native(
                tests.formal.helpers.overlap_checks.command("controller", tmp_path),
                "formal",
            ),
        ),
    )
    try:
        await tests.formal.helpers.overlap_checks.condition(
            (tmp_path / "leaf-ready.json").exists,
        )
        controller = tests.formal.helpers.overlap_checks.identity(
            tmp_path,
            "controller",
        )
        leaf = tests.formal.helpers.overlap_checks.identity(tmp_path, "leaf")
        for identity in (controller, leaf):
            assert identity["pid"] == identity["group"] == identity["session"]
        assert leaf["group"] != controller["group"]
        task.cancel()
        reasons = await tests.formal.helpers.overlap_checks.failure(task)
        assert any("CancelledError" in reason for reason in reasons)
        assert owner.aborted
        assert json.loads((tmp_path / "cooperative-cleanup.json").read_text()) == {
            "reason": "CancelledError",
            "nested_execute_returned": True,
        }
        await tests.formal.helpers.overlap_checks.assert_closed(tmp_path)
    finally:
        await tests.formal.helpers.overlap_checks.close_native(task, tmp_path)


@pytest.mark.asyncio
async def test_coordinator_guarded_retires_real_processes_after_sibling_failure(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = tests.formal.helpers.overlap_checks.native_owner(tmp_path, monkeypatch)

    async def ordinary_failure() -> None:
        """Fail after the native controller and leaf own their process groups.

        Raises:
            tests.formal.helpers.overlap.PhaseError: The controlled regular failure.
        """
        await tests.formal.helpers.overlap_checks.condition(
            (tmp_path / "leaf-ready.json").exists,
        )
        message = "Ordinary failure during native admission"
        raise tests.formal.helpers.overlap.PhaseError(message)

    async def run_group() -> None:
        """Exercise the actual task group's cancellation after bounded publication."""
        async with asyncio.TaskGroup() as group:
            group.create_task(
                owner.guarded(
                    owner.native(
                        tests.formal.helpers.overlap_checks.command(
                            "controller",
                            tmp_path,
                        ),
                        "formal",
                    ),
                ),
            )
            group.create_task(owner.guarded(ordinary_failure()))

    task = asyncio.create_task(run_group())
    try:
        reasons = await tests.formal.helpers.overlap_checks.failure(task)
        assert any("Ordinary failure" in reason for reason in reasons)
        assert owner.aborted
        assert json.loads((tmp_path / "cooperative-cleanup.json").read_text()) == {
            "reason": "CancelledError",
            "nested_execute_returned": True,
        }
        await tests.formal.helpers.overlap_checks.assert_closed(tmp_path)
    finally:
        await tests.formal.helpers.overlap_checks.close_native(task, tmp_path)


@pytest.mark.asyncio
async def test_execute_preserves_native_result_after_physical_group_cleanup(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(tests.formal.helpers.process.GROUP_VARIABLE, raising=False)
    result = await tests.formal.helpers.process.execute(
        tests.formal.helpers.overlap_checks.command("exited-parent", tmp_path),
        standard_input="",
        cwd=tests.formal.helpers.overlap.DIRECTORY,
        maximum_seconds=tests.formal.helpers.overlap_checks.GUARD_SECONDS,
        can_start_nested_tools=False,
        wait_for_group_exit=True,
    )
    assert result == tests.formal.helpers.process.Result(
        returncode=7,
        stdout="native stdout\n",
        stderr="native stderr\n",
    )
    await tests.formal.helpers.overlap_checks.assert_closed(tmp_path)
