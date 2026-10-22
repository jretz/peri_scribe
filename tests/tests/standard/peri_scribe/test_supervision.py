"""Supervised execution preserves actual leases, stage state and process outcomes."""

import asyncio
import concurrent.futures
import datetime
import json
import os
import pathlib
import runpy
import signal
import sys
import unittest.mock

import pydantic
import pytest

import peri_scribe.logging
import peri_scribe.pipeline
import peri_scribe.pipeline_state
import peri_scribe.supervision
import tests.helpers.doubles.peri_scribe.stage_parent
import tests.helpers.doubles.peri_scribe.stage_worker
import tests.helpers.doubles.peri_scribe.supervision
import tests.helpers.factories.peri_scribe.supervision
from measurement_units import units


def test_supervised_children_preserve_order_flags_frozen_inputs_and_one_lease(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        peri_scribe.supervision,
        "child_command",
        tests.helpers.doubles.peri_scribe.stage_parent.child_command,
    )
    request = tests.helpers.factories.peri_scribe.supervision.request(
        tmp_path,
    ).model_copy(
        update={
            "area_square_meters": 1.0,
            "publication_interval": datetime.timedelta(minutes=1),
        },
    )
    with peri_scribe.pipeline_state.run_lease(tmp_path) as descriptor:
        assert descriptor is not None
        peri_scribe.supervision.supervise(request, descriptor)
        with peri_scribe.pipeline_state.file_lock(tmp_path, shared=False) as competing:
            assert not competing
    entries = tests.helpers.factories.peri_scribe.supervision.events(tmp_path)
    assert [entry["stage"] for entry in entries] == [
        "geography",
        "score",
        "kmz",
        "reports",
    ]
    processes = [entry["process"] for entry in entries]
    assert processes[0] != processes[1]
    assert len(set(processes[1:])) == 1
    assert os.getpid() not in processes
    assert all(entry["run_context"] == request.run_context for entry in entries)
    assert entries[0]["options"] == {"unconditional": True}
    inputs = entries[2]["options"]["publication_inputs"]
    assert isinstance(inputs, dict)
    assert inputs["cities"] == "frozen cities"
    assert not peri_scribe.pipeline_state.read_state(tmp_path).remaining
    with peri_scribe.pipeline_state.run_lock(tmp_path) as acquired:
        assert acquired


@pytest.mark.parametrize("failure", ["geography", "score", "reports"])
def test_failed_child_preserves_exit_and_remaining_stage_prefix(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    monkeypatch.setattr(
        peri_scribe.supervision,
        "child_command",
        tests.helpers.doubles.peri_scribe.stage_parent.child_command,
    )
    (tmp_path / "mode.json").write_text(json.dumps({"failure": failure}))
    with peri_scribe.pipeline_state.run_lease(tmp_path) as descriptor:
        assert descriptor is not None
        with pytest.raises(SystemExit) as raised:
            peri_scribe.supervision.supervise(
                tests.helpers.factories.peri_scribe.supervision.request(tmp_path),
                descriptor,
            )
        assert (
            raised.value.code
            == tests.helpers.doubles.peri_scribe.stage_worker.FAILURE_EXIT
        )
    state = peri_scribe.pipeline_state.read_state(tmp_path)
    assert state.remaining[0] == failure
    assert state.unconditional


@pytest.mark.asyncio
async def test_public_command_has_one_log_boundary_and_one_identity_across_children(
    tmp_path: pathlib.Path,
) -> None:
    process = await tests.helpers.factories.peri_scribe.supervision.parent(tmp_path)
    _stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
    assert process.returncode == 0, stderr
    records = [
        json.loads(line)
        for path in sorted((tmp_path / "logs").glob("*.jsonl"))
        for line in path.read_text().splitlines()
    ]
    assert [record["event"] for record in records if "command" in record] == [
        "Starting command",
        "Finished command",
    ]
    assert [
        record["phase"] for record in records if record["event"] == "Starting phase"
    ] == ["geography", "score", "kmz", "reports"]
    boundaries = [
        record for record in records if "command" in record or "phase" in record
    ]
    assert len({record["run_id"] for record in boundaries}) == 1
    assert {record["process_id"] for record in boundaries} == {process.pid}
    assert records[-1]["status"] == "completed"


@pytest.mark.asyncio
@pytest.mark.parametrize("interruption", [signal.SIGINT, signal.SIGTERM])
async def test_parent_interruption_joins_child_before_releasing_lease(
    tmp_path: pathlib.Path,
    interruption: signal.Signals,
) -> None:
    (tmp_path / "mode.json").write_text(json.dumps({"wait": "geography"}))
    process = await tests.helpers.factories.peri_scribe.supervision.parent(tmp_path)
    child = await tests.helpers.factories.peri_scribe.supervision.wait_for_stage(
        tmp_path,
        "geography",
    )
    process.send_signal(interruption)
    _stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=15)
    assert process.returncode == (1 if interruption == signal.SIGINT else 143), stderr
    with pytest.raises(ProcessLookupError):
        os.kill(int(child["process"]), 0)
    with peri_scribe.pipeline_state.run_lock(tmp_path) as acquired:
        assert acquired
    assert peri_scribe.pipeline_state.read_state(tmp_path).remaining[0] == "geography"


@pytest.mark.asyncio
async def test_parent_crash_leaves_inherited_child_lease_live(
    tmp_path: pathlib.Path,
) -> None:
    (tmp_path / "mode.json").write_text(json.dumps({"wait": "geography"}))
    process = await tests.helpers.factories.peri_scribe.supervision.parent(tmp_path)
    child = await tests.helpers.factories.peri_scribe.supervision.wait_for_stage(
        tmp_path,
        "geography",
    )
    child_process = int(child["process"])
    try:
        process.kill()
        await process.wait()
        with peri_scribe.pipeline_state.run_lock(tmp_path) as acquired:
            assert not acquired
    finally:
        os.killpg(child_process, signal.SIGTERM)
        await asyncio.wait_for(process.communicate(), timeout=15)
    async with asyncio.timeout(10):
        while True:
            with peri_scribe.pipeline_state.run_lock(tmp_path) as acquired:
                if acquired:
                    break
            await asyncio.sleep(0.01)


def test_inherited_lease_rejects_another_year_and_preserves_parent_reference(
    tmp_path: pathlib.Path,
) -> None:
    other = tmp_path / "other"
    with peri_scribe.pipeline_state.run_lease(tmp_path) as descriptor:
        assert descriptor is not None
        other.mkdir()
        peri_scribe.pipeline_state.lock_path(other).touch()
        with (
            pytest.raises(ValueError, match="does not match"),
            peri_scribe.pipeline_state.inherited_lease(other, os.dup(descriptor)),
        ):
            pytest.fail("An unrelated lease must not be adopted")
        with peri_scribe.pipeline_state.run_lock(tmp_path) as acquired:
            assert not acquired


@pytest.mark.parametrize(
    "invalid",
    [
        {"start": 4, "end": 1},
        {"area_square_meters": 1.0},
        {"publication_interval": datetime.timedelta(minutes=1)},
        {"area_square_meters": 1.0, "publication_interval": datetime.timedelta(0)},
    ],
)
def test_serialized_request_rejects_inconsistent_selection(
    tmp_path: pathlib.Path,
    invalid: dict[str, object],
) -> None:
    values = tests.helpers.factories.peri_scribe.supervision.request(
        tmp_path,
    ).model_dump()
    with pytest.raises(pydantic.ValidationError, match="Invalid stage range"):
        peri_scribe.supervision.Request.model_validate(values | invalid)


def test_child_command_uses_current_interpreter_and_shell_free_arguments(
    tmp_path: pathlib.Path,
) -> None:
    request = tmp_path / "request with spaces.json"
    response = tmp_path / "response with spaces.json"
    assert peri_scribe.supervision.child_command(17, request, response) == [
        sys.executable,
        "-m",
        "peri_scribe.supervision",
        "17",
        str(request),
        str(response),
    ]


def test_unchanged_fetch_ends_without_starting_geography_or_a_second_child(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        peri_scribe.supervision,
        "child_command",
        tests.helpers.doubles.peri_scribe.stage_parent.child_command,
    )
    (tmp_path / "mode.json").write_text(json.dumps({"skip": True}))
    request = tests.helpers.factories.peri_scribe.supervision.request(
        tmp_path,
    ).model_copy(update={"start": 0, "unconditional": False})
    with peri_scribe.pipeline_state.run_lease(tmp_path) as descriptor:
        assert descriptor is not None
        peri_scribe.supervision.supervise(request, descriptor)
    entries = tests.helpers.factories.peri_scribe.supervision.events(tmp_path)
    assert [entry["stage"] for entry in entries] == ["fetch"]
    assert not peri_scribe.pipeline_state.read_state(tmp_path).remaining


@pytest.mark.parametrize("positions", [[1], [2, 2]])
def test_invalid_continuation_stops_before_further_children(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    positions: list[int],
) -> None:
    transport = unittest.mock.Mock(
        side_effect=[
            peri_scribe.supervision.SegmentResult(next_stage=position)
            for position in positions
        ],
    )
    monkeypatch.setattr(peri_scribe.supervision, "run_child", transport)
    with peri_scribe.pipeline_state.run_lease(tmp_path) as descriptor:
        assert descriptor is not None
        with pytest.raises(ValueError, match="unexpected continuation"):
            peri_scribe.supervision.supervise(
                tests.helpers.factories.peri_scribe.supervision.request(tmp_path),
                descriptor,
            )
    assert transport.call_count == len(positions)


def test_signal_exit_does_not_require_or_accept_a_child_response(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        peri_scribe.supervision,
        "child_status",
        unittest.mock.AsyncMock(return_value=-signal.SIGTERM),
    )
    with pytest.raises(SystemExit) as raised:
        peri_scribe.supervision.run_child(
            tests.helpers.factories.peri_scribe.supervision.request(tmp_path),
            17,
            tmp_path,
        )
    assert raised.value.code == 128 + signal.SIGTERM


@pytest.mark.asyncio
async def test_launch_failure_returns_original_error_without_an_unowned_child(
    tmp_path: pathlib.Path,
) -> None:
    with peri_scribe.pipeline_state.run_lease(tmp_path) as descriptor:
        assert descriptor is not None
        with pytest.raises(FileNotFoundError):
            await peri_scribe.supervision.child_status(
                [str(tmp_path / "missing-interpreter")],
                descriptor,
            )


@pytest.mark.asyncio
async def test_cancellation_before_launch_handle_joins_despite_repeated_cancellation(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    launch = tests.helpers.doubles.peri_scribe.supervision.DelayedLaunch()
    monkeypatch.setattr(asyncio, "create_subprocess_exec", launch)
    with peri_scribe.pipeline_state.run_lease(tmp_path) as descriptor:
        assert descriptor is not None
        task = asyncio.create_task(
            peri_scribe.supervision.child_status(
                [sys.executable, "-c", "pass"],
                descriptor,
            ),
        )
        await asyncio.wait_for(launch.entered.wait(), timeout=5)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        launch.release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=5)
        assert launch.process is not None
        assert launch.process.returncode is not None
        with peri_scribe.pipeline_state.file_lock(tmp_path, shared=False) as competing:
            assert not competing


@pytest.mark.asyncio
async def test_cancellation_kills_a_child_that_ignores_termination(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        peri_scribe.supervision,
        "CHILD_EXIT_GRACE",
        0.01 * units.seconds,
    )
    (tmp_path / "mode.json").write_text(
        json.dumps({"wait": "geography", "ignore_termination": True}),
    )
    request_path = tmp_path / "request.json"
    request_path.write_text(
        tests.helpers.factories.peri_scribe.supervision.request(
            tmp_path,
        ).model_dump_json(),
    )
    with peri_scribe.pipeline_state.run_lease(tmp_path) as descriptor:
        assert descriptor is not None
        task = asyncio.create_task(
            peri_scribe.supervision.child_status(
                tests.helpers.doubles.peri_scribe.stage_parent.child_command(
                    descriptor,
                    request_path,
                    tmp_path / "response.json",
                ),
                descriptor,
            ),
        )
        entry = await tests.helpers.factories.peri_scribe.supervision.wait_for_stage(
            tmp_path,
            "geography",
        )
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=5)
        with pytest.raises(ProcessLookupError):
            os.kill(entry["process"], 0)


def test_thread_callers_leave_process_signal_handlers_unchanged() -> None:
    expected = signal.getsignal(signal.SIGINT), signal.getsignal(signal.SIGTERM)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        assert (
            executor.submit(
                tests.helpers.doubles.peri_scribe.supervision.thread_signal_scopes,
            ).result()
            == expected
        )
    assert (
        signal.getsignal(signal.SIGINT),
        signal.getsignal(signal.SIGTERM),
    ) == expected


@pytest.mark.parametrize("termination", [False, True])
def test_termination_scope_restores_handlers_after_interruption(
    *,
    termination: bool,
) -> None:
    previous = signal.getsignal(signal.SIGTERM)
    with (
        pytest.raises(SystemExit if termination else KeyboardInterrupt) as raised,
        peri_scribe.supervision.termination_cleanup(),
    ):
        signal.raise_signal(signal.SIGTERM if termination else signal.SIGINT)
    if termination:
        assert isinstance(raised.value, SystemExit)
        assert raised.value.code == 128 + signal.SIGTERM
    assert signal.getsignal(signal.SIGTERM) == previous


def test_private_module_entry_restores_context_and_closes_only_its_lease_reference(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = tests.helpers.factories.peri_scribe.supervision.request(tmp_path)
    request_path = tmp_path / "request.json"
    response_path = tmp_path / "response.json"
    request_path.write_text(request.model_dump_json())
    execute = unittest.mock.Mock(
        return_value=peri_scribe.supervision.SegmentResult(next_stage=2),
    )
    configure = unittest.mock.Mock()
    monkeypatch.setattr(peri_scribe.pipeline, "run_selected_stages", execute)
    monkeypatch.setattr(peri_scribe.logging, "configure_logging", configure)
    previous = peri_scribe.logging.RUN_CONTEXT.get()
    with peri_scribe.pipeline_state.run_lease(tmp_path) as descriptor:
        assert descriptor is not None
        inherited = os.dup(descriptor)
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "supervision",
                str(inherited),
                str(request_path),
                str(response_path),
            ],
        )
        runpy.run_path(str(peri_scribe.supervision.__file__), run_name="__main__")
        with pytest.raises(OSError, match="Bad file descriptor"):
            os.fstat(inherited)
        with peri_scribe.pipeline_state.file_lock(tmp_path, shared=False) as competing:
            assert not competing
    assert peri_scribe.logging.RUN_CONTEXT.get() == previous
    assert json.loads(response_path.read_text()) == execute.return_value.model_dump()
    configure.assert_called_once_with("critical", "critical", year_directory=tmp_path)
    assert execute.call_args.args == (tmp_path, 1, 4)
