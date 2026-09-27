"""Run/phase evidence and bounded retention agree with the executable Lean policies."""

import pytest

import tests.formal.helpers.monitor_reconstruction


def test_append_records_and_phase_tree_match_lean_interleaved_histories() -> None:
    tests.formal.helpers.monitor_reconstruction.replay_histories()


def test_omission_reason_matches_lean_evidence_categories() -> None:
    tests.formal.helpers.monitor_reconstruction.replay_omissions()


@pytest.mark.parametrize("limit", [1, 2, 5, 20])
def test_append_records_preserves_lean_structural_retention(
    monkeypatch: pytest.MonkeyPatch,
    limit: int,
) -> None:
    tests.formal.helpers.monitor_reconstruction.replay_retention(monkeypatch, limit)


@pytest.mark.parametrize("limit", [1, 3, 10])
def test_append_records_matches_lean_run_retention(
    monkeypatch: pytest.MonkeyPatch,
    limit: int,
) -> None:
    tests.formal.helpers.monitor_reconstruction.replay_run_retention(monkeypatch, limit)


def test_phase_tree_matches_lean_planned_visibility_and_omission_composition() -> None:
    tests.formal.helpers.monitor_reconstruction.replay_planned_trees()
