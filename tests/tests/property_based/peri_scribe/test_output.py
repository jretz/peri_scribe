"""Verify serialized documents, GeoPackages, and score distribution plots."""

from __future__ import annotations

import hypothesis
import hypothesis.strategies
import pytest

import peri_scribe.output


@hypothesis.given(
    scores=hypothesis.strategies.lists(
        hypothesis.strategies.integers(0, 10_000),
        max_size=40,
    ),
)
def test_score_share_curve_matches_direct_exceedance_counts(scores: list[int]) -> None:
    expected = [
        (score, sum(other > score for other in scores) / len(scores))
        for score in sorted(set(scores))
        if any(other > score for other in scores)
    ]
    values, shares = peri_scribe.output.score_share_curve(scores)
    assert values.tolist() == [score for score, _share in expected]
    assert shares.tolist() == pytest.approx([share for _score, share in expected])
