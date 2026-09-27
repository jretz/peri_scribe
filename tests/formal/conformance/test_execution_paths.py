"""Reachable states alone cannot justify reordered or incomplete concrete histories."""

import dataclasses
import pathlib

import pytest

import tests.formal.helpers.path_checks


def test_path_observe_accepts_internal_steps_and_explicit_stutters(
    tmp_path: pathlib.Path,
) -> None:
    contract, observations = tests.formal.helpers.path_checks.rotation(tmp_path)
    path = contract.start(observations[0])
    assert len(path.candidates) > 1
    for value in observations:
        path = path.observe(value).observe(value)
    assert path.value == observations[-1]


def test_path_observe_rejects_reordered_reachable_states(
    tmp_path: pathlib.Path,
) -> None:
    contract, observations = tests.formal.helpers.path_checks.rotation(tmp_path)
    path = contract.start(observations[0])
    for value in observations[1:3]:
        path = path.observe(value)
    assert observations[1] in contract.values.values()
    with pytest.raises(AssertionError, match="no compatible TLC execution"):
        path.observe(observations[1])


def test_path_observe_rejects_skipping_a_durable_operation(
    tmp_path: pathlib.Path,
) -> None:
    contract, observations = tests.formal.helpers.path_checks.rotation(tmp_path)
    assert observations[2] in contract.values.values()
    with pytest.raises(AssertionError, match="no compatible TLC execution"):
        contract.start(observations[0]).observe(observations[2])


def test_path_event_consumes_only_observed_crash_budget(tmp_path: pathlib.Path) -> None:
    contract, observations = tests.formal.helpers.path_checks.rotation(tmp_path)
    path = contract.start(observations[0]).event("Crash").event("Crash")
    with pytest.raises(AssertionError, match="no compatible TLC event"):
        path.event("Crash")


def test_contract_start_rejects_noninitial_reachable_state(
    tmp_path: pathlib.Path,
) -> None:
    contract, observations = tests.formal.helpers.path_checks.rotation(tmp_path)
    assert observations[-1] in contract.values.values()
    with pytest.raises(AssertionError, match="no compatible TLC initial state"):
        contract.start(observations[-1])


def test_path_transition_requires_explicit_action_and_observed_value(
    tmp_path: pathlib.Path,
) -> None:
    contract, observations = tests.formal.helpers.path_checks.rotation(tmp_path)
    contract = dataclasses.replace(
        contract,
        internal=contract.internal - {"WriteReceipt"},
    )
    path = contract.start(observations[0])
    with pytest.raises(AssertionError, match="no compatible TLC execution"):
        path.observe(observations[1])
    with pytest.raises(AssertionError, match="no compatible TLC event"):
        path.transition("Publish", observations[1])
    with pytest.raises(AssertionError, match="no compatible TLC event"):
        path.event("WriteReceipt")
    path = path.transition("WriteReceipt", observations[1])
    assert path.value == observations[1]


def test_path_terminal_exit_requires_unchanged_projection(
    tmp_path: pathlib.Path,
) -> None:
    contract, observations = tests.formal.helpers.path_checks.rotation(tmp_path)
    path = contract.start(observations[0])
    for value in observations[1:]:
        path = path.observe(value)
    phases = frozenset({'"idle"'})
    assert path.event("Exit", terminal_phases=phases).value == observations[-1]
    assert observations[1] in contract.values.values()
    with pytest.raises(AssertionError, match="no compatible TLC event"):
        path.transition("Exit", observations[1], terminal_phases=phases)
