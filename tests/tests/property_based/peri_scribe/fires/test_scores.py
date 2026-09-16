"""Tests for peri_scribe.fires.scores."""

from __future__ import annotations

import hypothesis
import pandas as pd
import pytest

import peri_scribe.fires.identity
import peri_scribe.fires.scores
import tests.helpers.factories.peri_scribe.fires.scores
import tests.helpers.strategies.peri_scribe.fires.scores


# This test is slow, so limit examples to keep routine test runs fast.
@hypothesis.settings(max_examples=25)
@hypothesis.given(
    observations=tests.helpers.strategies.peri_scribe.fires.scores.score_histories(),
    use_geometry=hypothesis.infer,
)
def test_fire_metrics_matches_independent_per_fire_reductions(
    observations: list[
        tests.helpers.factories.peri_scribe.fires.scores.ScoreObservation
    ],
    *,
    use_geometry: bool,
) -> None:
    frame = tests.helpers.factories.peri_scribe.fires.scores.metric_frame(
        observations,
        use_geometry=use_geometry,
    )
    metrics, first = peri_scribe.fires.scores.fire_metrics(
        frame,
        peri_scribe.fires.identity.group_keys(frame),
    )
    keys = {item.key for item in observations}
    assert set(metrics.index) == keys
    assert set(first.index) == keys
    for key in keys:
        rows = [item for item in observations if item.key == key]
        growth = [
            item.calculated_growth
            if use_geometry and item.calculated_growth is not None
            else item.reported_growth
            for item in rows
        ]
        known_growth = [value for value in growth if value is not None]
        if known_growth:
            assert metrics.loc[key, "max_growth"] == pytest.approx(max(known_growth))
        else:
            assert pd.isna(metrics.loc[key, "max_growth"])
        earliest = min(
            rows,
            key=lambda item: float("inf") if item.hour is None else item.hour,
        )
        area = (
            earliest.calculated_area
            if use_geometry and earliest.calculated_area is not None
            else earliest.reported_area
        )
        if area is None:
            assert pd.isna(first[key])
        else:
            assert first[key] == pytest.approx(area)
