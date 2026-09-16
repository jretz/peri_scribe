"""Typed execution boundaries keep producer and observer identities consistent."""

import typing
import uuid

import pytest

import peri_scribe.logging
import peri_scribe.phases
import peri_scribe.pipeline_stages


if typing.TYPE_CHECKING:
    import structlog.testing


def test_log_phase_rejects_unregistered_string() -> None:
    with (
        pytest.raises(TypeError, match="Undeclared phase"),
        peri_scribe.logging.log_phase(
            typing.cast("peri_scribe.phases.Identifier", "fetch"),
        ),
    ):
        pytest.fail("An untyped phase was accepted")


def test_log_phase_rejects_invalid_parentage() -> None:
    with (
        peri_scribe.logging.log_phase(peri_scribe.pipeline_stages.Stage.SCORE),
        pytest.raises(ValueError, match="not a child of score"),
        peri_scribe.logging.log_phase(peri_scribe.phases.Phase.CHECK_METADATA),
    ):
        pytest.fail("An invalid phase parent was accepted")


def test_log_phase_propagates_run_and_branch_identity_to_ordinary_events(
    log_output: structlog.testing.LogCapture,
) -> None:
    with (
        peri_scribe.logging.log_execution("command", "run"),
        peri_scribe.logging.log_phase(peri_scribe.pipeline_stages.Stage.FETCH),
        peri_scribe.logging.log_phase(peri_scribe.phases.Phase.FIRE_COLLECTION),
        peri_scribe.logging.log_phase(
            peri_scribe.phases.Phase.COLLECT_FEED,
            feed="alpha",
        ),
        peri_scribe.logging.log_phase(peri_scribe.phases.Phase.QUERY_FEATURES),
    ):
        peri_scribe.logging.logger.info("A page arrived")
    entry = next(
        entry for entry in log_output.entries if entry["event"] == "A page arrived"
    )
    assert entry["phase_segments"] == [
        {"phase": "fetch", "branch": ""},
        {"phase": "fire-collection", "branch": ""},
        {"phase": "collect-feed", "branch": "alpha"},
        {"phase": "query-features", "branch": ""},
    ]
    assert len({entry["run_id"] for entry in log_output.entries}) == 1
    assert uuid.UUID(entry["run_id"])
    assert entry["process_id"] > 0
    peri_scribe.logging.logger.info("Outside command")
    assert "run_id" not in log_output.entries[-1]
    assert "phase_segments" not in log_output.entries[-1]


def test_log_execution_assigns_distinct_run_ids(
    log_output: structlog.testing.LogCapture,
) -> None:
    for _ in range(2):
        with peri_scribe.logging.log_execution("command", "run"):
            pass
    starts = [
        entry for entry in log_output.entries if entry["event"] == "Starting command"
    ]
    assert starts[0]["run_id"] != starts[1]["run_id"]
