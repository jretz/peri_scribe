"""Larger real feedback histories agree with the unbounded executable proof."""

import pathlib

import pytest

import tests.formal.helpers.identity_recomputation_large


@pytest.mark.parametrize(
    "mode",
    tests.formal.helpers.identity_recomputation_large.MODES,
)
@pytest.mark.parametrize("seed", range(2))
def test_resolved_ownership_matches_complete_unbounded_feedback_executor(
    tmp_path: pathlib.Path,
    mode: str,
    seed: int,
) -> None:
    expected = 8
    assert (
        tests.formal.helpers.identity_recomputation_large.check_sequences(
            tmp_path,
            mode,
            seed,
        )
        == expected
    )
