"""Recover retained city databases after actual process death at durable boundaries."""

import dataclasses
import json
import pathlib
import sys

import pydantic

import tests.formal.helpers.conditional_download
import tests.formal.helpers.conditional_download_worker
import tests.formal.helpers.process
import tests.formal.helpers.tlc


def invoke(
    directory: pathlib.Path,
    *,
    operation: str,
    existing: str,
    boundary: str,
) -> tests.formal.helpers.process.Result:
    """Require the selected child operation to run in a fresh interpreter.

    Args:
        directory: Private files shared only by this crash and recovery pair.
        operation: Terminate a writer or recover its retained database.
        existing: Whether the initial writer starts with absent or valid output.
        boundary: Independently durable interruption boundary.

    Returns:
        Actual exit status and captured subprocess diagnostics.
    """
    return tests.formal.helpers.process.run(
        [sys.executable, "-m", "tests.formal.helpers.conditional_download_worker"],
        standard_input=json.dumps({
            "directory": str(directory),
            "operation": operation,
            "existing": existing,
            "boundary": boundary,
        }),
        cwd=pathlib.Path(__file__).resolve().parents[3],
        timeout=30,
    )


def replay(
    graph: tests.formal.helpers.tlc.Graph,
    directory: pathlib.Path,
    *,
    existing: str,
    boundary: str,
) -> None:
    """Check exact ordered observations across process death and retained-file recovery.

    Args:
        graph: Complete checked protocol graph.
        directory: Isolated subprocess storage.
        existing: Absent or valid initial SQLite database.
        boundary: Partial conversion, validated staging, or published replacement.
    """
    directory.mkdir()
    (directory / "graph.json").write_bytes(
        pydantic.TypeAdapter(tests.formal.helpers.tlc.Graph).dump_json(graph),
    )
    result = invoke(directory, operation="crash", existing=existing, boundary=boundary)
    assert (
        result.returncode
        == tests.formal.helpers.conditional_download_worker.EXIT_STATUS
    ), (
        result.stdout,
        result.stderr,
    )
    assert not (directory / "finally-ran").exists()
    records = [
        json.loads(line)
        for line in (directory / "trace.jsonl").read_text().splitlines()
    ]
    adapter = pydantic.TypeAdapter(tests.formal.helpers.conditional_download.Projection)
    checked = tests.formal.helpers.conditional_download.contract(
        graph,
        previous=existing == "valid",
        validators="etag",
    )
    assert records[0]["action"] == "start"
    path = checked.start(adapter.validate_python(records[0]["value"]))
    for record in records[1:]:
        path = path.transition(
            record["action"],
            adapter.validate_python(record["value"]),
        )
    path = path.transition(
        "Crash",
        dataclasses.replace(path.value, outcome="interrupted"),
    )
    assert path.value.final == (
        2 if boundary == "published" else int(existing == "valid")
    )
    recovery = invoke(
        directory,
        operation="recover",
        existing=existing,
        boundary=boundary,
    )
    assert recovery.returncode == 0, (recovery.stdout, recovery.stderr)
    recovered = json.loads(recovery.stdout.splitlines()[-1])
    if boundary == "published":
        expected_name, expected_validator = "New Place", '"second"'
    elif existing == "valid":
        expected_name, expected_validator = "Bakersfield", '"first"'
    else:
        expected_name, expected_validator = None, None
    assert recovered == {
        "previous": expected_name,
        "recovered": expected_name or "Recovered Place",
        "headers": {"If-None-Match": expected_validator} if expected_validator else {},
    }
