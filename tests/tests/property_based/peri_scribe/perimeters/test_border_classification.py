"""Tests for peri_scribe.perimeters.border_classification."""

from __future__ import annotations

import hypothesis

import peri_scribe.perimeters.border_classification
import peri_scribe.perimeters.classification_data
import tests.helpers.assertions.peri_scribe.perimeters.classification
import tests.helpers.factories.peri_scribe.perimeters.classification
import tests.helpers.reference.peri_scribe.perimeters.classification
import tests.helpers.strategies.peri_scribe.perimeters.classification


@hypothesis.given(
    observations=tests.helpers.strategies.peri_scribe.perimeters.classification.observation_sequences(),
)
def test_unioned_observation_geometry_preserves_full_union_coverage(
    observations: list[peri_scribe.perimeters.classification_data.FireObservation],
) -> None:
    boundaries = (
        tests.helpers.factories.peri_scribe.perimeters.classification
    ).projected_boundaries()
    expected = (
        tests.helpers.reference.peri_scribe.perimeters.classification
    ).full_projected_union(
        observations,
    )
    actual = peri_scribe.perimeters.border_classification.unioned_observation_geometry(
        observations,
        boundaries,
    )
    if expected is None:
        assert actual is None
    else:
        assert actual is not None
        tests.helpers.assertions.peri_scribe.perimeters.classification.assert_same_projected_coverage(
            actual,
            expected,
        )
