"""Real process teardown is distinct from exceptions that execute cleanup handlers."""

import pathlib

import pytest

import tests.formal.helpers.journal_builder
import tests.formal.helpers.log_rotation
import tests.formal.helpers.paths
import tests.formal.helpers.process_crashes


@pytest.mark.parametrize(
    ("boundary", "after", "method"),
    tests.formal.helpers.process_crashes.MARKER_FAULTS,
)
def test_run_fetch_stage_recovers_after_hard_process_termination(
    tmp_path: pathlib.Path,
    crash_marker_contract: tests.formal.helpers.paths.Contract[
        tests.formal.helpers.process_crashes.Marker
    ],
    boundary: str,
    *,
    after: bool,
    method: str,
) -> None:
    tests.formal.helpers.process_crashes.markers(
        tmp_path,
        crash_marker_contract,
        (boundary, after, method),
    )


@pytest.mark.parametrize(
    ("boundary", "after", "method"),
    tests.formal.helpers.process_crashes.BUILDER_FAULTS,
)
def test_create_kmz_recovers_in_a_fresh_interpreter_after_hard_termination(
    tmp_path: pathlib.Path,
    crash_builder_contract: tests.formal.helpers.paths.Contract[
        tests.formal.helpers.journal_builder.Projection
    ],
    boundary: str,
    *,
    after: bool,
    method: str,
) -> None:
    tests.formal.helpers.process_crashes.builders(
        tmp_path,
        crash_builder_contract,
        (boundary, after, method),
    )


@pytest.mark.parametrize(
    ("boundary", "after", "method"),
    tests.formal.helpers.process_crashes.ROTATION_FAULTS,
)
def test_compress_log_recovers_receipts_after_hard_process_termination(
    tmp_path: pathlib.Path,
    crash_rotation_contract: tests.formal.helpers.paths.Contract[
        tests.formal.helpers.log_rotation.Projection
    ],
    boundary: str,
    *,
    after: bool,
    method: str,
) -> None:
    tests.formal.helpers.process_crashes.rotations(
        tmp_path,
        crash_rotation_contract,
        (boundary, after, method),
    )


@pytest.mark.parametrize(
    "index",
    range(len(tests.formal.helpers.process_crashes.CACHE_BOUNDARIES)),
)
def test_scope_sqlite_recovers_without_python_transaction_cleanup(
    tmp_path: pathlib.Path,
    crash_cache_prefixes: dict[tuple[int, ...], dict[str, str]],
    index: int,
) -> None:
    tests.formal.helpers.process_crashes.caches(tmp_path, crash_cache_prefixes, index)
