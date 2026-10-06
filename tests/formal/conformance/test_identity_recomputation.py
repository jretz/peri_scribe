"""Fresh resolution after persisted alias learning obeys complete TLC paths."""

import pathlib

import pytest

import tests.formal.helpers.corpus
import tests.formal.helpers.identity_recomputation


def test_resolved_ownership_recomputation_matches_checked_feedback_paths(
    tmp_path: pathlib.Path,
) -> None:
    graph = tests.formal.helpers.corpus.graph(
        "IdentityRecomputation",
        "IdentityRecomputationBridge",
        tmp_path / "model",
    )
    expected_cases = 256
    assert (
        tests.formal.helpers.identity_recomputation.replay(
            graph,
            tmp_path / "checkpoints",
        )
        == expected_cases
    )


def test_successor_rejects_reachable_acknowledgement_before_alias_learning(
    tmp_path: pathlib.Path,
) -> None:
    graph = tests.formal.helpers.corpus.graph(
        "IdentityRecomputation",
        "IdentityRecomputationBridge",
        tmp_path,
    )
    initial = next(iter(graph.initial))
    resolved = tests.formal.helpers.identity_recomputation.successor(
        graph,
        initial,
        "Resolve",
    )
    learned = tests.formal.helpers.identity_recomputation.successor(
        graph,
        resolved,
        "Learn",
    )
    acknowledged = tests.formal.helpers.identity_recomputation.successor(
        graph,
        learned,
        "Acknowledge",
    )
    assert acknowledged in graph.states
    with pytest.raises(AssertionError):
        tests.formal.helpers.identity_recomputation.successor(
            graph,
            resolved,
            "Acknowledge",
        )
